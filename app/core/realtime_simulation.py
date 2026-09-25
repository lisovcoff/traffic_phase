from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
import json
import math
from threading import RLock
from typing import BinaryIO
import zipfile

from app.core.intersection_config import (
    DEFAULT_INTERSECTION_CONFIG,
    IntersectionConfig,
)
from app.core.intersection_topology import IntersectionTopology
from app.core.models import Trajectory, TrajectoryEvent
from app.core.preprocessing import load_trajectory_payload
from app.core.realtime_inference import RealtimeSignalInferenceEngine
from app.core.reconstruction import extract_events_from_trajectories
from app.core.trajectory_events import CausalTrajectoryEventExtractor
from app.core.signal_state_estimator import (
    DEFAULT_RED_YELLOW_DURATION_SECONDS,
    DEFAULT_YELLOW_DURATION_SECONDS,
)


DEFAULT_SIMULATION_SPEED = 1.0
MAX_SIMULATION_SPEED = 1000.0
MAX_ACTIVE_SIMULATIONS = 4


@dataclass(frozen=True)
class ScheduledTrajectoryEvidence:
    available_timestamp_ms: int
    start_timestamp_ms: int
    trajectory_key: str
    events: tuple[TrajectoryEvent, ...] = ()
    trajectory: Trajectory | None = None


@dataclass(frozen=True)
class RealtimeSimulationSource:
    filename: str
    source_format: str
    start_timestamp_ms: int
    end_timestamp_ms: int
    trajectory_count: int
    event_count: int
    items: tuple[ScheduledTrajectoryEvidence, ...]


def _trajectory_bounds_ms(trajectory: Trajectory) -> tuple[int, int]:
    if trajectory.detections:
        timestamps = [item.millis for item in trajectory.detections]
        return min(timestamps), max(timestamps)
    timestamp = int(trajectory.timestamp_ms)
    return timestamp, timestamp


def _scheduled_items(
    trajectories: list[Trajectory],
    *,
    key_prefix: str,
) -> list[ScheduledTrajectoryEvidence]:
    scheduled: list[ScheduledTrajectoryEvidence] = []
    for index, trajectory in enumerate(trajectories):
        start_ms, available_ms = _trajectory_bounds_ms(trajectory)
        events = tuple(
            sorted(
                extract_events_from_trajectories((trajectory,)),
                key=lambda item: (
                    item.timestamp_ms,
                    item.event_type.value,
                    item.approach,
                    item.movement,
                ),
            )
        )
        scheduled.append(
            ScheduledTrajectoryEvidence(
                available_timestamp_ms=available_ms,
                start_timestamp_ms=start_ms,
                trajectory_key=(
                    f"{key_prefix}:{index}:{trajectory.vehicle_id}"
                ),
                events=events,
                trajectory=trajectory,
            )
        )
    return scheduled


def _source_from_items(
    items: list[ScheduledTrajectoryEvidence],
    *,
    filename: str,
    source_format: str,
) -> RealtimeSimulationSource:
    if not items:
        raise ValueError("no usable car trajectories found")
    items.sort(
        key=lambda item: (
            item.start_timestamp_ms,
            item.available_timestamp_ms,
            item.trajectory_key,
        )
    )
    return RealtimeSimulationSource(
        filename=filename,
        source_format=source_format,
        start_timestamp_ms=min(item.start_timestamp_ms for item in items),
        end_timestamp_ms=max(item.available_timestamp_ms for item in items),
        trajectory_count=len(items),
        event_count=sum(len(item.events) for item in items),
        items=tuple(items),
    )


