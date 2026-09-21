from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import json
import math
from threading import RLock
from typing import BinaryIO
import zipfile

from app.core.models import Trajectory, TrajectoryEvent
from app.core.preprocessing import load_trajectory_payload
from app.core.realtime_inference import RealtimeSignalInferenceEngine
from app.core.reconstruction import extract_events_from_trajectories


DEFAULT_SIMULATION_SPEED = 1.0
MAX_SIMULATION_SPEED = 1000.0
MAX_ACTIVE_SIMULATIONS = 4


@dataclass(frozen=True)
class ScheduledTrajectoryEvidence:
    available_timestamp_ms: int
    start_timestamp_ms: int
    trajectory_key: str
    events: tuple[TrajectoryEvent, ...]


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
            item.available_timestamp_ms,
            item.start_timestamp_ms,
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
    """Prepare a compact playback schedule without retaining raw detections.

    ZIP members are decoded one at a time. Each completed trajectory is reduced
    to its availability timestamp plus extracted events, then the decoded raw
    member can be released before the next member is processed.
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
        yellow_duration_seconds: float = 2.0,
    ) -> None:
        self.source = source
        self.speed = self._validated_speed(speed)
        self._phase_model = phase_model
        self._recent_window_s = float(recent_window_s)
        self._yellow_duration_seconds = float(
            yellow_duration_seconds
        )
        self._lock = RLock()
        self._engine = self._new_engine()
        self._cursor = 0
        self._simulated_timestamp_ms = source.start_timestamp_ms
        self._emitted_trajectory_count = 0
        self._emitted_event_count = 0
        self._last_inference: dict[str, object] | None = None

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
        )

    @property
    def finished(self) -> bool:
        return self._cursor >= len(self.source.items)

    def reset(self) -> dict[str, object]:
        with self._lock:
            self._engine = self._new_engine()
            self._cursor = 0
            self._simulated_timestamp_ms = (
                self.source.start_timestamp_ms
            )
            self._emitted_trajectory_count = 0
            self._emitted_event_count = 0
            self._last_inference = None
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
            return self.snapshot()

    def _emit_available(self, target_ms: int) -> None:
        while self._cursor < len(self.source.items):
            item = self.source.items[self._cursor]
            if item.available_timestamp_ms > target_ms:
                break

            # The trajectory is only released after its final detection time.
            # Event extraction may have happened offline, but realtime inference
            # sees none of its events before this availability boundary.
            if item.events:
                event_ids = [
                    (
                        f"{item.trajectory_key}:{index}:"
                        f"{event.event_type.value}:"
                        f"{event.timestamp_ms}"
                    )
                    for index, event in enumerate(item.events)
                ]
                inference = self._engine.ingest_events(
                    item.events,
                    event_ids=event_ids,
                )
                self._last_inference = inference.to_dict()
                self._emitted_event_count += len(item.events)

            self._emitted_trajectory_count += 1
            self._cursor += 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            inference = self._last_inference
            if inference is None:
                synchronization_status = "WARMUP"
                phase_id = None
                phase = None
                signal_states = {
                    approach: "UNKNOWN"
                    for approach in ("N", "S", "E", "W")
                }
                confidence = 0.0
                phase_confidence = 0.0
                cycle_position_s = None
                phase_offset_s = None
                synchronization_confidence = 0.0
                synchronization_evidence_count = 0
                buffer_event_count = 0
            else:
                synchronization_status = str(
                    inference["synchronization_status"]
                )
                phase_id = inference["phase_id"]
                phase = inference["phase"]
                signal_states = dict(inference["signal_states"])
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

            duration_ms = max(
                1,
                self.source.end_timestamp_ms
                - self.source.start_timestamp_ms,
            )
            progress = (
                self._simulated_timestamp_ms
                - self.source.start_timestamp_ms
            ) / duration_ms

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
                "confidence": confidence,
                "phase_confidence": phase_confidence,
                "cycle_position_s": cycle_position_s,
                "phase_offset_s": phase_offset_s,
                "synchronization_status": synchronization_status,
                "synchronization_confidence": (
                    synchronization_confidence
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
                    "remaining_trajectory_count": (
                        self.source.trajectory_count
                        - self._emitted_trajectory_count
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
