from __future__ import annotations

from types import SimpleNamespace

from app.core.archive_analysis import _gap_semantics
from app.core.event_phase_discovery import (
    EventPhase,
    EventPhaseDiscoveryResult,
    MovementActivationCandidate,
)
from app.core.reconstruction import SessionReconstruction
from app.core.regime_aggregation import build_regime_families


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

    assert len(families) == 1
    family = families[0]
    assert family.member_count == 3
    assert family.model_quality == "GOOD"
    assert family.consensus_coverage == 1.0
    assert family.consensus_phase_model is not None
    assert len(family.consensus_phase_model["phases"]) == 2
    assert {
        member.physical_session_index
        for member in family.members
    } == {1, 2, 3}


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