def load_realtime_simulation_source(
    stream: BinaryIO,
    *,
    filename: str,
) -> RealtimeSimulationSource:
    """Prepare a compact causal playback schedule.

    ZIP members are decoded one at a time. Full detector payloads are reduced
    to normalized Trajectory/Detection models; bbox/score metadata is discarded.
    Offline events are retained only for diagnostics/backward compatibility.
    Causal playback never releases them early: it feeds normalized detections
    to a stateful extractor only after each detection timestamp is reached.
    """
    lowered = filename.lower()
    if lowered.endswith(".json"):
        payload = json.load(stream)
        trajectories = load_trajectory_payload(payload)
        items = _scheduled_items(
            trajectories,
            key_prefix="json",
        )
        return _source_from_items(
            items,
            filename=filename,
            source_format="json",
        )

    if lowered.endswith(".zip"):
        items: list[ScheduledTrajectoryEvidence] = []
        json_member_count = 0
        with zipfile.ZipFile(stream) as archive:
            members = [
                member
                for member in archive.infolist()
                if not member.is_dir()
                and member.filename.lower().endswith(".json")
            ]
            if not members:
                raise ValueError(
                    "ZIP archive contains no JSON trajectory files"
                )
            for member_index, member in enumerate(members):
                with archive.open(member) as handle:
                    payload = json.load(handle)
                trajectories = load_trajectory_payload(payload)
                items.extend(
                    _scheduled_items(
                        trajectories,
                        key_prefix=f"zip:{member_index}",
                    )
                )
                json_member_count += 1
                del payload
                del trajectories

        source = _source_from_items(
            items,
            filename=filename,
            source_format="zip",
        )
        if json_member_count <= 0:
            raise ValueError(
                "ZIP archive contains no JSON trajectory files"
            )
        return source

    raise ValueError(
        "Only JSON and ZIP trajectory files are supported"
    )


