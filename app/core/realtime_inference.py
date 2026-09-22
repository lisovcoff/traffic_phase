from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from threading import RLock
from typing import Iterable, Sequence

from app.core.adaptive_realtime import (
    AdaptiveRealtimeDecision,
    AdaptiveRealtimeMode,
    AdaptiveRealtimeOverride,
)
from app.core.anomaly_profile import TrafficBaselineProfile
from app.core.anomaly_inference import AnomalyAwareSignalInference
from app.core.intersection_topology import (
    DEFAULT_INTERSECTION_TOPOLOGY,
    IntersectionTopology,
)
from app.core.models import TrajectoryEvent
from app.core.realtime_phase_sync import (
    PhaseSynchronization,
    RealtimePhaseSynchronizer,
    RealtimePhaseTemplate,
)
from app.core.signal_state_estimator import (
    DEFAULT_RED_YELLOW_DURATION_SECONDS,
    DEFAULT_YELLOW_DURATION_SECONDS,
    SignalStateEstimator,
)
from app.core.trajectory_events import extract_trajectory_events
from app.core.trajectory_geometry import (
    build_trajectory_geometry,
    build_trajectory_model,
)


@dataclass(frozen=True)
class RealtimeInferenceSnapshot:
    timestamp_ms: int
    timestamp_s: float
    phase_id: int | None
    phase: dict[str, object] | None
    signal_states: dict[str, str]
    active_movements: list[dict[str, object]]
    confidence: float
    phase_confidence: float
    traffic_evidence_confidence: float
    cycle_position_s: float | None
    evidence_summary: dict[str, dict[str, object]]
    buffer_event_count: int
    synchronization_status: str = "WARMUP"
    phase_offset_s: float | None = None
    synchronization_confidence: float = 0.0
    synchronization_evidence_count: int = 0
    anomaly: dict[str, object] | None = None
    adaptive_mode: str = "NORMAL"
    effective_axis: str | None = None
    template_expected_axis: str | None = None
    template_disagreement: bool = False
    adaptive_confidence: float = 0.0
    adaptive_reason: str | None = None
    observed_live_approaches: tuple[str, ...] = ()
    template_signal_states: dict[str, str] | None = None
    duplicate: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DuplicateEventError(ValueError):
    pass


