from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from threading import RLock
from typing import Iterable, Sequence

from app.core.anomaly_profile import TrafficBaselineProfile
from app.core.event_phase_discovery import EventPhaseDiscoveryResult
from app.core.intersection_topology import (
    DEFAULT_INTERSECTION_TOPOLOGY,
    IntersectionTopology,
)
from app.core.models import EventType, TrajectoryEvent
from app.core.realtime_inference import (
    DuplicateEventError,
    RealtimeSignalInferenceEngine,
)
from app.core.reconstruction import reconstruct_event_session
from app.core.trajectory_events import extract_trajectory_events
from app.core.trajectory_geometry import (
    build_trajectory_geometry,
    build_trajectory_model,
)


BOOTSTRAP_EVENT_TYPES = {
    EventType.RELEASE,
    EventType.CROSSING,
}


@dataclass(frozen=True)
class OnlineLearningStatus:
    mode: str
    ready: bool
    usable_event_count: int
    observation_seconds: float
    attempt_count: int
    last_model_quality: str | None
    last_confidence: float | None
    candidate_cycle_seconds: float | None
    candidate_coverage: float | None
    observed_cycles: float | None
    reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class OnlinePhaseBootstrap:
    """Learn the first reusable phase template from causal live events.

    The bootstrap only consumes RELEASE/CROSSING events that have already
    arrived. Reconstruction is throttled so a one-second input cadence does
    not rerun Batch inference every second. A model is accepted only when the
    existing Batch quality contract classifies it as PARTIAL or GOOD and the
    observation window contains several complete cycles.
    """

    def __init__(
        self,
        *,
        sampling_seconds: float = 2.0,
        bin_seconds: float = 2.0,
        min_observation_seconds: float = 600.0,
        min_observed_cycles: float = 8.0,
        min_usable_events: int = 32,
        retry_event_stride: int = 24,
        retry_seconds: float = 30.0,
        max_history_seconds: float = 6.0 * 60.0 * 60.0,
        max_events: int = 50_000,
    ) -> None:
        if sampling_seconds <= 0 or bin_seconds <= 0:
            raise ValueError("bootstrap sampling/bin seconds must be positive")
        if min_observation_seconds <= 0 or min_observed_cycles <= 0:
            raise ValueError("bootstrap observation limits must be positive")
        if min_usable_events < 8:
            raise ValueError("bootstrap min_usable_events must be at least 8")
        if retry_event_stride < 1 or retry_seconds <= 0:
            raise ValueError("bootstrap retry cadence must be positive")
        if max_history_seconds <= 0 or max_events < min_usable_events:
            raise ValueError("bootstrap history bounds are invalid")

        self.sampling_seconds = float(sampling_seconds)
        self.bin_seconds = float(bin_seconds)
        self.min_observation_seconds = float(min_observation_seconds)
        self.min_observed_cycles = float(min_observed_cycles)
        self.min_usable_events = int(min_usable_events)
        self.retry_event_stride = int(retry_event_stride)
        self.retry_seconds = float(retry_seconds)
        self.max_history_seconds = float(max_history_seconds)
        self.max_events = int(max_events)

        self._events: dict[str, TrajectoryEvent] = {}
        self._current_timestamp_ms: int | None = None
        self._last_attempt_timestamp_ms: int | None = None
        self._last_attempt_event_count = 0
        self._attempt_count = 0
        self._last_result = None
        self._accepted_model: EventPhaseDiscoveryResult | None = None
        self._status = OnlineLearningStatus(
            mode="LEARNING",
            ready=False,
            usable_event_count=0,
            observation_seconds=0.0,
            attempt_count=0,
            last_model_quality=None,
            last_confidence=None,
            candidate_cycle_seconds=None,
            candidate_coverage=None,
            observed_cycles=None,
            reason="need_release_or_crossing_evidence",
        )

    @property
    def accepted_model(self) -> EventPhaseDiscoveryResult | None:
        return self._accepted_model

    @property
    def events(self) -> tuple[TrajectoryEvent, ...]:
        return tuple(
            sorted(
                self._events.values(),
                key=lambda event: (
                    event.timestamp_ms,
                    event.event_type.value,
                    event.approach,
                    event.movement,
                ),
            )
        )

    @property
    def status(self) -> OnlineLearningStatus:
        return self._status

    def ingest_event(self, event: TrajectoryEvent) -> OnlineLearningStatus:
        if self._current_timestamp_ms is None:
            self._current_timestamp_ms = int(event.timestamp_ms)
        else:
            self._current_timestamp_ms = max(
                self._current_timestamp_ms,
                int(event.timestamp_ms),
            )

        if event.event_type in BOOTSTRAP_EVENT_TYPES:
            self._events[self._fingerprint(event)] = event
            self._trim()
        self._maybe_reconstruct()
        return self._status

    def evidence_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self._events.values():
            counts[event.approach] = counts.get(event.approach, 0) + 1
        return counts

    def _observation_seconds(self) -> float:
        if len(self._events) < 2:
            return 0.0
        timestamps = [
            event.timestamp_ms
            for event in self._events.values()
        ]
        return max(0.0, (max(timestamps) - min(timestamps)) / 1000.0)

    def _maybe_reconstruct(self) -> None:
        if self._accepted_model is not None:
            self._status = self._status_from_result(
                mode="READY",
                ready=True,
                reason="reusable_phase_model_learned",
            )
            return

        usable_count = len(self._events)
        observation_seconds = self._observation_seconds()
        if usable_count < self.min_usable_events:
            self._status = self._status_from_result(
                reason="need_more_release_or_crossing_events",
            )
            return
        if observation_seconds < self.min_observation_seconds:
            self._status = self._status_from_result(
                reason="need_more_observation_time",
            )
            return

        current_ms = self._current_timestamp_ms
        assert current_ms is not None
        enough_new_events = (
            usable_count - self._last_attempt_event_count
            >= self.retry_event_stride
        )
        enough_time = (
            self._last_attempt_timestamp_ms is None
            or current_ms - self._last_attempt_timestamp_ms
            >= int(self.retry_seconds * 1000.0)
        )
        if not enough_new_events and not enough_time:
            self._status = self._status_from_result(
                reason="waiting_for_next_learning_attempt",
            )
            return

        ordered = self.events
        self._attempt_count += 1
        self._last_attempt_event_count = usable_count
        self._last_attempt_timestamp_ms = current_ms
        result = reconstruct_event_session(
            ordered,
            start_timestamp_ms=ordered[0].timestamp_ms,
            end_timestamp_ms=ordered[-1].timestamp_ms,
            trajectory_count=0,
            sampling_seconds=self.sampling_seconds,
            bin_seconds=self.bin_seconds,
        )
        self._last_result = result

        if (
            result.status != "ok"
            or result.phase_model is None
            or result.cycle is None
        ):
            self._status = self._status_from_result(
                reason=(
                    result.error_reason
                    or "phase_model_not_reconstructed"
                ),
            )
            return

        cycle_seconds = float(result.cycle.estimate.cycle_seconds)
        observed_cycles = (
            observation_seconds / cycle_seconds
            if cycle_seconds > 0
            else 0.0
        )
        if observed_cycles < self.min_observed_cycles:
            self._status = self._status_from_result(
                observed_cycles=observed_cycles,
                reason="need_more_observed_cycles",
            )
            return

        if result.model_quality not in {"PARTIAL", "GOOD"}:
            self._status = self._status_from_result(
                observed_cycles=observed_cycles,
                reason="candidate_not_safe_for_realtime_template",
            )
            return

        self._accepted_model = result.phase_model
        self._status = self._status_from_result(
            mode="READY",
            ready=True,
            observed_cycles=observed_cycles,
            reason="reusable_phase_model_learned",
        )

    def _status_from_result(
        self,
        *,
        mode: str = "LEARNING",
        ready: bool = False,
        observed_cycles: float | None = None,
        reason: str,
    ) -> OnlineLearningStatus:
        result = self._last_result
        cycle_seconds = None
        coverage = None
        confidence = None
        quality = None
        if result is not None:
            quality = result.model_quality
            confidence = float(result.confidence)
            if result.cycle is not None:
                cycle_seconds = float(
                    result.cycle.estimate.cycle_seconds
                )
            if result.phase_model is not None:
                coverage = float(result.phase_model.cycle_coverage)
            if (
                observed_cycles is None
                and cycle_seconds is not None
                and cycle_seconds > 0
            ):
                observed_cycles = (
                    self._observation_seconds() / cycle_seconds
                )

        return OnlineLearningStatus(
            mode=mode,
            ready=ready,
            usable_event_count=len(self._events),
            observation_seconds=round(
                self._observation_seconds(),
                3,
            ),
            attempt_count=self._attempt_count,
            last_model_quality=quality,
            last_confidence=(
                round(confidence, 4)
                if confidence is not None
                else None
            ),
            candidate_cycle_seconds=(
                round(cycle_seconds, 3)
                if cycle_seconds is not None
                else None
            ),
            candidate_coverage=(
                round(coverage, 4)
                if coverage is not None
                else None
            ),
            observed_cycles=(
                round(observed_cycles, 3)
                if observed_cycles is not None
                else None
            ),
            reason=reason,
        )

    def _trim(self) -> None:
        if self._current_timestamp_ms is None:
            return
        cutoff_ms = self._current_timestamp_ms - int(
            self.max_history_seconds * 1000.0
        )
        stale = [
            key
            for key, event in self._events.items()
            if event.timestamp_ms < cutoff_ms
        ]
        for key in stale:
            self._events.pop(key, None)

        if len(self._events) <= self.max_events:
            return
        ordered = sorted(
            self._events.items(),
            key=lambda item: item[1].timestamp_ms,
        )
        for key, _event in ordered[: len(self._events) - self.max_events]:
            self._events.pop(key, None)

    @staticmethod
    def _fingerprint(event: TrajectoryEvent) -> str:
        payload = {
            "event_type": event.event_type.value,
            "timestamp_ms": int(event.timestamp_ms),
            "approach": event.approach,
            "movement": event.movement,
            "confidence": round(float(event.confidence), 6),
            "quality": event.quality,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class RealtimeOnlineSession:
    """One realtime stream that can start with or without a Batch template."""

    def __init__(
        self,
        phase_model: EventPhaseDiscoveryResult | None,
        *,
        recent_window_s: float = 12.0,
        event_origin_ms: int | None = None,
        yellow_duration_seconds: float = 3.0,
        red_yellow_duration_seconds: float = 2.0,
        baseline: TrafficBaselineProfile | None = None,
        topology: IntersectionTopology | None = None,
    ) -> None:
        self.topology = topology or DEFAULT_INTERSECTION_TOPOLOGY
        self.recent_window_s = float(recent_window_s)
        self.requested_event_origin_ms = (
            int(event_origin_ms)
            if event_origin_ms is not None
            else None
        )
        self.yellow_duration_seconds = float(yellow_duration_seconds)
        self.red_yellow_duration_seconds = float(
            red_yellow_duration_seconds
        )
        self.baseline_profile = baseline
        self._bootstrap = OnlinePhaseBootstrap()
        self._engine: RealtimeSignalInferenceEngine | None = None
        self._seeded = phase_model is not None
        self._online_learned = False
        self._seen: dict[str, tuple[str, int]] = {}
        self._current_timestamp_ms: int | None = None
        self._stream_start_timestamp_ms: int | None = None
        self._lock = RLock()

        if phase_model is not None:
            self._engine = self._make_engine(
                phase_model,
                event_origin_ms=event_origin_ms,
            )

    @property
    def phase_template_dict(self) -> dict[str, object] | None:
        if self._engine is None:
            return None
        return self._engine.phase_template.to_dict()

    @property
    def has_phase_template(self) -> bool:
        return self._engine is not None

    def ingest_event(
        self,
        event: TrajectoryEvent,
        *,
        event_id: str | None = None,
    ) -> dict[str, object]:
        if event.approach not in self.topology.approaches:
            raise ValueError(
                "event approach is not present in the configured "
                f"intersection topology: {event.approach}"
            )

        with self._lock:
            key = event_id or OnlinePhaseBootstrap._fingerprint(event)
            fingerprint = OnlinePhaseBootstrap._fingerprint(event)
            previous = self._seen.get(key)
            if previous is not None:
                if previous[0] != fingerprint:
                    raise DuplicateEventError(
                        f"idempotency key {key!r} was already used "
                        "for another event"
                    )
                return self._duplicate_snapshot()

            self._seen[key] = (fingerprint, int(event.timestamp_ms))
            if self._current_timestamp_ms is None:
                self._current_timestamp_ms = int(event.timestamp_ms)
                self._stream_start_timestamp_ms = int(event.timestamp_ms)
            else:
                self._current_timestamp_ms = max(
                    self._current_timestamp_ms,
                    int(event.timestamp_ms),
                )
            self._trim_seen()

            if self._engine is not None:
                snapshot = self._engine.ingest_event(
                    event,
                    event_id=key,
                ).to_dict()
                snapshot["learning"] = self._learning_payload()
                return snapshot

            status = self._bootstrap.ingest_event(event)
            learned_model = self._bootstrap.accepted_model
            if status.ready and learned_model is not None:
                self._engine = self._make_engine(
                    learned_model,
                    event_origin_ms=learned_model.origin_timestamp_ms,
                )
                self._online_learned = True
                snapshot = self._engine.ingest_event(
                    event,
                    event_id=key,
                ).to_dict()
                snapshot["learning"] = self._learning_payload()
                return snapshot

            return self._learning_snapshot(duplicate=False)

    def ingest_events(
        self,
        events: Iterable[TrajectoryEvent],
        *,
        event_ids: Sequence[str | None] | None = None,
    ) -> dict[str, object]:
        items = list(events)
        if event_ids is not None and len(event_ids) != len(items):
            raise ValueError("event_ids must match events length")
        snapshot = None
        for index, event in enumerate(items):
            snapshot = self.ingest_event(
                event,
                event_id=(
                    event_ids[index]
                    if event_ids is not None
                    else None
                ),
            )
        if snapshot is None:
            raise ValueError("at least one event is required")
        return snapshot

    def ingest_trajectory(
        self,
        trajectory: dict[str, object],
        *,
        trajectory_id: str | None = None,
    ) -> dict[str, object]:
        model = build_trajectory_model(trajectory)
        geometry = build_trajectory_geometry(trajectory)
        events = extract_trajectory_events(model, geometry)
        if not events:
            raise ValueError("trajectory produced no usable events")

        prefix = trajectory_id or str(model.vehicle_id)
        event_ids = [
            (
                f"{prefix}:{event.event_type.value}:"
                f"{event.timestamp_ms}:{event.approach}:"
                f"{event.movement}"
            )
            for event in events
        ]
        return self.ingest_events(events, event_ids=event_ids)

    def _make_engine(
        self,
        phase_model: EventPhaseDiscoveryResult,
        *,
        event_origin_ms: int | None,
    ) -> RealtimeSignalInferenceEngine:
        return RealtimeSignalInferenceEngine(
            phase_model,
            recent_window_s=self.recent_window_s,
            event_origin_ms=event_origin_ms,
            yellow_duration_seconds=self.yellow_duration_seconds,
            red_yellow_duration_seconds=self.red_yellow_duration_seconds,
            baseline=self.baseline_profile,
            topology=self.topology,
        )

    def _learning_payload(self) -> dict[str, object]:
        if self._seeded:
            data = self._bootstrap.status.to_dict()
            data.update({
                "mode": "SEEDED_TEMPLATE",
                "ready": True,
                "reason": "phase_model_supplied",
            })
            return data
        data = self._bootstrap.status.to_dict()
        if self._online_learned:
            data.update({
                "mode": "ONLINE_LEARNED",
                "ready": True,
                "reason": "reusable_phase_model_learned",
            })
        return data

    def _learning_snapshot(
        self,
        *,
        duplicate: bool,
    ) -> dict[str, object]:
        if self._current_timestamp_ms is None:
            raise ValueError("no realtime event has been ingested")
        start_ms = (
            self._stream_start_timestamp_ms
            if self._stream_start_timestamp_ms is not None
            else self._current_timestamp_ms
        )
        states = {
            approach: "UNKNOWN"
            for approach in self.topology.approaches
        }
        counts = self._bootstrap.evidence_counts()
        evidence_summary = {
            approach: {
                "state": "UNKNOWN",
                "evidence_weight": float(counts.get(approach, 0)),
                "supporting_event_count": counts.get(approach, 0),
                "contradictory_event_count": 0,
                "traffic_evidence_confidence": 0.0,
                "confidence": 0.0,
            }
            for approach in states
        }
        return {
            "timestamp_ms": self._current_timestamp_ms,
            "timestamp_s": round(
                (self._current_timestamp_ms - start_ms) / 1000.0,
                3,
            ),
            "phase_id": None,
            "phase": None,
            "signal_states": states,
            "active_movements": [],
            "confidence": 0.0,
            "phase_confidence": 0.0,
            "traffic_evidence_confidence": 0.0,
            "cycle_position_s": None,
            "evidence_summary": evidence_summary,
            "buffer_event_count": len(self._bootstrap.events),
            "synchronization_status": "LEARNING",
            "phase_offset_s": None,
            "synchronization_confidence": 0.0,
            "synchronization_evidence_count": 0,
            "synchronization_match_ratio": 0.0,
            "template_compatibility": "CHECKING",
            "instant_unknown_rate": 1.0,
            "unknown_reasons": {
                approach: "learning_phase_model"
                for approach in states
            },
            "template_deviation_seconds": None,
            "anomaly": None,
            "adaptive_mode": "NORMAL",
            "effective_axis": None,
            "template_expected_axis": None,
            "template_disagreement": False,
            "adaptive_confidence": 0.0,
            "adaptive_reason": "learning_phase_model",
            "observed_live_approaches": (),
            "template_signal_states": dict(states),
            "duplicate": duplicate,
            "learning": self._learning_payload(),
        }

    def _duplicate_snapshot(self) -> dict[str, object]:
        if self._engine is not None:
            snapshot = self._engine.snapshot().to_dict()
            snapshot["duplicate"] = True
            snapshot["learning"] = self._learning_payload()
            return snapshot
        return self._learning_snapshot(duplicate=True)

    def _trim_seen(self) -> None:
        if self._current_timestamp_ms is None:
            return
        horizon_seconds = max(
            self.recent_window_s,
            self._bootstrap.max_history_seconds,
        )
        cutoff_ms = self._current_timestamp_ms - int(
            horizon_seconds * 1000.0
        )
        stale = [
            key
            for key, (_fingerprint, timestamp_ms) in self._seen.items()
            if timestamp_ms < cutoff_ms
        ]
        for key in stale:
            self._seen.pop(key, None)


__all__ = [
    "OnlineLearningStatus",
    "OnlinePhaseBootstrap",
    "RealtimeOnlineSession",
]