class RealtimeArchiveSimulation:
    """Deterministic, frontend-driven archive playback into realtime inference."""

    def __init__(
        self,
        source: RealtimeSimulationSource,
        phase_model: object,
        *,
        speed: float = DEFAULT_SIMULATION_SPEED,
        recent_window_s: float = 12.0,
        yellow_duration_seconds: float = DEFAULT_YELLOW_DURATION_SECONDS,
        red_yellow_duration_seconds: float = DEFAULT_RED_YELLOW_DURATION_SECONDS,
        topology: IntersectionTopology | None = None,
        intersection_config: IntersectionConfig | None = None,
    ) -> None:
        self.source = source
        self.speed = self._validated_speed(speed)
        self._phase_model = phase_model
        self._recent_window_s = float(recent_window_s)
        self._yellow_duration_seconds = float(
            yellow_duration_seconds
        )
        self._red_yellow_duration_seconds = float(
            red_yellow_duration_seconds
        )
        if (
            intersection_config is not None
            and topology is not None
            and intersection_config.to_topology().to_dict() != topology.to_dict()
        ):
            raise ValueError(
                "pass either matching intersection_config/topology, not conflicting values"
            )
        if intersection_config is None and topology is None:
            intersection_config = DEFAULT_INTERSECTION_CONFIG
        self._intersection_config = intersection_config
        self._topology = (
            intersection_config.to_topology()
            if intersection_config is not None
            else topology
        )
        self._lock = RLock()
        self._engine = self._new_engine()
        self._validate_source_topology()
        self._cursor = 0
        self._simulated_timestamp_ms = source.start_timestamp_ms
        self._emitted_trajectory_count = 0
        self._completed_trajectory_count = 0
        self._emitted_event_count = 0
        self._active_items: dict[str, ScheduledTrajectoryEvidence] = {}
        self._causal_extractors: dict[
            str,
            CausalTrajectoryEventExtractor,
        ] = {}
        self._detection_cursors: dict[str, int] = {}
        self._last_inference: dict[str, object] | None = None
        self._reset_observability()

    def _validate_source_topology(self) -> None:
        observed: set[str] = set()
        for item in self.source.items:
            if item.trajectory is not None:
                observed.add(item.trajectory.zone_in)
            observed.update(event.approach for event in item.events)
        unknown = sorted(observed - set(self._engine.topology.approaches))
        if unknown:
            raise ValueError(
                "incompatible realtime source approaches for the "
                f"configured topology: {', '.join(unknown)}"
            )

    def _reset_observability(self) -> None:
        approaches = tuple(self._engine.topology.approaches)
        self._unknown_sample_count = 0
        self._unknown_counts = {
            approach: 0 for approach in approaches
        }
        self._post_sync_sample_count = 0
        self._post_sync_unknown_counts = {
            approach: 0 for approach in approaches
        }
        self._unknown_recent = deque()
        self._override_count = 0
        self._override_started_ms: int | None = None
        self._override_total_ms = 0
        self._last_override_duration_ms: int | None = None
        self._last_adaptive_mode = "NORMAL"

    @staticmethod
    def _validated_speed(speed: float) -> float:
        value = float(speed)
        if (
            not math.isfinite(value)
            or value <= 0
            or value > MAX_SIMULATION_SPEED
        ):
            raise ValueError(
                f"speed must be in (0, {MAX_SIMULATION_SPEED}]"
            )
        return value

    def _new_engine(self) -> RealtimeSignalInferenceEngine:
        return RealtimeSignalInferenceEngine(
            self._phase_model,
            recent_window_s=self._recent_window_s,
            yellow_duration_seconds=self._yellow_duration_seconds,
            red_yellow_duration_seconds=self._red_yellow_duration_seconds,
            topology=self._topology,
            intersection_config=self._intersection_config,
        )

    @property
    def finished(self) -> bool:
        return (
            self._completed_trajectory_count
            >= self.source.trajectory_count
        )

    def reset(self) -> dict[str, object]:
        with self._lock:
            self._engine = self._new_engine()
            self._cursor = 0
            self._simulated_timestamp_ms = (
                self.source.start_timestamp_ms
            )
            self._emitted_trajectory_count = 0
            self._completed_trajectory_count = 0
            self._emitted_event_count = 0
            self._active_items.clear()
            self._causal_extractors.clear()
            self._detection_cursors.clear()
            self._last_inference = None
            self._reset_observability()
            return self.snapshot()

    def set_speed(self, speed: float) -> None:
        with self._lock:
            self.speed = self._validated_speed(speed)

    def step(
        self,
        elapsed_seconds: float = 1.0,
        *,
        speed: float | None = None,
    ) -> dict[str, object]:
        if elapsed_seconds <= 0 or not math.isfinite(elapsed_seconds):
            raise ValueError("elapsed_seconds must be positive")
        with self._lock:
            if speed is not None:
                self.speed = self._validated_speed(speed)

            advance_ms = max(
                1,
                int(round(elapsed_seconds * self.speed * 1000.0)),
            )
            target_ms = min(
                self.source.end_timestamp_ms,
                self._simulated_timestamp_ms + advance_ms,
            )
            self._emit_available(target_ms)
            if self._engine.current_timestamp_ms is not None:
                self._last_inference = (
                    self._engine.snapshot_at(target_ms).to_dict()
                )
            self._simulated_timestamp_ms = target_ms
            self._record_observability()
            return self.snapshot()

    def _emit_available(self, target_ms: int) -> None:
        while self._cursor < len(self.source.items):
            item = self.source.items[self._cursor]
            if item.start_timestamp_ms > target_ms:
                break
            self._active_items[item.trajectory_key] = item
            if item.trajectory is not None:
                self._causal_extractors[item.trajectory_key] = (
                    CausalTrajectoryEventExtractor(
                        approach=item.trajectory.zone_in,
                        movement=item.trajectory.movement,
                        zone_out=item.trajectory.zone_out,
                    )
                )
                self._detection_cursors[item.trajectory_key] = 0
            self._cursor += 1

        confirmed: list[tuple[str, TrajectoryEvent]] = []
        completed: list[str] = []

        for key, item in tuple(self._active_items.items()):
            trajectory = item.trajectory
            if trajectory is None:
                if item.available_timestamp_ms > target_ms:
                    continue
                if item.events:
                    confirmed.extend((key, event) for event in item.events)
                self._emitted_trajectory_count += 1
                self._completed_trajectory_count += 1
                completed.append(key)
                continue

            cursor = self._detection_cursors.get(key, 0)
            detections = trajectory.detections
            next_cursor = cursor
            while (
                next_cursor < len(detections)
                and detections[next_cursor].millis <= target_ms
            ):
                next_cursor += 1

            new_detections = detections[cursor:next_cursor]
            if new_detections and cursor == 0:
                self._emitted_trajectory_count += 1

            final = (
                next_cursor >= len(detections)
                and item.available_timestamp_ms <= target_ms
            )
            extractor = self._causal_extractors[key]
            if new_detections or final:
                events = extractor.ingest_snapshot(
                    new_detections,
                    final=final,
                )
                confirmed.extend((key, event) for event in events)
            self._detection_cursors[key] = next_cursor

            if final:
                if not detections:
                    self._emitted_trajectory_count += 1
                self._completed_trajectory_count += 1
                completed.append(key)

        confirmed.sort(
            key=lambda item: (
                item[1].timestamp_ms,
                item[1].event_type.value,
                item[1].approach,
                item[1].movement,
                item[0],
            )
        )
        if confirmed:
            events = [event for _key, event in confirmed]
            event_ids = [
                f"{key}:{event.event_type.value}:{event.timestamp_ms}"
                for key, event in confirmed
            ]
            inference = self._engine.ingest_events(
                events,
                event_ids=event_ids,
            )
            self._last_inference = inference.to_dict()
            self._emitted_event_count += len(events)

        for key in completed:
            self._active_items.pop(key, None)
            self._causal_extractors.pop(key, None)
            self._detection_cursors.pop(key, None)

    def _record_observability(self) -> None:
        approaches = tuple(self._engine.topology.approaches)
        if self._last_inference is None:
            states = {
                approach: "UNKNOWN" for approach in approaches
            }
            synchronized = False
            adaptive_mode = "NORMAL"
        else:
            states = {
                approach: str(
                    self._last_inference.get(
                        "signal_states",
                        {},
                    ).get(approach, "UNKNOWN")
                )
                for approach in approaches
            }
            synchronized = (
                self._last_inference.get("synchronization_status")
                == "SYNCHRONIZED"
            )
            adaptive_mode = str(
                self._last_inference.get(
                    "adaptive_mode",
                    "NORMAL",
                )
            )

        self._unknown_sample_count += 1
        for approach, state in states.items():
            if state == "UNKNOWN":
                self._unknown_counts[approach] += 1

        if synchronized:
            self._post_sync_sample_count += 1
            for approach, state in states.items():
                if state == "UNKNOWN":
                    self._post_sync_unknown_counts[approach] += 1

        unknown_approaches = tuple(
            approach
            for approach, state in states.items()
            if state == "UNKNOWN"
        )
        self._unknown_recent.append(
            (
                self._simulated_timestamp_ms,
                unknown_approaches,
            )
        )
        cutoff_ms = self._simulated_timestamp_ms - 60_000
        while (
            self._unknown_recent
            and self._unknown_recent[0][0] < cutoff_ms
        ):
            self._unknown_recent.popleft()

        if (
            adaptive_mode == "LIVE_OVERRIDE"
            and self._last_adaptive_mode != "LIVE_OVERRIDE"
        ):
            self._override_count += 1
            self._override_started_ms = self._simulated_timestamp_ms
        elif (
            adaptive_mode != "LIVE_OVERRIDE"
            and self._last_adaptive_mode == "LIVE_OVERRIDE"
            and self._override_started_ms is not None
        ):
            duration_ms = max(
                0,
                self._simulated_timestamp_ms
                - self._override_started_ms,
            )
            self._override_total_ms += duration_ms
            self._last_override_duration_ms = duration_ms
            self._override_started_ms = None
        self._last_adaptive_mode = adaptive_mode

    @staticmethod
    def _rate(
        unknown_count: int,
        sample_count: int,
    ) -> float | None:
        if sample_count <= 0:
            return None
        return round(unknown_count / sample_count, 4)

    def _unknown_metrics(self) -> dict[str, object]:
        approaches = tuple(self._engine.topology.approaches)
        approach_count = max(1, len(approaches))
        total_states = self._unknown_sample_count * approach_count
        total_unknown = sum(self._unknown_counts.values())
        post_sync_states = (
            self._post_sync_sample_count * approach_count
        )
        post_sync_unknown = sum(
            self._post_sync_unknown_counts.values()
        )
        recent_samples = len(self._unknown_recent)
        recent_unknown = sum(
            len(unknown)
            for _timestamp, unknown in self._unknown_recent
        )
        post_sync_rate = self._rate(
            post_sync_unknown,
            post_sync_states,
        )
        overall_rate = self._rate(
            total_unknown,
            total_states,
        )
        rolling_rate = self._rate(
            recent_unknown,
            recent_samples * approach_count,
        )
        return {
            "sample_count": self._unknown_sample_count,
            "overall_rate": overall_rate,
            "unable_to_determine_rate": overall_rate,
            "determined_rate": (
                round(1.0 - overall_rate, 4)
                if overall_rate is not None
                else None
            ),
            "per_approach_rate": {
                approach: self._rate(
                    self._unknown_counts[approach],
                    self._unknown_sample_count,
                )
                for approach in approaches
            },
            "post_sync_sample_count": self._post_sync_sample_count,
            "post_sync_rate": post_sync_rate,
            "post_sync_per_approach_rate": {
                approach: self._rate(
                    self._post_sync_unknown_counts[approach],
                    self._post_sync_sample_count,
                )
                for approach in approaches
            },
            "rolling_60s_rate": rolling_rate,
            "post_sync_determined_rate": (
                round(1.0 - post_sync_rate, 4)
                if post_sync_rate is not None
                else None
            ),
            "rolling_60s_determined_rate": (
                round(1.0 - rolling_rate, 4)
                if rolling_rate is not None
                else None
            ),
        }

    def _override_metrics(self) -> dict[str, object]:
        active_ms = (
            max(
                0,
                self._simulated_timestamp_ms
                - self._override_started_ms,
            )
            if self._override_started_ms is not None
            else 0
        )
        return {
            "count": self._override_count,
            "active": self._override_started_ms is not None,
            "current_duration_s": round(active_ms / 1000.0, 3),
            "last_duration_s": (
                round(
                    self._last_override_duration_ms / 1000.0,
                    3,
                )
                if self._last_override_duration_ms is not None
                else None
            ),
            "total_duration_s": round(
                (self._override_total_ms + active_ms) / 1000.0,
                3,
            ),
        }

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            inference = self._last_inference
            if inference is None:
                synchronization_status = "WARMUP"
                phase_id = None
                phase = None
                signal_states = {
                    approach: "UNKNOWN"
                    for approach in self._engine.topology.approaches
                }
                active_movements: list[dict[str, object]] = []
                confidence = 0.0
                phase_confidence = 0.0
                cycle_position_s = None
                phase_offset_s = None
                synchronization_confidence = 0.0
                synchronization_evidence_count = 0
                buffer_event_count = 0
                adaptive_mode = "NORMAL"
                effective_axis = None
                template_expected_axis = None
                template_disagreement = False
                adaptive_confidence = 0.0
                adaptive_reason = None
                observed_live_approaches: list[str] = []
                template_signal_states = dict(signal_states)
                synchronization_match_ratio = 0.0
                template_compatibility = "CHECKING"
                instant_unknown_rate = 1.0
                unknown_reasons = {
                    approach: "no_release_or_crossing_evidence"
                    for approach in signal_states
                }
                template_deviation_seconds = None
            else:
                synchronization_status = str(
                    inference["synchronization_status"]
                )
                phase_id = inference["phase_id"]
                phase = inference["phase"]
                signal_states = dict(inference["signal_states"])
                active_movements = list(
                    inference.get("active_movements", [])
                )
                confidence = float(inference["confidence"])
                phase_confidence = float(
                    inference["phase_confidence"]
                )
                cycle_position_s = inference["cycle_position_s"]
                phase_offset_s = inference["phase_offset_s"]
                synchronization_confidence = float(
                    inference["synchronization_confidence"]
                )
                synchronization_evidence_count = int(
                    inference["synchronization_evidence_count"]
                )
                buffer_event_count = int(
                    inference["buffer_event_count"]
                )
                adaptive_mode = str(
                    inference.get("adaptive_mode", "NORMAL")
                )
                effective_axis = inference.get("effective_axis")
                template_expected_axis = inference.get(
                    "template_expected_axis"
                )
                template_disagreement = bool(
                    inference.get("template_disagreement", False)
                )
                adaptive_confidence = float(
                    inference.get("adaptive_confidence", 0.0)
                )
                adaptive_reason = inference.get("adaptive_reason")
                observed_live_approaches = list(
                    inference.get("observed_live_approaches", ())
                )
                template_signal_states = dict(
                    inference.get(
                        "template_signal_states",
                        signal_states,
                    )
                    or signal_states
                )
                synchronization_match_ratio = float(
                    inference.get(
                        "synchronization_match_ratio",
                        0.0,
                    )
                )
                template_compatibility = str(
                    inference.get(
                        "template_compatibility",
                        "CHECKING",
                    )
                )
                instant_unknown_rate = float(
                    inference.get(
                        "instant_unknown_rate",
                        0.0,
                    )
                )
                unknown_reasons = dict(
                    inference.get("unknown_reasons", {}) or {}
                )
                template_deviation_seconds = inference.get(
                    "template_deviation_seconds"
                )

            duration_ms = max(
                1,
                self.source.end_timestamp_ms
                - self.source.start_timestamp_ms,
            )
            progress = (
                self._simulated_timestamp_ms
                - self.source.start_timestamp_ms
            ) / duration_ms

            sync_state = self._engine.synchronization
            if sync_state.status != "WARMUP":
                warmup_reason = None
            elif sync_state.evidence_count <= 0:
                warmup_reason = "no_release_or_crossing_evidence"
            elif sync_state.observed_group_count < 2:
                warmup_reason = "only_one_family"
            else:
                warmup_reason = "insufficient_match_ratio_or_evidence"

            return {
                "simulated_timestamp_ms": (
                    self._simulated_timestamp_ms
                ),
                "source_start_timestamp_ms": (
                    self.source.start_timestamp_ms
                ),
                "source_end_timestamp_ms": (
                    self.source.end_timestamp_ms
                ),
                "progress": round(
                    max(0.0, min(1.0, progress)),
                    4,
                ),
                "speed": self.speed,
                "finished": self.finished,
                "phase_id": phase_id,
                "phase": phase,
                "signal_states": signal_states,
                "active_movements": active_movements,
                "confidence": confidence,
                "phase_confidence": phase_confidence,
                "cycle_position_s": cycle_position_s,
                "phase_offset_s": phase_offset_s,
                "synchronization_status": synchronization_status,
                "synchronization_confidence": (
                    synchronization_confidence
                ),
                "synchronization_observed_family_count": (
                    sync_state.observed_group_count
                ),
                "synchronization_match_ratio": round(
                    sync_state.match_ratio,
                    4,
                ),
                "template_compatibility": (
                    "INCONCLUSIVE"
                    if (
                        self.finished
                        and template_compatibility == "CHECKING"
                    )
                    else template_compatibility
                ),
                "warmup_reason": warmup_reason,
                "instant_unknown_rate": instant_unknown_rate,
                "unknown_reasons": unknown_reasons,
                "unknown_metrics": self._unknown_metrics(),
                "template_deviation_seconds": (
                    template_deviation_seconds
                ),
                "live_override_metrics": self._override_metrics(),
                "adaptive_mode": adaptive_mode,
                "effective_axis": effective_axis,
                "template_expected_axis": (
                    template_expected_axis
                ),
                "template_disagreement": template_disagreement,
                "adaptive_confidence": adaptive_confidence,
                "adaptive_reason": adaptive_reason,
                "observed_live_approaches": (
                    observed_live_approaches
                ),
                "template_signal_states": (
                    template_signal_states
                ),
                "evidence_summary": {
                    "synchronization_evidence_count": (
                        synchronization_evidence_count
                    ),
                    "buffer_event_count": buffer_event_count,
                    "emitted_trajectory_count": (
                        self._emitted_trajectory_count
                    ),
                    "emitted_event_count": (
                        self._emitted_event_count
                    ),
                    "active_trajectory_count": len(
                        self._active_items
                    ),
                    "completed_trajectory_count": (
                        self._completed_trajectory_count
                    ),
                    "remaining_trajectory_count": (
                        self.source.trajectory_count
                        - self._emitted_trajectory_count
                    ),
                    "unfinished_trajectory_count": (
                        self.source.trajectory_count
                        - self._completed_trajectory_count
                    ),
                },
                "source": {
                    "filename": self.source.filename,
                    "format": self.source.source_format,
                    "trajectory_count": (
                        self.source.trajectory_count
                    ),
                    "event_count": self.source.event_count,
                },
            }


