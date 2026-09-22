from __future__ import annotations

from types import SimpleNamespace

from app.core.archive_analysis import _gap_semantics
from app.core.event_phase_discovery import (
    EventPhase,
    EventPhaseDiscoveryResult,
    MovementActivationCandidate,
)
from app.core.models import EventType, TrajectoryEvent
from app.core.reconstruction import SessionReconstruction
from app.core.regime_aggregation import (
    _aligned_pooled_events,
    build_regime_families,
)


def _phase(
    phase_id: int,
    start: float,
    end: float,
    active: tuple[str, ...],
    confidence: float = 0.9,
) -> EventPhase:
    return EventPhase(
        phase_id=phase_id,
        phase_start=start,
        phase_end=end,
        active_approaches=active,
        confidence=confidence,
        supporting_event_count=100,
        contradictory_event_count=5,
        members=active,
    )


def _session(
    phases: tuple[EventPhase, ...],
    *,
    cycle_seconds: float = 100.0,
    cycle_confidence: float = 0.9,
    quality: str = "GOOD",
    physical_session_index: int = 1,
    regime_index: int = 1,
    event_count: int = 5000,
    movement_candidates=(),
) -> SessionReconstruction:
    coverage = sum(
        (
            (phase.phase_end - phase.phase_start)
            % cycle_seconds
        )
        or cycle_seconds
        for phase in phases
    ) / cycle_seconds
    model = EventPhaseDiscoveryResult(
        cycle_seconds=cycle_seconds,
        bin_seconds=2.0,
        phases=phases,
        profiles=(),
        cycle_coverage=round(min(1.0, coverage), 4),
        overlap=0.0,
        supporting_event_count=1000,
        contradictory_event_count=50,
        origin_timestamp_ms=0,
        distinct_movement_candidates=tuple(
            movement_candidates
        ),
    )
    return SessionReconstruction(
        start_timestamp_ms=0,
        end_timestamp_ms=3_600_000,
        duration_s=3600.0,
        trajectory_count=1000,
        event_count=event_count,
        cycle=SimpleNamespace(
            estimate=SimpleNamespace(
                confidence=cycle_confidence
            )
        ),
        phase_model=model,
        status="ok",
        confidence=min(
            cycle_confidence,
            min(phase.confidence for phase in phases),
        ),
        session_index=physical_session_index,
        regime_index=regime_index,
        regime_count=1,
        model_quality=quality,
    )


def _raw_events(
    *,
    origin_ms: int = 0,
    cycles: int = 12,
    cycle_seconds: float = 100.0,
    shift_s: float = 0.0,
    movement_probe: bool = False,
) -> tuple[TrajectoryEvent, ...]:
    events: list[TrajectoryEvent] = []
    sequence = [
        (10.0, "N", "N->_S"),
        (20.0, "S", "S->_N"),
        (60.0, "E", "E->_W"),
        (70.0, "W", "W->_E"),
    ]
    if movement_probe:
        sequence.append((42.0, "N", "N->_E"))
    for cycle_index in range(cycles):
        base_s = cycle_index * cycle_seconds
        for offset_s, approach, movement in sequence:
            events.append(
                TrajectoryEvent(
                    event_type=EventType.RELEASE,
                    timestamp_ms=origin_ms
                    + int(
                        round(
                            (
                                base_s
                                + offset_s
                                + shift_s
                            )
                            * 1000.0
                        )
                    ),
                    approach=approach,
                    movement=movement,
                    confidence=0.95,
                    quality="HIGH",
                )
            )
            events.append(
                TrajectoryEvent(
                    event_type=EventType.CROSSING,
                    timestamp_ms=origin_ms
                    + int(
                        round(
                            (
                                base_s
                                + offset_s
                                + shift_s
                                + 1.0
                            )
                            * 1000.0
                        )
                    ),
                    approach=approach,
                    movement=movement,
                    confidence=0.95,
                    quality="HIGH",
                )
            )
    return tuple(events)


