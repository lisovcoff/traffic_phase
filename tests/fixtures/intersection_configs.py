from __future__ import annotations

from dataclasses import dataclass

from app.core.event_phase_discovery import (
    EventPhase,
    EventPhaseDiscoveryResult,
    MovementSignalStage,
)
from app.core.intersection_config import (
    DEFAULT_INTERSECTION_CONFIG,
    IntersectionConfig,
    Movement,
    SignalHead,
)
from app.core.intersection_topology import SignalFamily
from app.core.models import EventType, TrajectoryEvent


@dataclass(frozen=True)
class IntersectionFixture:
    name: str
    config: IntersectionConfig
    phase_model: EventPhaseDiscoveryResult
    events: tuple[TrajectoryEvent, ...]
    probe_time_s: float


def _event(timestamp_s: float, approach: str, movement: str) -> TrajectoryEvent:
    return TrajectoryEvent(
        event_type=EventType.RELEASE,
        timestamp_ms=int(timestamp_s * 1000),
        approach=approach,
        movement=movement,
        confidence=1.0,
        quality="HIGH",
    )


def _phase_model(
    *,
    cycle: float,
    active_a: tuple[str, ...],
    active_b: tuple[str, ...],
    movement_stages: tuple[MovementSignalStage, ...] = (),
) -> EventPhaseDiscoveryResult:
    split = cycle / 2.0
    phases = (
        EventPhase(
            phase_id=1,
            phase_start=0.0,
            phase_end=split,
            active_approaches=active_a,
            confidence=0.95,
            supporting_event_count=60,
            contradictory_event_count=0,
            members=active_a,
        ),
        EventPhase(
            phase_id=2,
            phase_start=split,
            phase_end=cycle,
            active_approaches=active_b,
            confidence=0.95,
            supporting_event_count=60,
            contradictory_event_count=0,
            members=active_b,
        ),
    )
    return EventPhaseDiscoveryResult(
        cycle_seconds=cycle,
        bin_seconds=2.0,
        phases=phases,
        profiles=(),
        cycle_coverage=1.0,
        overlap=0.0,
        supporting_event_count=120,
        contradictory_event_count=0,
        movement_stages=movement_stages,
    )


def _repeat_events(
    movements: tuple[tuple[str, str, float], ...],
    *,
    cycle: float,
    repeats: int = 6,
) -> tuple[TrajectoryEvent, ...]:
    return tuple(
        _event(
            timestamp_s=offset + cycle * repeat,
            approach=approach,
            movement=movement,
        )
        for repeat in range(repeats)
        for approach, movement, offset in movements
    )


def ordinary_ns_ew() -> IntersectionFixture:
    config = DEFAULT_INTERSECTION_CONFIG
    phases = _phase_model(cycle=80.0, active_a=("N", "S"), active_b=("E", "W"))
    events = _repeat_events(
        (
            ("N", "N->S", 10.0),
            ("S", "S->N", 12.0),
            ("E", "E->W", 50.0),
            ("W", "W->E", 52.0),
        ),
        cycle=80.0,
    )
    return IntersectionFixture("ordinary_ns_ew", config, phases, events, 15.0)


def protected_left_turn() -> IntersectionFixture:
    config = IntersectionConfig(
        intersection_id="protected-left",
        families=(
            SignalFamily("NS", ("N", "S")),
            SignalFamily("EW", ("E", "W")),
        ),
        movements=(
            Movement("N->S", "N", "S", "through"),
            Movement("N->E", "N", "E", "left"),
            Movement("S->N", "S", "N", "through"),
            Movement("E->W", "E", "W", "through"),
            Movement("W->E", "W", "E", "through"),
        ),
        signal_heads=(
            SignalHead("N_MAIN", "N", ("N->S",)),
            SignalHead("N_LEFT", "N", ("N->E",), additional=True, arrows=("left",)),
            SignalHead("S_MAIN", "S", ("S->N",)),
            SignalHead("E_MAIN", "E", ("E->W",)),
            SignalHead("W_MAIN", "W", ("W->E",)),
        ),
        family_conflicts=(("NS", "EW"),),
        movement_conflicts=(("N->E", "S->N"),),
    )
    stages = (
        MovementSignalStage(
            movement_stage_id=1,
            approach="N",
            movement="N->E",
            phase_start=12.0,
            phase_end=24.0,
            confidence=0.95,
            repeatability=1.0,
            stability=1.0,
            supporting_event_count=24,
            observed_cycle_count=6,
        ),
    )
    phase_model = _phase_model(
        cycle=80.0,
        active_a=("N", "S"),
        active_b=("E", "W"),
        movement_stages=stages,
    )
    events = _repeat_events(
        (
            ("N", "N->S", 10.0),
            ("N", "N->E", 16.0),
            ("S", "S->N", 18.0),
            ("E", "E->W", 50.0),
            ("W", "W->E", 52.0),
        ),
        cycle=80.0,
    )
    return IntersectionFixture("protected_left_turn", config, phase_model, events, 16.0)


