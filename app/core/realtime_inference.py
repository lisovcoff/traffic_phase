from __future__ import annotations

from collections import OrderedDict
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
from app.core.models import EventType, TrajectoryEvent
from app.core.observability import (
    DiagnosticReason,
    DeterminationStatus,
    ObservabilitySnapshot,
    build_realtime_observability,
)
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
from app.core.trajectory_events import (
    UNKNOWN_DESTINATION,
    CausalTrajectoryEventExtractor,
    resolve_movement,
)
from app.core.trajectory_geometry import build_trajectory_geometry


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
    synchronization_match_ratio: float = 0.0
    template_compatibility: str = "CHECKING"
    instant_unknown_rate: float = 1.0
    unknown_reasons: dict[str, str] | None = None
    template_deviation_seconds: float | None = None
    anomaly: dict[str, object] | None = None
    adaptive_mode: str = "NORMAL"
    effective_axis: str | None = None
    template_expected_axis: str | None = None
    template_disagreement: bool = False
    adaptive_confidence: float = 0.0
    adaptive_reason: str | None = None
    phase_extension_duration_seconds: float = 0.0
    phase_extension_event_count: int = 0
    phase_extension_peak_duration_seconds: float = 0.0
    observed_live_approaches: tuple[str, ...] = ()
    effective_movement_states: dict[str, dict[str, object]] | None = None
    template_signal_states: dict[str, str] | None = None
    duplicate: bool = False
    determination_status: DeterminationStatus = DeterminationStatus.INSUFFICIENT_DATA
    diagnostic_reason: DiagnosticReason | None = None
    observability: ObservabilitySnapshot | None = None

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
        min_extension_weight: float = 2.0,
        min_extension_releases: int = 2,
        extension_max_seconds: float | None = None,
        max_active_trajectories: int = 1024,
        max_idempotency_entries: int = 8192,
    ) -> None:
        if recent_window_s <= 0:
            raise ValueError("recent_window_s must be positive")
        if max_active_trajectories < 1:
            raise ValueError("max_active_trajectories must be positive")
        if max_idempotency_entries < 1:
            raise ValueError("max_idempotency_entries must be positive")

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
            min_extension_weight=min_extension_weight,
            min_extension_releases=min_extension_releases,
            extension_max_seconds=extension_max_seconds,
            topology=self.topology,
        )
        self._synchronizer = RealtimePhaseSynchronizer(
            self.phase_template,
            min_evidence_events=synchronization_min_events,
            fixed_origin_ms=self.event_origin_ms,
        )
        self._events: dict[str, TrajectoryEvent] = {}
        self._seen: OrderedDict[str, tuple[str, int]] = OrderedDict()
        self._trajectory_extractors: OrderedDict[
            str,
            CausalTrajectoryEventExtractor,
        ] = OrderedDict()
        self._max_active_trajectories = int(max_active_trajectories)
        self._max_idempotency_entries = int(max_idempotency_entries)
        self._current_timestamp_ms: int | None = None
        self._stream_start_timestamp_ms: int | None = None
        self._ever_synchronized = False
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
    def active_trajectory_count(self) -> int:
        return len(self._trajectory_extractors)

    @property
    def idempotency_entry_count(self) -> int:
        return len(self._seen)

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
        if event.approach not in self.topology.approaches:
            raise ValueError(
                "event approach is not present in the configured "
                f"intersection topology: {event.approach}"
            )
        with self._lock:
            key = event_id or self._event_fingerprint(event)
            fingerprint = self._event_fingerprint(event)

            previous = self._seen.get(key)
            if previous is not None:
                if previous[0] != fingerprint:
                    raise DuplicateEventError(
                        f"idempotency key {key!r} was already used for another event"
                    )
                self._seen.move_to_end(key)
                return self._snapshot(duplicate=True)

            self._advance_clock(event.timestamp_ms)
            self._remember_idempotency(
                key,
                fingerprint,
                event.timestamp_ms,
            )

            cutoff_ms = self._current_timestamp_ms - int(
                self.recent_window_s * 1000.0
            )
            if event.timestamp_ms < cutoff_ms:
                self._trim(cutoff_ms)
                return self._snapshot(duplicate=False)

            self._events[key] = event
            if self._adaptive_override.mode not in {
                AdaptiveRealtimeMode.SUSPECT,
                AdaptiveRealtimeMode.LIVE_OVERRIDE,
            }:
                self._synchronizer.ingest(event)
            self._trim(cutoff_ms)
            return self._snapshot(duplicate=False)

    def _advance_clock(self, timestamp_ms: int) -> None:
        value = int(timestamp_ms)
        if self._current_timestamp_ms is None:
            self._current_timestamp_ms = value
            self._stream_start_timestamp_ms = value
            return
        self._current_timestamp_ms = max(
            self._current_timestamp_ms,
            value,
        )

    def _remember_idempotency(
        self,
        key: str,
        fingerprint: str,
        timestamp_ms: int,
    ) -> None:
        self._seen[key] = (fingerprint, int(timestamp_ms))
        self._seen.move_to_end(key)
        while len(self._seen) > self._max_idempotency_entries:
            self._seen.popitem(last=False)

    def _validate_trajectory(
        self,
        trajectory: dict[str, object],
        trajectory_id: str | None,
    ) -> tuple[str, str, str, str]:
        approach = str(trajectory.get("zone_in", "")).strip()
        if approach not in self.topology.approaches:
            raise ValueError(
                "trajectory approach is not present in the configured "
                f"intersection topology: {approach}"
            )

        zone_out_raw = trajectory.get("zone_out")
        zone_out = (
            str(zone_out_raw).strip()
            if zone_out_raw
            else UNKNOWN_DESTINATION
        )
        movement, _quality, _reason = resolve_movement(
            approach,
            zone_out,
            trajectory.get("movement"),
        )
        trajectory_key = (
            str(trajectory_id).strip()
            if trajectory_id is not None
            else str(trajectory.get("id", "")).strip()
        )
        if not trajectory_key:
            raise ValueError(
                "trajectory id is required for causal realtime ingestion"
            )
        return trajectory_key, approach, zone_out, movement

    def _evict_trajectory_capacity(self) -> None:
        while len(self._trajectory_extractors) >= self._max_active_trajectories:
            self._trajectory_extractors.popitem(last=False)

    def ingest_trajectory(
        self,
        trajectory: dict[str, object],
        *,
        trajectory_id: str | None = None,
    ) -> RealtimeInferenceSnapshot:
        geometry = build_trajectory_geometry(trajectory)
        if not geometry.detections:
            raise ValueError("trajectory requires at least one valid detection")

        key, approach, zone_out, movement = self._validate_trajectory(
            trajectory,
            trajectory_id,
        )

        with self._lock:
            extractor = self._trajectory_extractors.get(key)
            if extractor is None:
                self._evict_trajectory_capacity()
                extractor = CausalTrajectoryEventExtractor(
                    approach=approach,
                    movement=movement,
                    zone_out=zone_out,
                )
                self._trajectory_extractors[key] = extractor
            else:
                if (
                    extractor.approach != approach
                    or extractor.movement != movement
                    or extractor.zone_out != zone_out
                ):
                    raise DuplicateEventError(
                        f"trajectory id {key!r} was already used for another trajectory"
                    )
                self._trajectory_extractors.move_to_end(key)

            before = extractor.observed_detection_count
            events = extractor.ingest_snapshot(geometry.detections)
            after = extractor.observed_detection_count

            latest_detection_ms = max(
                detection.millis
                for detection in geometry.detections
            )
            self._advance_clock(latest_detection_ms)
            cutoff_ms = self._current_timestamp_ms - int(
                self.recent_window_s * 1000.0
            )
            self._trim(cutoff_ms)

            if events:
                event_ids = [
                    f"{key}:{event.event_type.value}"
                    for event in events
                ]
                return self.ingest_events(
                    events,
                    event_ids=event_ids,
                )

            return self._snapshot(
                duplicate=(before == after),
            )

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
            self._trajectory_extractors.clear()
            self._current_timestamp_ms = None
            self._stream_start_timestamp_ms = None
            self._synchronizer.reset()
            self._adaptive_override.reset()
            self._ever_synchronized = False

    def _snapshot(self, *, duplicate: bool) -> RealtimeInferenceSnapshot:
        if self._current_timestamp_ms is None:
            raise ValueError("no realtime event has been ingested")

        synchronization = self._synchronizer.snapshot()
        if synchronization.synchronized:
            self._ever_synchronized = True
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
            phases=self.phase_model.phases,
            expected_movements=tuple(
                stage.movement
                for stage in self.phase_template.active_movements_at(
                    cycle_position_s
                )
            ),
        )

        if (
            previous_mode
            in {
                AdaptiveRealtimeMode.PHASE_EXTENSION,
                AdaptiveRealtimeMode.LIVE_OVERRIDE,
            }
            and adaptive.mode == AdaptiveRealtimeMode.RECOVERY
        ):
            self._synchronizer.enter_recovery()
            synchronization = self._synchronizer.snapshot()
            if synchronization.synchronized:
                self._adaptive_override.mark_resynchronized()
                adaptive = self._adaptive_override.evaluate(
                    timestamp_ms=self._current_timestamp_ms,
                    cycle_position_s=cycle_position_s,
                    phase=template_phase,
                    events=buffered_events,
                    cycle_seconds=self.phase_template.cycle_seconds,
                    phases=self.phase_model.phases,
                    expected_movements=tuple(
                        stage.movement
                        for stage in self.phase_template.active_movements_at(
                            cycle_position_s
                        )
                    ),
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
        effective_movement_states = self._effective_movement_states(
            adaptive=adaptive,
            cycle_position_s=cycle_position_s,
            events=buffered_events,
        )

        if adaptive.mode in {
            AdaptiveRealtimeMode.PHASE_EXTENSION,
            AdaptiveRealtimeMode.LIVE_OVERRIDE,
        }:
            signal_states = self._override_signal_states(
                adaptive,
                effective_movement_states,
            )
            active_movements = (
                self._extension_active_movements(adaptive, cycle_position_s)
                if adaptive.mode == AdaptiveRealtimeMode.PHASE_EXTENSION
                else []
            )

        compatibility = self._template_compatibility(synchronization)
        realtime_observability = build_realtime_observability(
            buffered_events,
            cycle_confidence=(
                1.0
                if synchronization.synchronized
                else synchronization.confidence
            ),
            synchronization_confidence=(
                1.0
                if synchronization.synchronized
                else synchronization.confidence
            ),
            phase_confidence=(
                float(template_phase.confidence)
                if template_phase is not None
                else result.phase_confidence
            ),
            traffic_evidence_confidence=result.traffic_evidence_confidence,
            synchronization_ready=True,
            observed_family_count=synchronization.observed_group_count,
            template_compatibility=compatibility,
            recovery=adaptive.mode == AdaptiveRealtimeMode.RECOVERY,
            conflicting_evidence=(
                adaptive.mode == AdaptiveRealtimeMode.SUSPECT
            ),
            topology=self.topology,
        )
        if realtime_observability.determination_status != DeterminationStatus.KNOWN:
            # A model/template never supplies RED by itself.
            signal_states = {
                approach: "UNKNOWN"
                for approach in signal_states
            }
            active_movements = []
            effective_movement_states = {
                movement: {
                    **details,
                    "effective_state": "UNKNOWN",
                    "confidence": 0.0,
                    "reason": "insufficient_observability",
                }
                for movement, details in effective_movement_states.items()
            }
        unknown_reason = (
            "live_override_partial"
            if adaptive.mode == AdaptiveRealtimeMode.LIVE_OVERRIDE
            else "low_confidence_or_uncovered_phase"
        )
        unknown_reasons = {
            approach: unknown_reason
            for approach, state in signal_states.items()
            if state == "UNKNOWN"
        }
        template_deviation_seconds = None
        if (
            adaptive.mode
            in {
                AdaptiveRealtimeMode.PHASE_EXTENSION,
                AdaptiveRealtimeMode.LIVE_OVERRIDE,
            }
            and template_phase is not None
        ):
            template_start = (
                float(template_phase.phase_start)
                % self.phase_template.cycle_seconds
            )
            template_deviation_seconds = round(
                (
                    cycle_position_s - template_start
                )
                % self.phase_template.cycle_seconds,
                3,
            )

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

        if adaptive.mode in {
            AdaptiveRealtimeMode.PHASE_EXTENSION,
            AdaptiveRealtimeMode.LIVE_OVERRIDE,
        }:
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

        warm_observability = build_realtime_observability(
            tuple(self._events.values()),
            cycle_confidence=0.0,
            synchronization_confidence=synchronization.confidence,
            phase_confidence=0.0,
            synchronization_ready=False,
            observed_family_count=synchronization.observed_group_count,
            template_compatibility=compatibility,
            recovery=(
                adaptive is not None
                and adaptive.mode == AdaptiveRealtimeMode.RECOVERY
            ),
            topology=self.topology,
        )
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
            synchronization_match_ratio=synchronization.match_ratio,
            template_compatibility=compatibility,
            instant_unknown_rate=self._unknown_rate(signal_states),
            unknown_reasons=unknown_reasons,
            template_deviation_seconds=template_deviation_seconds,
            anomaly=aware.indicators.to_dict(),
            adaptive_mode=adaptive.mode.value,
            effective_axis=adaptive.effective_axis,
            template_expected_axis=adaptive.expected_axis,
            template_disagreement=adaptive.template_disagreement,
            adaptive_confidence=adaptive.confidence,
            adaptive_reason=adaptive.reason,
            phase_extension_duration_seconds=(
                adaptive.extension_duration_seconds
            ),
            phase_extension_event_count=adaptive.extension_event_count,
            phase_extension_peak_duration_seconds=(
                adaptive.extension_peak_duration_seconds
            ),
            observed_live_approaches=adaptive.observed_approaches,
            effective_movement_states=effective_movement_states,
            template_signal_states=template_signal_states,
            duplicate=duplicate,
            determination_status=realtime_observability.determination_status,
            diagnostic_reason=realtime_observability.diagnostic_reason,
            observability=realtime_observability,
        )

    def _template_compatibility(
        self,
        synchronization: PhaseSynchronization,
    ) -> str:
        if self._ever_synchronized or synchronization.synchronized:
            return "COMPATIBLE"
        if (
            synchronization.evidence_count < 12
            or synchronization.observed_group_count < 2
        ):
            return "CHECKING"
        if synchronization.match_ratio < 0.55:
            return "INCOMPATIBLE"
        return "SUSPECT"

    @staticmethod
    def _unknown_rate(states: dict[str, str]) -> float:
        if not states:
            return 1.0
        return round(
            sum(value == "UNKNOWN" for value in states.values())
            / len(states),
            4,
        )

    def _warmup_reason(
        self,
        synchronization: PhaseSynchronization,
        compatibility: str,
        adaptive: AdaptiveRealtimeDecision | None = None,
    ) -> str:
        if compatibility == "INCOMPATIBLE":
            return "template_incompatible"
        mode = (
            adaptive.mode
            if adaptive is not None
            else self._adaptive_override.mode
        )
        if mode == AdaptiveRealtimeMode.RECOVERY:
            return "recovery_resynchronization"
        if synchronization.evidence_count <= 0:
            return "no_release_or_crossing_evidence"
        if synchronization.observed_group_count < 2:
            return "only_one_family"
        return "insufficient_match_ratio_or_evidence"

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
        compatibility = self._template_compatibility(synchronization)
        reason = self._warmup_reason(
            synchronization,
            compatibility,
            adaptive,
        )
        unknown_reasons = {
            approach: reason
            for approach in states
        }
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
            synchronization_match_ratio=synchronization.match_ratio,
            template_compatibility=compatibility,
            instant_unknown_rate=1.0,
            unknown_reasons=unknown_reasons,
            template_deviation_seconds=None,
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
                    (
                        "resynchronizing_after_phase_extension"
                        if self._adaptive_override._extension_axis is not None
                        else "resynchronizing_after_live_override"
                    )
                    if mode == AdaptiveRealtimeMode.RECOVERY.value
                    else None
                )
            ),
            phase_extension_duration_seconds=(
                adaptive.extension_duration_seconds
                if adaptive is not None
                else 0.0
            ),
            phase_extension_event_count=(
                adaptive.extension_event_count
                if adaptive is not None
                else 0
            ),
            phase_extension_peak_duration_seconds=(
                adaptive.extension_peak_duration_seconds
                if adaptive is not None
                else 0.0
            ),
            observed_live_approaches=(
                adaptive.observed_approaches
                if adaptive is not None
                else ()
            ),
            effective_movement_states={},
            template_signal_states=dict(states),
            duplicate=duplicate,
        )

    def _extension_active_movements(
        self,
        adaptive: AdaptiveRealtimeDecision,
        cycle_position_s: float,
    ) -> list[dict[str, object]]:
        family = adaptive.effective_axis
        if family is None:
            return []

        stages = [
            stage
            for stage in self.phase_template.movement_stages
            if self.topology.family_for_approach(stage.approach) == family
        ]
        if not stages:
            return []

        cycle = self.phase_template.cycle_seconds
        ranked = [
            (
                (cycle_position_s - float(stage.phase_end)) % cycle,
                stage,
            )
            for stage in stages
        ]
        nearest = min(distance for distance, _stage in ranked)
        return [
            stage.to_dict()
            for distance, stage in ranked
            if abs(distance - nearest) < 1e-9
        ]

    def _override_signal_states(
        self,
        adaptive: AdaptiveRealtimeDecision,
        movement_states: dict[str, dict[str, object]] | None = None,
    ) -> dict[str, str]:
        states = {
            approach: "UNKNOWN"
            for approach in self.topology.approaches
        }
        if (
            movement_states
            and adaptive.override_movements
            and self._movement_granularity_enabled()
        ):
            for approach in self.topology.approaches:
                owned = [
                    details
                    for movement, details in movement_states.items()
                    if self.topology.movement_approach(movement) == approach
                ]
                if not owned:
                    continue
                if all(
                    details["effective_state"] == "GREEN"
                    for details in owned
                ):
                    states[approach] = "GREEN"
                else:
                    states[approach] = "UNKNOWN"
            return states

        family = adaptive.effective_axis
        if family is None:
            return states

        observed = set(adaptive.observed_approaches)
        for approach in self.topology.approaches_for_family(family):
            if approach in observed:
                states[approach] = "GREEN"

        if adaptive.mode == AdaptiveRealtimeMode.PHASE_EXTENSION:
            return states

        for conflicting_family in self.topology.conflicting_families_for(
            family
        ):
            for approach in self.topology.approaches_for_family(
                conflicting_family
            ):
                states[approach] = "RED"
        return states


    def _effective_movement_states(
        self,
        *,
        adaptive: AdaptiveRealtimeDecision,
        cycle_position_s: float,
        events: Sequence[TrajectoryEvent],
    ) -> dict[str, dict[str, object]]:
        stages_by_movement: dict[str, list[object]] = {}
        for stage in self.phase_template.movement_stages:
            stages_by_movement.setdefault(
                stage.movement,
                [],
            ).append(stage)

        evidence: dict[str, dict[str, object]] = {}
        now_ms = self._current_timestamp_ms
        if now_ms is not None:
            lower_ms = now_ms - int(
                self.recent_window_s * 1000.0
            )
            for item in events:
                if not lower_ms <= item.timestamp_ms <= now_ms:
                    continue
                if item.event_type not in {
                    EventType.RELEASE,
                    EventType.CROSSING,
                }:
                    continue
                movement = str(item.movement or "").strip()
                if not movement or movement.endswith("->UNKNOWN"):
                    continue
                weight = (
                    1.0
                    if item.event_type == EventType.RELEASE
                    else 0.5
                ) * max(0.0, min(1.0, float(item.confidence)))
                row = evidence.setdefault(
                    movement,
                    {
                        "evidence_weight": 0.0,
                        "supporting_event_count": 0,
                    },
                )
                row["evidence_weight"] = (
                    float(row["evidence_weight"]) + weight
                )
                row["supporting_event_count"] = (
                    int(row["supporting_event_count"]) + 1
                )

        movement_ids = set(stages_by_movement) | set(evidence)
        movement_ids.update(adaptive.override_movements)
        if not movement_ids:
            return {}

        result: dict[str, dict[str, object]] = {}
        for movement in sorted(movement_ids):
            stages = stages_by_movement.get(movement, [])
            active_stage = next(
                (
                    stage
                    for stage in stages
                    if self._in_cycle_interval(
                        cycle_position_s,
                        float(stage.phase_start),
                        float(stage.phase_end),
                    )
                ),
                None,
            )
            stage_confidence = (
                float(getattr(active_stage, "confidence", 0.0))
                if active_stage is not None
                else max(
                    (
                        float(getattr(stage, "confidence", 0.0))
                        for stage in stages
                    ),
                    default=0.0,
                )
            )
            evidence_row = evidence.get(
                movement,
                {
                    "evidence_weight": 0.0,
                    "supporting_event_count": 0,
                },
            )
            expected_state = (
                "GREEN"
                if active_stage is not None
                else ("RED" if stages else "UNKNOWN")
            )
            result[movement] = {
                "movement": movement,
                "expected_state": expected_state,
                "effective_state": expected_state,
                "evidence_weight": round(
                    float(evidence_row["evidence_weight"]),
                    4,
                ),
                "supporting_event_count": int(
                    evidence_row["supporting_event_count"]
                ),
                "confidence": round(
                    max(0.0, min(1.0, stage_confidence)),
                    4,
                ),
                "reason": (
                    "template_expected_active"
                    if active_stage is not None
                    else (
                        "template_expected_inactive"
                        if stages
                        else "no_template_movement_stage"
                    )
                ),
            }

        if adaptive.mode in {
            AdaptiveRealtimeMode.LIVE_OVERRIDE,
            AdaptiveRealtimeMode.PHASE_EXTENSION,
        } and adaptive.override_movements:
            selected = set(adaptive.override_movements)
            for movement, details in result.items():
                if movement in selected:
                    details["effective_state"] = "GREEN"
                    details["confidence"] = round(
                        max(
                            float(details["confidence"]),
                            min(
                                1.0,
                                0.45
                                + 0.10 * min(
                                    6,
                                    int(details["supporting_event_count"]),
                                )
                                + 0.06 * float(details["evidence_weight"]),
                            ),
                        ),
                        4,
                    )
                    details["reason"] = "live_override_movement"
                    continue

                if any(
                    self.topology.movements_conflict(
                        movement,
                        primary,
                    )
                    for primary in selected
                ):
                    details["effective_state"] = "RED"
                    details["confidence"] = max(
                        0.75,
                        float(details["confidence"]),
                    )
                    details["reason"] = "conflicts_with_live_override"
                    continue

                if details["expected_state"] == "GREEN":
                    details["effective_state"] = "GREEN"
                    details["reason"] = "compatible_live_overlap"
                elif (
                    details["expected_state"] == "RED"
                    and float(details["evidence_weight"]) > 0.0
                ):
                    details["effective_state"] = "RED"
                    details["reason"] = "positive_conflicting_evidence"
                else:
                    details["effective_state"] = "UNKNOWN"
                    details["confidence"] = min(
                        float(details["confidence"]),
                        0.5,
                    )
                    details["reason"] = "no_positive_live_evidence"

            self._enforce_movement_exclusivity(result)

        return result

    def _in_cycle_interval(
        self,
        position_s: float,
        start_s: float,
        end_s: float,
    ) -> bool:
        cycle = self.phase_template.cycle_seconds
        position = position_s % cycle
        start = start_s % cycle
        end = end_s % cycle
        return (
            start <= position < end
            if start <= end
            else position >= start or position < end
        )

    def _enforce_movement_exclusivity(
        self,
        states: dict[str, dict[str, object]],
    ) -> None:
        green = [
            movement
            for movement, details in states.items()
            if details["effective_state"] == "GREEN"
        ]
        accepted: list[str] = []
        for movement in sorted(
            green,
            key=lambda item: (
                -float(states[item]["evidence_weight"]),
                -float(states[item]["confidence"]),
                item,
            ),
        ):
            if any(
                self.topology.movements_conflict(
                    movement,
                    other,
                )
                for other in accepted
            ):
                states[movement]["effective_state"] = "RED"
                states[movement]["confidence"] = min(
                    float(states[movement]["confidence"]),
                    0.5,
                )
                states[movement]["reason"] = "suppressed_conflicting_green"
            else:
                accepted.append(movement)

    def _movement_granularity_enabled(self) -> bool:
        return bool(
            self.phase_template.movement_stages
            or self.topology.movement_conflicts
            or self.topology.movement_compatibilities
        )

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

        stale_trajectories = [
            key
            for key, extractor in self._trajectory_extractors.items()
            if (
                extractor.latest_detection_ms is not None
                and extractor.latest_detection_ms < cutoff_ms
            )
        ]
        for key in stale_trajectories:
            self._trajectory_extractors.pop(key, None)

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