class RealtimeSignalInferenceEngine:
    """Warm-start realtime inference with a conservative live override.

    The validated phase template is the normal operating prior. Repeated
    orthogonal RELEASE evidence may temporarily override the effective signal
    state without mutating that template. Synchronization scoring is frozen
    while the deviation is suspect/active and restarted during recovery.
    """

    def __init__(
        self,
        phase_model: object,
        *,
        recent_window_s: float = 12.0,
        event_origin_ms: int | None = None,
        min_phase_confidence: float = 0.20,
        min_traffic_confidence: float = 0.12,
        yellow_duration_seconds: float = DEFAULT_YELLOW_DURATION_SECONDS,
        red_yellow_duration_seconds: float = DEFAULT_RED_YELLOW_DURATION_SECONDS,
        conflict_persistence_seconds: float = 3.0,
        baseline: TrafficBaselineProfile | None = None,
        synchronization_min_events: int = 6,
        topology: IntersectionTopology | None = None,
    ) -> None:
        if recent_window_s <= 0:
            raise ValueError("recent_window_s must be positive")

        self.topology = topology or DEFAULT_INTERSECTION_TOPOLOGY
        self.phase_template = RealtimePhaseTemplate.from_phase_model(
            phase_model,
            topology=self.topology,
        )
        self.phase_model = self.phase_template.to_phase_model()
        self.recent_window_s = float(recent_window_s)
        self.event_origin_ms = (
            int(event_origin_ms)
            if event_origin_ms is not None
            else None
        )
        self._min_phase_confidence = float(min_phase_confidence)
        self._min_traffic_confidence = float(min_traffic_confidence)
        self._yellow_duration_seconds = float(yellow_duration_seconds)
        self._red_yellow_duration_seconds = float(
            red_yellow_duration_seconds
        )
        cycle = float(self.phase_template.cycle_seconds)
        if (
            self._yellow_duration_seconds < 0
            or self._yellow_duration_seconds >= cycle
        ):
            raise ValueError("invalid yellow_duration_seconds")
        if (
            self._red_yellow_duration_seconds < 0
            or self._red_yellow_duration_seconds >= cycle
        ):
            raise ValueError("invalid red_yellow_duration_seconds")
        self._conflict_persistence_seconds = float(
            conflict_persistence_seconds
        )
        self._anomaly_inference = AnomalyAwareSignalInference(
            self.phase_model,
            baseline,
        )
        self._adaptive_override = AdaptiveRealtimeOverride(
            evidence_window_seconds=min(8.0, self.recent_window_s),
            topology=self.topology,
        )
        self._synchronizer = RealtimePhaseSynchronizer(
            self.phase_template,
            min_evidence_events=synchronization_min_events,
            fixed_origin_ms=self.event_origin_ms,
        )
        self._events: dict[str, TrajectoryEvent] = {}
        self._seen: dict[str, tuple[str, int]] = {}
        self._current_timestamp_ms: int | None = None
        self._stream_start_timestamp_ms: int | None = None
        self._lock = RLock()

    @property
    def yellow_duration_seconds(self) -> float:
        return self._yellow_duration_seconds

    @property
    def red_yellow_duration_seconds(self) -> float:
        return self._red_yellow_duration_seconds

    @property
    def current_timestamp_ms(self) -> int | None:
        return self._current_timestamp_ms

    @property
    def buffer_event_count(self) -> int:
        return len(self._events)

    @property
    def baseline_profile(self) -> TrafficBaselineProfile | None:
        return self._anomaly_inference.baseline

    @property
    def synchronization(self) -> PhaseSynchronization:
        return self._synchronizer.snapshot()

    @property
    def adaptive_mode(self) -> AdaptiveRealtimeMode:
        return self._adaptive_override.mode

    def ingest_event(
        self,
        event: TrajectoryEvent,
        *,
        event_id: str | None = None,
    ) -> RealtimeInferenceSnapshot:
        with self._lock:
            key = event_id or self._event_fingerprint(event)
            fingerprint = self._event_fingerprint(event)

            previous = self._seen.get(key)
            if previous is not None:
                if previous[0] != fingerprint:
                    raise DuplicateEventError(
                        f"idempotency key {key!r} was already used for another event"
                    )
                return self._snapshot(duplicate=True)

            self._seen[key] = (fingerprint, event.timestamp_ms)
            if self._current_timestamp_ms is None:
                self._current_timestamp_ms = event.timestamp_ms
                self._stream_start_timestamp_ms = event.timestamp_ms
            else:
                self._current_timestamp_ms = max(
                    self._current_timestamp_ms,
                    event.timestamp_ms,
                )

            cutoff_ms = self._current_timestamp_ms - int(
                self.recent_window_s * 1000.0
            )
            if event.timestamp_ms >= cutoff_ms:
                self._events[key] = event

            if self._adaptive_override.mode not in {
                AdaptiveRealtimeMode.SUSPECT,
                AdaptiveRealtimeMode.LIVE_OVERRIDE,
            }:
                self._synchronizer.ingest(event)
            self._trim(cutoff_ms)
            return self._snapshot(duplicate=False)

    def ingest_events(
        self,
        events: Iterable[TrajectoryEvent],
        *,
        event_ids: Sequence[str | None] | None = None,
    ) -> RealtimeInferenceSnapshot:
        items = list(events)
        if event_ids is not None and len(event_ids) != len(items):
            raise ValueError("event_ids must match events length")
        snapshot = None
        for index, event in enumerate(items):
            snapshot = self.ingest_event(
                event,
                event_id=event_ids[index] if event_ids is not None else None,
            )
        if snapshot is None:
            raise ValueError("at least one event is required")
        return snapshot

    def ingest_trajectory(
        self,
        trajectory: dict[str, object],
        *,
        trajectory_id: str | None = None,
    ) -> RealtimeInferenceSnapshot:
        model = build_trajectory_model(trajectory)
        geometry = build_trajectory_geometry(trajectory)
        events = extract_trajectory_events(model, geometry)
        if not events:
            raise ValueError("trajectory produced no usable events")

        prefix = trajectory_id or str(model.vehicle_id)
        event_ids = [
            (
                f"{prefix}:{event.event_type.value}:{event.timestamp_ms}:"
                f"{event.approach}:{event.movement}"
            )
            for event in events
        ]
        return self.ingest_events(events, event_ids=event_ids)

    def snapshot(self) -> RealtimeInferenceSnapshot:
        with self._lock:
            return self._snapshot(duplicate=False)

    def snapshot_at(self, timestamp_ms: int) -> RealtimeInferenceSnapshot:
        """Advance inference time without adding traffic evidence."""
        with self._lock:
            if self._current_timestamp_ms is None:
                raise ValueError("no realtime event has been ingested")
            target_ms = int(timestamp_ms)
            if target_ms < self._current_timestamp_ms:
                raise ValueError(
                    "snapshot timestamp cannot move backwards"
                )
            self._current_timestamp_ms = target_ms
            cutoff_ms = target_ms - int(
                self.recent_window_s * 1000.0
            )
            self._trim(cutoff_ms)
            return self._snapshot(duplicate=False)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._seen.clear()
            self._current_timestamp_ms = None
            self._stream_start_timestamp_ms = None
            self._synchronizer.reset()
            self._adaptive_override.reset()

    def _snapshot(self, *, duplicate: bool) -> RealtimeInferenceSnapshot:
        if self._current_timestamp_ms is None:
            raise ValueError("no realtime event has been ingested")

        synchronization = self._synchronizer.snapshot()
        elapsed_s = (
            (
                self._current_timestamp_ms
                - (
                    self._stream_start_timestamp_ms
                    or self._current_timestamp_ms
                )
            )
            / 1000.0
        )

        if (
            self._adaptive_override.mode == AdaptiveRealtimeMode.RECOVERY
            and synchronization.synchronized
        ):
            self._adaptive_override.mark_resynchronized()

        if not synchronization.synchronized:
            return self._warmup_snapshot(
                elapsed_s=elapsed_s,
                synchronization=synchronization,
                duplicate=duplicate,
            )

        cycle_position_s = self._synchronizer.cycle_position_s(
            self._current_timestamp_ms,
            synchronization,
        )
        assert cycle_position_s is not None

        template_phase = self.phase_template.phase_at(
            cycle_position_s
        )
        buffered_events = tuple(self._events.values())
        previous_mode = self._adaptive_override.mode
        adaptive = self._adaptive_override.evaluate(
            timestamp_ms=self._current_timestamp_ms,
            cycle_position_s=cycle_position_s,
            phase=template_phase,
            events=buffered_events,
            cycle_seconds=self.phase_template.cycle_seconds,
        )

        if (
            previous_mode == AdaptiveRealtimeMode.LIVE_OVERRIDE
            and adaptive.mode == AdaptiveRealtimeMode.RECOVERY
        ):
            self._synchronizer.reset()
            synchronization = self._synchronizer.snapshot()
            if synchronization.synchronized:
                self._adaptive_override.mark_resynchronized()
                adaptive = self._adaptive_override.evaluate(
                    timestamp_ms=self._current_timestamp_ms,
                    cycle_position_s=cycle_position_s,
                    phase=template_phase,
                    events=buffered_events,
                    cycle_seconds=self.phase_template.cycle_seconds,
                )
            else:
                return self._warmup_snapshot(
                    elapsed_s=elapsed_s,
                    synchronization=synchronization,
                    duplicate=duplicate,
                    adaptive=adaptive,
                )

        realtime_origin_ms = self._current_timestamp_ms - int(
            round(cycle_position_s * 1000.0)
        )
        estimator = SignalStateEstimator(
            self.phase_model,
            recent_window_s=self.recent_window_s,
            min_phase_confidence=self._min_phase_confidence,
            min_traffic_confidence=self._min_traffic_confidence,
            yellow_duration_seconds=self._yellow_duration_seconds,
            red_yellow_duration_seconds=self._red_yellow_duration_seconds,
            conflict_persistence_seconds=self._conflict_persistence_seconds,
            event_origin_ms=realtime_origin_ms,
            topology=self.topology,
        )
        base_result = estimator.estimate(
            cycle_position_s,
            buffered_events,
        )
        aware = self._anomaly_inference.estimate(
            base_result,
            buffered_events,
            current_time_s=cycle_position_s,
            recent_window_s=self.recent_window_s,
            origin_ms=realtime_origin_ms,
        )
        result = aware.signal

        phase = next(
            (
                item.to_dict()
                for item in self.phase_model.phases
                if item.phase_id == result.phase_id
            ),
            None,
        )
        template_signal_states = {
            item.approach: item.state.value
            for item in result.approaches
        }
        signal_states = dict(template_signal_states)
        active_movements = [
            stage.to_dict()
            for stage in self.phase_template.active_movements_at(
                cycle_position_s
            )
        ]

        if adaptive.mode == AdaptiveRealtimeMode.LIVE_OVERRIDE:
            signal_states = self._override_signal_states(adaptive)
            active_movements = []

        evidence_summary = {
            item.approach: {
                "state": signal_states[item.approach],
                "evidence_weight": item.evidence_weight,
                "supporting_event_count": item.supporting_event_count,
                "contradictory_event_count": item.contradictory_event_count,
                "traffic_evidence_confidence": (
                    item.traffic_evidence_confidence
                ),
                "confidence": item.confidence,
            }
            for item in result.approaches
        }

        if adaptive.mode == AdaptiveRealtimeMode.LIVE_OVERRIDE:
            confidence = round(
                max(
                    0.0,
                    min(
                        1.0,
                        synchronization.confidence
                        * adaptive.confidence,
                    ),
                ),
                4,
            )
        else:
            confidence = round(
                max(
                    0.0,
                    min(
                        1.0,
                        synchronization.confidence
                        * (
                            0.70 * result.phase_confidence
                            + 0.30
                            * result.traffic_evidence_confidence
                        ),
                    ),
                ),
                4,
            )
            if adaptive.mode == AdaptiveRealtimeMode.SUSPECT:
                confidence = round(confidence * 0.75, 4)

        return RealtimeInferenceSnapshot(
            timestamp_ms=self._current_timestamp_ms,
            timestamp_s=round(elapsed_s, 3),
            phase_id=result.phase_id,
            phase=phase,
            signal_states=signal_states,
            active_movements=active_movements,
            confidence=confidence,
            phase_confidence=result.phase_confidence,
            traffic_evidence_confidence=(
                result.traffic_evidence_confidence
            ),
            cycle_position_s=result.cycle_phase_s,
            evidence_summary=evidence_summary,
            buffer_event_count=len(self._events),
            synchronization_status=synchronization.status,
            phase_offset_s=synchronization.offset_seconds,
            synchronization_confidence=synchronization.confidence,
            synchronization_evidence_count=synchronization.evidence_count,
            anomaly=aware.indicators.to_dict(),
            adaptive_mode=adaptive.mode.value,
            effective_axis=adaptive.effective_axis,
            template_expected_axis=adaptive.expected_axis,
            template_disagreement=adaptive.template_disagreement,
            adaptive_confidence=adaptive.confidence,
            adaptive_reason=adaptive.reason,
            observed_live_approaches=adaptive.observed_approaches,
            template_signal_states=template_signal_states,
            duplicate=duplicate,
        )

    def _warmup_snapshot(
        self,
        *,
        elapsed_s: float,
        synchronization: PhaseSynchronization,
        duplicate: bool,
        adaptive: AdaptiveRealtimeDecision | None = None,
    ) -> RealtimeInferenceSnapshot:
        states = {
            approach: "UNKNOWN"
            for approach in self.topology.approaches
        }
        evidence_summary = {
            approach: {
                "state": "UNKNOWN",
                "evidence_weight": 0.0,
                "supporting_event_count": 0,
                "contradictory_event_count": 0,
                "traffic_evidence_confidence": 0.0,
                "confidence": 0.0,
            }
            for approach in states
        }
        mode = (
            adaptive.mode.value
            if adaptive is not None
            else self._adaptive_override.mode.value
        )
        return RealtimeInferenceSnapshot(
            timestamp_ms=self._current_timestamp_ms,
            timestamp_s=round(elapsed_s, 3),
            phase_id=None,
            phase=None,
            signal_states=states,
            active_movements=[],
            confidence=0.0,
            phase_confidence=0.0,
            traffic_evidence_confidence=0.0,
            cycle_position_s=None,
            evidence_summary=evidence_summary,
            buffer_event_count=len(self._events),
            synchronization_status=synchronization.status,
            phase_offset_s=None,
            synchronization_confidence=synchronization.confidence,
            synchronization_evidence_count=synchronization.evidence_count,
            anomaly=None,
            adaptive_mode=mode,
            effective_axis=(
                adaptive.effective_axis
                if adaptive is not None
                else None
            ),
            template_expected_axis=(
                adaptive.expected_axis
                if adaptive is not None
                else None
            ),
            template_disagreement=(
                adaptive.template_disagreement
                if adaptive is not None
                else False
            ),
            adaptive_confidence=(
                adaptive.confidence
                if adaptive is not None
                else 0.0
            ),
            adaptive_reason=(
                adaptive.reason
                if adaptive is not None
                else (
                    "resynchronizing_after_live_override"
                    if mode == AdaptiveRealtimeMode.RECOVERY.value
                    else None
                )
            ),
            observed_live_approaches=(
                adaptive.observed_approaches
                if adaptive is not None
                else ()
            ),
            template_signal_states=dict(states),
            duplicate=duplicate,
        )

    def _override_signal_states(
        self,
        adaptive: AdaptiveRealtimeDecision,
    ) -> dict[str, str]:
        states = {
            approach: "UNKNOWN"
            for approach in self.topology.approaches
        }
        family = adaptive.effective_axis
        if family is None:
            return states

        observed = set(adaptive.observed_approaches)
        for approach in self.topology.approaches_for_family(family):
            if approach in observed:
                states[approach] = "GREEN"

        for conflicting_family in self.topology.conflicting_families_for(
            family
        ):
            for approach in self.topology.approaches_for_family(
                conflicting_family
            ):
                states[approach] = "RED"
        return states

    def _trim(self, cutoff_ms: int) -> None:
        stale_keys = [
            key
            for key, event in self._events.items()
            if event.timestamp_ms < cutoff_ms
        ]
        for key in stale_keys:
            self._events.pop(key, None)

        stale_seen = [
            key
            for key, (_fingerprint, timestamp_ms) in self._seen.items()
            if timestamp_ms < cutoff_ms
        ]
        for key in stale_seen:
            self._seen.pop(key, None)

    @staticmethod
    def _event_fingerprint(event: TrajectoryEvent) -> str:
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


__all__ = [
    "DuplicateEventError",
    "RealtimeInferenceSnapshot",
    "RealtimeSignalInferenceEngine",
]
