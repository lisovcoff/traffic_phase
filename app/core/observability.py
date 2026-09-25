from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, replace
from enum import Enum
from statistics import mean
from typing import Sequence

from app.core.intersection_topology import (
    DEFAULT_INTERSECTION_TOPOLOGY,
    IntersectionTopology,
)
from app.core.models import EventType, MovementEvidenceQuality, TrajectoryEvent


class DeterminationStatus(str, Enum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class DiagnosticReason(str, Enum):
    NO_EVIDENCE = "NO_EVIDENCE"
    INSUFFICIENT_EVENTS = "INSUFFICIENT_EVENTS"
    ONLY_ONE_FAMILY = "ONLY_ONE_FAMILY"
    UNOBSERVED_MOVEMENT = "UNOBSERVED_MOVEMENT"
    LOW_PHASE_CONFIDENCE = "LOW_PHASE_CONFIDENCE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    OUTSIDE_TOPOLOGY = "OUTSIDE_TOPOLOGY"
    RECOVERY = "RECOVERY"
    INCOMPATIBLE_TEMPLATE = "INCOMPATIBLE_TEMPLATE"
    SPARSE_TRAFFIC = "SPARSE_TRAFFIC"



class TrafficObservabilityLevel(str, Enum):
    HIGH = "HIGH"
    DEGRADED = "DEGRADED"
    SPARSE = "SPARSE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


DEFAULT_TRAFFIC_OBSERVABILITY_HIGH_DENSITY = 0.50
DEFAULT_TRAFFIC_OBSERVABILITY_DEGRADED_DENSITY = 0.15
DEFAULT_TRAFFIC_OBSERVABILITY_SPARSE_DENSITY = 0.10


@dataclass(frozen=True)
class TrafficObservabilitySnapshot:
    """Rolling traffic evidence density and determination coverage.

    The model is deliberately time-of-day agnostic. Sparse nighttime traffic
    is represented by sparse observed RELEASE/CROSSING evidence rather than
    by a clock-based signal-state rule.
    """

    level: TrafficObservabilityLevel
    usable_event_count: int
    window_seconds: float
    evidence_density: float
    determination_status: DeterminationStatus
    diagnostic_reason: DiagnosticReason | None
    unknown_rate: float
    determined_rate: float
    longest_unknown_interval_seconds: float
    sample_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "level": self.level.value,
            "usable_event_count": self.usable_event_count,
            "window_seconds": self.window_seconds,
            "evidence_density": self.evidence_density,
            "determination_status": self.determination_status.value,
            "diagnostic_reason": (
                self.diagnostic_reason.value
                if self.diagnostic_reason is not None
                else None
            ),
            "unknown_rate": self.unknown_rate,
            "determined_rate": self.determined_rate,
            "longest_unknown_interval_seconds": (
                self.longest_unknown_interval_seconds
            ),
            "sample_count": self.sample_count,
        }