def test_short_conflicting_gap_is_clearance_candidate():
    session = _session(
        (
            _phase(1, 0.0, 40.0, ("N", "S")),
            _phase(2, 44.0, 100.0, ("E", "W")),
        )
    )

    semantics = _gap_semantics(session)

    assert len(semantics["gaps"]) == 1
    gap = semantics["gaps"][0]
    assert gap["start_s"] == 40.0
    assert gap["end_s"] == 44.0
    assert gap["kind"] == "CLEARANCE_CANDIDATE"
    assert gap["previous_axis"] == "NS"
    assert gap["following_axis"] == "EW"
    assert semantics["clearance_candidate_rate"] == 0.04
    assert semantics["unresolved_unknown_rate"] == 0.0
    assert semantics["meets_unresolved_target"] is True


def test_large_gap_with_strong_model_is_unresolved_stage():
    session = _session(
        (
            _phase(1, 0.0, 40.0, ("N", "S"), 0.95),
            _phase(2, 50.0, 100.0, ("E", "W"), 0.96),
        ),
        cycle_confidence=0.91,
        event_count=31_000,
    )

    semantics = _gap_semantics(session)

    gap = semantics["gaps"][0]
    assert gap["kind"] == "UNRESOLVED_STAGE"
    assert "high-confidence" in gap["reason"]
    assert semantics["unresolved_stage_rate"] == 0.10
    assert semantics["unresolved_unknown_rate"] == 0.10


def test_large_gap_with_weak_model_is_unobserved():
    session = _session(
        (
            _phase(1, 0.0, 20.0, ("N", "S"), 0.67),
            _phase(2, 48.0, 100.0, ("E", "W"), 0.65),
        ),
        cycle_confidence=0.59,
        quality="INSUFFICIENT",
        event_count=1100,
    )

    semantics = _gap_semantics(session)

    assert semantics["gaps"][0]["kind"] == "UNOBSERVED"
    assert semantics["unobserved_rate"] == 0.28


def test_movement_probe_promotes_gap_semantics_without_inventing_phase():
    candidate = MovementActivationCandidate(
        approach="N",
        movement="N->_E",
        phase_start=24.0,
        phase_end=40.0,
        repeatability=0.8,
        stability=0.9,
        usable_event_count=80,
        observed_cycle_count=20,
        score=0.85,
    )
    session = _session(
        (
            _phase(1, 0.0, 20.0, ("N", "S"), 0.6),
            _phase(2, 48.0, 100.0, ("E", "W"), 0.6),
        ),
        cycle_confidence=0.6,
        quality="PARTIAL",
        movement_candidates=(candidate,),
    )

    semantics = _gap_semantics(session)

    gap = semantics["gaps"][0]
    assert gap["kind"] == "UNRESOLVED_STAGE"
    assert gap["movement_evidence"]
    assert gap["movement_evidence"][0]["movement"] == "N->_E"


def test_cross_session_family_aligns_same_plan_and_builds_consensus():
    first = _session(
        (
            _phase(1, 0.0, 40.0, ("N", "S")),
            _phase(2, 40.0, 100.0, ("E", "W")),
        ),
        physical_session_index=1,
    )
    weak_shifted = _session(
        (
            _phase(1, 20.0, 55.0, ("N", "S"), 0.65),
            _phase(2, 65.0, 20.0, ("E", "W"), 0.65),
        ),
        cycle_confidence=0.65,
        quality="INSUFFICIENT",
        physical_session_index=2,
    )
    second_good_shifted = _session(
        (
            _phase(1, 40.0, 80.0, ("N", "S")),
            _phase(2, 80.0, 40.0, ("E", "W")),
        ),
        physical_session_index=3,
    )

    families = build_regime_families(
        (first, weak_shifted, second_good_shifted)
    )

    family = max(
        families,
        key=lambda item: item.member_count,
    )
    assert family.member_count >= 2
    assert family.model_quality == "GOOD"
    assert family.consensus_coverage == 1.0
    assert family.consensus_phase_model is not None
    assert len(family.consensus_phase_model["phases"]) == 2
    assert {1, 3}.issubset(
        {
            member.physical_session_index
            for member in family.members
        }
    )
    assert family.pooling_status == "raw_events_unavailable"