def separate_arrow_section() -> IntersectionFixture:
    config = IntersectionConfig(
        intersection_id="separate-arrow-section",
        families=(
            SignalFamily("NS", ("N", "S")),
            SignalFamily("EW", ("E", "W")),
        ),
        movements=(
            Movement("N->S", "N", "S", "through"),
            Movement("N->W", "N", "W", "left"),
            Movement("S->N", "S", "N", "through"),
            Movement("E->W", "E", "W", "through"),
            Movement("W->E", "W", "E", "through"),
        ),
        signal_heads=(
            SignalHead("N_MAIN", "N", ("N->S",)),
            SignalHead(
                "N_ARROW",
                "N",
                ("N->W",),
                additional=True,
                arrows=("left",),
                colors=("RED", "YELLOW", "GREEN"),
            ),
            SignalHead("S_MAIN", "S", ("S->N",)),
            SignalHead("E_MAIN", "E", ("E->W",)),
            SignalHead("W_MAIN", "W", ("W->E",)),
        ),
        family_conflicts=(("NS", "EW"),),
    )
    stages = (
        MovementSignalStage(
            movement_stage_id=1,
            approach="N",
            movement="N->W",
            phase_start=8.0,
            phase_end=18.0,
            confidence=0.92,
            repeatability=1.0,
            stability=1.0,
            supporting_event_count=18,
            observed_cycle_count=6,
        ),
    )
    phase_model = _phase_model(
        cycle=80.0,
        active_a=("N", "S"),
        active_b=("E", "W"),
        movement_stages=stages,
    )
    events = _repeat_events(
        (
            ("N", "N->S", 10.0),
            ("N", "N->W", 12.0),
            ("S", "S->N", 15.0),
            ("E", "E->W", 50.0),
            ("W", "W->E", 55.0),
        ),
        cycle=80.0,
    )
    return IntersectionFixture("separate_arrow_section", config, phase_model, events, 12.0)


def independent_ns_signal_heads() -> IntersectionFixture:
    config = IntersectionConfig(
        intersection_id="independent-ns-heads",
        families=(
            SignalFamily("NS", ("N", "S")),
            SignalFamily("EW", ("E", "W")),
        ),
        movements=(
            Movement("N->S", "N", "S"),
            Movement("S->N", "S", "N"),
            Movement("E->W", "E", "W"),
            Movement("W->E", "W", "E"),
        ),
        signal_heads=(
            SignalHead("N_MAIN", "N", ("N->S",)),
            SignalHead("S_MAIN", "S", ("S->N",)),
            SignalHead("E_MAIN", "E", ("E->W",)),
            SignalHead("W_MAIN", "W", ("W->E",)),
        ),
        family_conflicts=(("NS", "EW"),),
    )
    phase_model = _phase_model(
        cycle=80.0,
        active_a=("N", "S"),
        active_b=("E", "W"),
    )
    events = _repeat_events(
        (
            ("N", "N->S", 10.0),
            ("S", "S->N", 14.0),
            ("E", "E->W", 50.0),
            ("W", "W->E", 54.0),
        ),
        cycle=80.0,
    )
    return IntersectionFixture(
        "independent_ns_signal_heads",
        config,
        phase_model,
        events,
        15.0,
    )


def complex_overlap() -> IntersectionFixture:
    # Deliberately non-compass approach names: the topology itself defines
    # every physical relationship used by inference.
    config = IntersectionConfig(
        intersection_id="complex-overlap",
        families=(
            SignalFamily("AXIS_A", ("A1", "A2")),
            SignalFamily("AXIS_B", ("B1", "B2")),
        ),
        movements=(
            Movement("A1->A2", "A1", "A2", "through"),
            Movement("A1->B1", "A1", "B1", "left"),
            Movement("A2->A1", "A2", "A1", "through"),
            Movement("A2->B2", "A2", "B2", "left"),
            Movement("B1->B2", "B1", "B2", "through"),
            Movement("B2->B1", "B2", "B1", "through"),
        ),
        signal_heads=(
            SignalHead("A1_MAIN", "A1", ("A1->A2",)),
            SignalHead("A1_LEFT", "A1", ("A1->B1",), additional=True, arrows=("left",)),
            SignalHead("A2_MAIN", "A2", ("A2->A1",)),
            SignalHead("A2_LEFT", "A2", ("A2->B2",), additional=True, arrows=("left",)),
            SignalHead("B1_MAIN", "B1", ("B1->B2",)),
            SignalHead("B2_MAIN", "B2", ("B2->B1",)),
        ),
        family_conflicts=(("AXIS_A", "AXIS_B"),),
        movement_compatibilities=(
            ("A1->B1", "A2->B2"),
        ),
    )
    stages = (
        MovementSignalStage(
            movement_stage_id=1,
            approach="A1",
            movement="A1->B1",
            phase_start=10.0,
            phase_end=22.0,
            confidence=0.9,
            repeatability=1.0,
            stability=1.0,
            supporting_event_count=18,
            observed_cycle_count=6,
        ),
        MovementSignalStage(
            movement_stage_id=2,
            approach="A2",
            movement="A2->B2",
            phase_start=14.0,
            phase_end=26.0,
            confidence=0.9,
            repeatability=1.0,
            stability=1.0,
            supporting_event_count=18,
            observed_cycle_count=6,
        ),
    )
    phase_model = _phase_model(
        cycle=80.0,
        active_a=("A1", "A2"),
        active_b=("B1", "B2"),
        movement_stages=stages,
    )
    events = _repeat_events(
        (
            ("A1", "A1->A2", 8.0),
            ("A1", "A1->B1", 16.0),
            ("A2", "A2->A1", 9.0),
            ("A2", "A2->B2", 18.0),
            ("B1", "B1->B2", 50.0),
            ("B2", "B2->B1", 54.0),
        ),
        cycle=80.0,
    )
    return IntersectionFixture("complex_overlap", config, phase_model, events, 18.0)


FIXTURES = (
    ordinary_ns_ew,
    protected_left_turn,
    separate_arrow_section,
    independent_ns_signal_heads,
    complex_overlap,
)