class RealtimeSimulationRegistry:
    """Small bounded registry for interactive simulations."""

    def __init__(
        self,
        *,
        max_simulations: int = MAX_ACTIVE_SIMULATIONS,
    ) -> None:
        if max_simulations < 1:
            raise ValueError("max_simulations must be positive")
        self.max_simulations = int(max_simulations)
        self._items: OrderedDict[
            str,
            RealtimeArchiveSimulation,
        ] = OrderedDict()
        self._lock = RLock()

    def create(
        self,
        simulation_id: str,
        simulation: RealtimeArchiveSimulation,
    ) -> RealtimeArchiveSimulation:
        with self._lock:
            if simulation_id in self._items:
                raise ValueError(
                    f"simulation {simulation_id!r} already exists"
                )
            while len(self._items) >= self.max_simulations:
                self._items.popitem(last=False)
            self._items[simulation_id] = simulation
            return simulation

    def get(self, simulation_id: str) -> RealtimeArchiveSimulation:
        with self._lock:
            simulation = self._items.get(simulation_id)
            if simulation is None:
                raise KeyError(simulation_id)
            self._items.move_to_end(simulation_id)
            return simulation

    def remove(self, simulation_id: str) -> bool:
        with self._lock:
            return self._items.pop(
                simulation_id,
                None,
            ) is not None

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


__all__ = [
    "DEFAULT_SIMULATION_SPEED",
    "MAX_ACTIVE_SIMULATIONS",
    "MAX_SIMULATION_SPEED",
    "RealtimeArchiveSimulation",
    "RealtimeSimulationRegistry",
    "RealtimeSimulationSource",
    "ScheduledTrajectoryEvidence",
    "load_realtime_simulation_source",
]