def test_same_cycle_but_different_stage_structure_stays_separate():
    simple = _session(
        (
            _phase(1, 0.0, 40.0, ("N", "S")),
            _phase(2, 40.0, 100.0, ("E", "W")),
        ),
        physical_session_index=1,
    )
    staggered = _session(
        (
            _phase(1, 0.0, 20.0, ("N", "S")),
            _phase(2, 20.0, 40.0, ("N",)),
            _phase(3, 40.0, 100.0, ("E", "W")),
        ),
        physical_session_index=2,
    )

    families = build_regime_families(
        (simple, staggered)
    )

    assert len(families) == 2



def test_short_gap_with_movement_evidence_is_transition_ambiguous():
    candidate = MovementActivationCandidate(
        approach="S",
        movement="S->_W",
        phase_start=40.0,
        phase_end=44.0,
        repeatability=0.7,
        stability=0.8,
        usable_event_count=30,
        observed_cycle_count=12,
        score=0.7,
    )
    session = _session(
        (
            _phase(1, 0.0, 40.0, ("N", "S")),
            _phase(2, 44.0, 100.0, ("E", "W")),
        ),
        movement_candidates=(candidate,),
    )

    semantics = _gap_semantics(session)

    gap = semantics["gaps"][0]
    assert gap["kind"] == "TRANSITION_AMBIGUOUS"
    assert semantics["transition_ambiguous_rate"] == 0.04
    assert semantics["clearance_candidate_rate"] == 0.0
    assert semantics["unresolved_unknown_rate"] == 0.04
    assert semantics["meets_unresolved_target"] is False


def test_aligned_pool_combines_raw_events_from_multiple_days():
    first = _session(
        (
            _phase(1, 0.0, 40.0, ("N", "S")),
            _phase(2, 40.0, 100.0, ("E", "W")),
        ),
        physical_session_index=1,
    )
    shifted = _session(
        (
            _phase(1, 20.0, 60.0, ("N", "S")),
            _phase(2, 60.0, 20.0, ("E", "W")),
        ),
        physical_session_index=2,
    )
    first_events = _raw_events(cycles=10)
    shifted_events = _raw_events(
        origin_ms=10_000_000,
        cycles=10,
        shift_s=20.0,
        movement_probe=True,
    )

    pooled, cycle_count = _aligned_pooled_events(
        (
            (1, first, 0, 1.0),
            (2, shifted, 12, 1.0),
        ),
        (first_events, shifted_events),
        cycle_seconds=100.0,
    )

    assert cycle_count >= 20
    assert len(pooled) == len(first_events) + len(shifted_events)
    assert any(event.movement == "N->_E" for event in pooled)
    assert all(
        pooled[index].timestamp_ms
        <= pooled[index + 1].timestamp_ms
        for index in range(len(pooled) - 1)
    )


def test_family_reconstructs_phase_model_from_pooled_raw_evidence():
    first = _session(
        (
            _phase(1, 0.0, 40.0, ("N", "S")),
            _phase(2, 40.0, 100.0, ("E", "W")),
        ),
        physical_session_index=1,
    )
    shifted = _session(
        (
            _phase(1, 20.0, 60.0, ("N", "S")),
            _phase(2, 60.0, 20.0, ("E", "W")),
        ),
        physical_session_index=2,
    )
    first_events = _raw_events(
        cycles=14,
        movement_probe=True,
    )
    shifted_events = _raw_events(
        origin_ms=20_000_000,
        cycles=14,
        shift_s=20.0,
        movement_probe=True,
    )

    families = build_regime_families(
        (first, shifted),
        segment_events=(first_events, shifted_events),
    )

    assert len(families) == 1
    family = families[0]
    assert family.member_count == 2
    assert family.pooled_event_count == (
        len(first_events) + len(shifted_events)
    )
    assert family.pooled_cycle_count >= 28
    assert family.pooling_status in {
        "ok",
        "ambiguous_phase_model",
    }
    assert family.pooled_phase_model is not None
    assert (
        family.pooled_phase_model["model_type"]
        == "cross_session_pooled_evidence"
    )
    assert "movement_stages" in family.pooled_phase_model
    assert "distinct_movement_candidates" in family.pooled_phase_model
    assert family.pooled_coverage is not None
