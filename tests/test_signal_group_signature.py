from __future__ import annotations

from app.core.models import EventType, TrajectoryEvent
from app.core.signal_group_signature import (
    CircularInterval,
    SignalGroupRelation,
    build_movement_phase_signatures,
    compare_movement_signatures,
)


def _event(timestamp_s: float, approach: str, movement: str) -> TrajectoryEvent:
    return TrajectoryEvent(
        event_type=EventType.RELEASE,
        timestamp_ms=int(timestamp_s * 1000),
        approach=approach,
        movement=movement,
        confidence=1.0,
        quality="HIGH",
    )


def _signature(
    movement: str,
    approach: str,
    start: float,
    end: float,
    *,
    support_cycles: int = 8,
) -> object:
    from app.core.signal_group_signature import MovementPhaseSignature

    return MovementPhaseSignature(
        movement=movement,
        approach=approach,
        cycle_seconds=100.0,
        bin_seconds=1.0,
        phase_presence=tuple([1.0] * 100),
        active_intervals=(CircularInterval(start, end, 100.0),),
        support_count=support_cycles,
        observed_cycle_count=support_cycles,
        active_cycle_count=support_cycles,
        repeatability=1.0,
        boundary_stability=1.0,
    )


def test_circular_interval_wraparound_geometry():
    interval = CircularInterval(90.0, 10.0, 100.0)

    assert interval.duration == 20.0
    assert interval.contains(95.0)
    assert interval.contains(5.0)
    assert not interval.contains(50.0)


def test_circular_interval_iou_handles_wraparound():
    first = CircularInterval(90.0, 10.0, 100.0)
    second = CircularInterval(95.0, 5.0, 100.0)

    assert first.iou(second) == 0.5
    assert first.containment(second) == 0.5


def test_equivalent_movements_are_equivalent():
    left = _signature("N->S", "N", 10.0, 40.0)
    right = _signature("N->W", "N", 11.0, 41.0)

    assert compare_movement_signatures(left, right) is SignalGroupRelation.EQUIVALENT


def test_strict_subset_is_reported_as_containment():
    parent = _signature("N->S", "N", 10.0, 50.0)
    child = _signature("N->E", "N", 20.0, 40.0)

    assert compare_movement_signatures(child, parent) is SignalGroupRelation.CONTAINED
    assert compare_movement_signatures(parent, child) is SignalGroupRelation.CONTAINS


def test_separated_movements_are_disjoint():
    left = _signature("N->S", "N", 10.0, 30.0)
    right = _signature("N->E", "N", 50.0, 70.0)

    assert compare_movement_signatures(left, right) is SignalGroupRelation.DISJOINT


def test_coincident_cross_approach_movements_never_merge():
    east = _signature("E->N", "E", 20.0, 40.0)
    north = _signature("N->E", "N", 20.0, 40.0)

    assert compare_movement_signatures(east, north) is SignalGroupRelation.CROSS_APPROACH


def test_sparse_signature_is_insufficient():
    left = _signature("N->S", "N", 10.0, 40.0, support_cycles=2)
    right = _signature("N->E", "N", 10.0, 40.0, support_cycles=8)

    assert compare_movement_signatures(left, right) is SignalGroupRelation.INSUFFICIENT_EVIDENCE


def test_phase_folding_is_cycle_normalized_and_deduplicates_release_crossing():
    events = []
    for cycle_index in range(8):
        base = cycle_index * 100.0
        events.extend(
            (
                _event(base + 20.0, "N", "N->S"),
                _event(base + 21.0, "N", "N->S"),
            )
        )

    signatures = build_movement_phase_signatures(
        events,
        cycle_seconds=100.0,
        bin_seconds=2.0,
    )

    assert len(signatures) == 1
    signature = signatures[0]
    assert signature.movement == "N->S"
    assert signature.support_count == 8
    assert signature.observed_cycle_count == 8
    assert signature.active_cycle_count == 8
    assert signature.repeatability == 1.0
    assert any(interval.contains(20.0) for interval in signature.active_intervals)


def test_sparse_movement_does_not_get_fabricated_active_interval():
    events = [
        _event(20.0, "N", "N->S"),
        _event(120.0 + 20.0, "N", "N->S"),
    ]

    signatures = build_movement_phase_signatures(
        events,
        cycle_seconds=100.0,
        bin_seconds=2.0,
        min_cycle_presence=0.75,
    )

    assert len(signatures) == 1
    signature = signatures[0]
    assert signature.active_intervals == ()
    assert signature.active_cycle_count == 0
    assert not signature.is_sufficient
