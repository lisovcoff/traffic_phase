from __future__ import annotations

from dataclasses import asdict, dataclass
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

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["determination_status"] = self.determination_status.value
        data["diagnostic_reason"] = (
            self.diagnostic_reason.value
            if self.diagnostic_reason is not None
            else None
        )
        return data


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