class TrafficObservabilityModel:
    """Causal rolling model for usable traffic evidence.

    Evidence density is measured only from RELEASE/CROSSING events currently
    present in the realtime window. It adapts determination coverage without
    changing the meaning of GREEN/RED/YELLOW/RED_YELLOW states.
    """

    def __init__(
        self,
        *,
        window_seconds: float = 12.0,
        high_density: float = DEFAULT_TRAFFIC_OBSERVABILITY_HIGH_DENSITY,
        degraded_density: float = DEFAULT_TRAFFIC_OBSERVABILITY_DEGRADED_DENSITY,
        sparse_density: float = DEFAULT_TRAFFIC_OBSERVABILITY_SPARSE_DENSITY,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if not (
            0.0 <= sparse_density <= degraded_density <= high_density
        ):
            raise ValueError(
                "traffic evidence density thresholds must satisfy "
                "0 <= sparse <= degraded <= high"
            )
        self.window_seconds = float(window_seconds)
        self.high_density = float(high_density)
        self.degraded_density = float(degraded_density)
        self.sparse_density = float(sparse_density)
        self._history: deque[tuple[int, DeterminationStatus]] = deque()

    def reset(self) -> None:
        self._history.clear()

    @property
    def sample_count(self) -> int:
        return len(self._history)

    @staticmethod
    def _usable_event_count(events: Sequence[TrajectoryEvent]) -> int:
        return sum(
            event.event_type in {EventType.RELEASE, EventType.CROSSING}
            for event in events
        )

    def _level(self, usable_event_count: int) -> TrafficObservabilityLevel:
        if usable_event_count <= 0:
            return TrafficObservabilityLevel.INSUFFICIENT_DATA
        if usable_event_count == 1:
            return TrafficObservabilityLevel.SPARSE

        density = usable_event_count / self.window_seconds
        if density >= self.high_density:
            return TrafficObservabilityLevel.HIGH
        if density >= self.degraded_density:
            return TrafficObservabilityLevel.DEGRADED
        return TrafficObservabilityLevel.SPARSE

    def observe(
        self,
        *,
        timestamp_ms: int,
        events: Sequence[TrajectoryEvent],
        determination_status: DeterminationStatus,
        diagnostic_reason: DiagnosticReason | None = None,
    ) -> TrafficObservabilitySnapshot:
        timestamp_ms = int(timestamp_ms)
        if self._history and timestamp_ms < self._history[-1][0]:
            raise ValueError(
                "traffic observability timestamp cannot move backwards"
            )

        usable_event_count = self._usable_event_count(events)
        level = self._level(usable_event_count)
        effective_status = determination_status
        effective_reason = diagnostic_reason

        if level is TrafficObservabilityLevel.INSUFFICIENT_DATA and (
            determination_status is DeterminationStatus.KNOWN
        ):
            effective_status = DeterminationStatus.INSUFFICIENT_DATA
            effective_reason = DiagnosticReason.NO_EVIDENCE

        if self._history and timestamp_ms == self._history[-1][0]:
            self._history.pop()
        self._history.append((timestamp_ms, effective_status))

        cutoff_ms = timestamp_ms - int(self.window_seconds * 1000.0)
        while self._history and self._history[0][0] < cutoff_ms:
            self._history.popleft()

        determined_count = sum(
            status is DeterminationStatus.KNOWN
            for _, status in self._history
        )
        unknown_count = len(self._history) - determined_count
        sample_count = len(self._history)
        determined_rate = (
            determined_count / sample_count
            if sample_count
            else 0.0
        )
        unknown_rate = (
            unknown_count / sample_count
            if sample_count
            else 1.0
        )

        longest_unknown_ms = 0
        run_start_ms: int | None = None
        for index, (sample_timestamp_ms, status) in enumerate(self._history):
            if status is DeterminationStatus.KNOWN:
                if run_start_ms is not None:
                    longest_unknown_ms = max(
                        longest_unknown_ms,
                        sample_timestamp_ms - run_start_ms,
                    )
                    run_start_ms = None
                continue
            if run_start_ms is None:
                run_start_ms = sample_timestamp_ms
            if index == sample_count - 1:
                longest_unknown_ms = max(
                    longest_unknown_ms,
                    timestamp_ms - run_start_ms,
                )

        return TrafficObservabilitySnapshot(
            level=level,
            usable_event_count=usable_event_count,
            window_seconds=round(self.window_seconds, 4),
            evidence_density=round(
                usable_event_count / self.window_seconds,
                4,
            ),
            determination_status=effective_status,
            diagnostic_reason=effective_reason,
            unknown_rate=round(unknown_rate, 4),
            determined_rate=round(determined_rate, 4),
            longest_unknown_interval_seconds=round(
                longest_unknown_ms / 1000.0,
                4,
            ),
            sample_count=sample_count,
        )


@dataclass(frozen=True)
class ObservabilitySnapshot:
    """Evidence state; an existing template/model never implies determination."""

    determination_status: DeterminationStatus
    diagnostic_reason: DiagnosticReason | None
    cycle_confidence: float
    synchronization_confidence: float
    phase_confidence: float
    movement_confidence: float
    traffic_evidence_confidence: float
    observability_confidence: float
    traffic_observability: TrafficObservabilitySnapshot | None = None

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["determination_status"] = self.determination_status.value
        data["diagnostic_reason"] = (
            self.diagnostic_reason.value
            if self.diagnostic_reason is not None
            else None
        )
        data["traffic_observability"] = (
            self.traffic_observability.to_dict()
            if self.traffic_observability is not None
            else None
        )
        return data

    def with_traffic_observability(
        self,
        traffic_observability: TrafficObservabilitySnapshot,
    ) -> "ObservabilitySnapshot":
        return replace(
            self,
            determination_status=traffic_observability.determination_status,
            diagnostic_reason=traffic_observability.diagnostic_reason,
            traffic_observability=traffic_observability,
        )


def _clip(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 4)


def _usable_events(events: Sequence[TrajectoryEvent]) -> list[TrajectoryEvent]:
    return [
        event
        for event in events
        if event.event_type in {EventType.RELEASE, EventType.CROSSING}
    ]


def _movement_confidence(events: Sequence[TrajectoryEvent]) -> float:
    usable = _usable_events(events)
    if not usable:
        return 0.0
    known = [
        event
        for event in usable
        if event.movement
        and "->" in event.movement
        and not event.movement.endswith("->UNKNOWN")
    ]
    if not known:
        return 0.0
    valid = [
        event
        for event in known
        if event.movement_quality == MovementEvidenceQuality.VALID
    ]
    if not valid:
        # Legacy/API events carry explicit movement but may not carry the
        # trajectory-derived quality field.
        return _clip(0.5 * len(known) / len(usable))
    return _clip((len(valid) / len(known)) * (len(known) / len(usable)))


def _traffic_confidence(events: Sequence[TrajectoryEvent]) -> float:
    usable = _usable_events(events)
    return _clip(mean(event.confidence for event in usable)) if usable else 0.0


def _families(
    events: Sequence[TrajectoryEvent],
    topology: IntersectionTopology,
) -> set[str]:
    return {
        family
        for event in _usable_events(events)
        for family in [topology.family_for_approach(event.approach)]
        if family is not None
    }


def _outside_topology(
    events: Sequence[TrajectoryEvent],
    topology: IntersectionTopology,
) -> bool:
    return any(
        event.approach not in topology.approaches
        for event in _usable_events(events)
    )


def _conflicting_evidence(phase_model: object | None) -> bool:
    if phase_model is None:
        return False
    for phase in getattr(phase_model, "phases", ()):
        supporting = int(getattr(phase, "supporting_event_count", 0))
        contradictory = int(getattr(phase, "contradictory_event_count", 0))
        total = supporting + contradictory
        if total and contradictory / total > 0.5:
            return True
    return False


def build_batch_observability(
    events: Sequence[TrajectoryEvent],
    *,
    cycle_confidence: float,
    phase_confidence: float,
    phase_coverage: float,
    phase_model: object | None = None,
    topology: IntersectionTopology = DEFAULT_INTERSECTION_TOPOLOGY,
    synchronization_confidence: float | None = None,
    movement_confidence: float | None = None,
    diagnostic_reason: DiagnosticReason | None = None,
    min_events: int = 8,
) -> ObservabilitySnapshot:
    usable = _usable_events(events)
    traffic = _traffic_confidence(events)
    movement = (
        _movement_confidence(events)
        if movement_confidence is None
        else _clip(movement_confidence)
    )
    cycle = _clip(cycle_confidence)
    phase = _clip(phase_confidence)
    synchronization = _clip(
        phase_coverage
        if synchronization_confidence is None
        else synchronization_confidence
    )
    # Structural observability answers "can the signal be determined?".
    # Traffic and movement evidence remain separate dimensions and do not
    # turn an otherwise synchronized signal into RED merely because no cars
    # are currently visible.
    observability = _clip(min(cycle, synchronization, phase))

    if _outside_topology(events, topology):
        status = DeterminationStatus.UNKNOWN
        reason = DiagnosticReason.OUTSIDE_TOPOLOGY
    elif not usable:
        status = DeterminationStatus.INSUFFICIENT_DATA
        reason = DiagnosticReason.NO_EVIDENCE
    elif len(usable) < min_events:
        status = DeterminationStatus.INSUFFICIENT_DATA
        reason = DiagnosticReason.INSUFFICIENT_EVENTS
    elif len(_families(usable, topology)) < 2:
        status = DeterminationStatus.INSUFFICIENT_DATA
        reason = DiagnosticReason.ONLY_ONE_FAMILY
    elif diagnostic_reason is not None:
        status = DeterminationStatus.UNKNOWN
        reason = diagnostic_reason
    elif _conflicting_evidence(phase_model):
        status = DeterminationStatus.UNKNOWN
        reason = DiagnosticReason.CONFLICTING_EVIDENCE
    elif phase < 0.20:
        status = DeterminationStatus.UNKNOWN
        reason = DiagnosticReason.LOW_PHASE_CONFIDENCE
    elif movement < 0.20:
        status = DeterminationStatus.UNKNOWN
        reason = DiagnosticReason.UNOBSERVED_MOVEMENT
    elif observability >= 0.20:
        status = DeterminationStatus.KNOWN
        reason = None
    else:
        status = DeterminationStatus.UNKNOWN
        reason = DiagnosticReason.LOW_PHASE_CONFIDENCE

    return ObservabilitySnapshot(
        determination_status=status,
        diagnostic_reason=reason,
        cycle_confidence=cycle,
        synchronization_confidence=synchronization,
        phase_confidence=phase,
        movement_confidence=movement,
        traffic_evidence_confidence=traffic,
        observability_confidence=observability,
    )


def build_realtime_observability(
    events: Sequence[TrajectoryEvent],
    *,
    cycle_confidence: float,
    synchronization_confidence: float,
    phase_confidence: float,
    movement_confidence: float | None = None,
    traffic_evidence_confidence: float | None = None,
    synchronization_ready: bool,
    observed_family_count: int,
    template_compatibility: str,
    recovery: bool = False,
    conflicting_evidence: bool = False,
    topology: IntersectionTopology = DEFAULT_INTERSECTION_TOPOLOGY,
    min_events: int = 6,
) -> ObservabilitySnapshot:
    usable = _usable_events(events)
    cycle = _clip(cycle_confidence)
    synchronization = _clip(synchronization_confidence)
    phase = _clip(phase_confidence)
    movement = (
        _movement_confidence(events)
        if movement_confidence is None
        else _clip(movement_confidence)
    )
    traffic = (
        _traffic_confidence(events)
        if traffic_evidence_confidence is None
        else _clip(traffic_evidence_confidence)
    )
    # Structural observability is independent from live traffic volume.
    observability = _clip(min(cycle, synchronization, phase))

    if _outside_topology(events, topology):
        status = DeterminationStatus.UNKNOWN
        reason = DiagnosticReason.OUTSIDE_TOPOLOGY
    elif not usable:
        status = DeterminationStatus.INSUFFICIENT_DATA
        reason = DiagnosticReason.NO_EVIDENCE
    elif recovery:
        status = DeterminationStatus.UNKNOWN
        reason = DiagnosticReason.RECOVERY
    elif template_compatibility == "INCOMPATIBLE":
        status = DeterminationStatus.UNKNOWN
        reason = DiagnosticReason.INCOMPATIBLE_TEMPLATE
    elif conflicting_evidence:
        status = DeterminationStatus.UNKNOWN
        reason = DiagnosticReason.CONFLICTING_EVIDENCE
    elif not synchronization_ready:
        status = DeterminationStatus.INSUFFICIENT_DATA
        reason = (
            DiagnosticReason.ONLY_ONE_FAMILY
            if observed_family_count < 2
            else DiagnosticReason.INSUFFICIENT_EVENTS
            if len(usable) < min_events
            else DiagnosticReason.NO_EVIDENCE
        )
    elif phase < 0.20:
        status = DeterminationStatus.UNKNOWN
        reason = DiagnosticReason.LOW_PHASE_CONFIDENCE
    elif movement < 0.20:
        status = DeterminationStatus.UNKNOWN
        reason = DiagnosticReason.UNOBSERVED_MOVEMENT
    elif observability >= 0.20:
        status = DeterminationStatus.KNOWN
        reason = None
    else:
        status = DeterminationStatus.UNKNOWN
        reason = DiagnosticReason.CONFLICTING_EVIDENCE

    return ObservabilitySnapshot(
        determination_status=status,
        diagnostic_reason=reason,
        cycle_confidence=cycle,
        synchronization_confidence=synchronization,
        phase_confidence=phase,
        movement_confidence=movement,
        traffic_evidence_confidence=traffic,
        observability_confidence=observability,
    )
