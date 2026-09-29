from __future__ import annotations

from app.core.models import EventType, TrajectoryEvent
from app.core.signal_group_discovery import (
    SignalGroupDiscovery,
    SignalGroupEvidence,
)
from app.core.signal_group_signature import (
    CircularInterval,
    MovementPhaseSignature,
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
    repeatability: float = 1.0,
    stability: float = 1.0,
    intervals: tuple[tuple[float, float], ...] | None = None,
) -> MovementPhaseSignature:
    interval_values = intervals or ((start, end),)
    return MovementPhaseSignature(
        movement=movement,
        approach=approach,
        cycle_seconds=100.0,
        bin_seconds=1.0,
        phase_presence=tuple([1.0] * 100),
        active_intervals=tuple(
            CircularInterval(first, last, 100.0)
            for first, last in interval_values
        ),
        support_count=support_cycles,
        observed_cycle_count=support_cycles,
        active_cycle_count=support_cycles,
        repeatability=repeatability,
        boundary_stability=stability,
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


def test_partial_overlap_is_preserved_as_evidence():
    left = _signature("N->S", "N", 10.0, 40.0)
    right = _signature("N->E", "N", 30.0, 60.0)

    assert compare_movement_signatures(left, right) is SignalGroupRelation.PARTIAL_OVERLAP


def test_double_serviced_signatures_require_set_level_equivalence():
    left = _signature(
        "N->S", "N", 5.0, 20.0,
        intervals=((5.0, 20.0), (60.0, 75.0)),
    )
    right = _signature(
        "N->W", "N", 6.0, 21.0,
        intervals=((6.0, 21.0), (61.0, 76.0)),
    )

    assert compare_movement_signatures(left, right) is SignalGroupRelation.EQUIVALENT


def test_one_matching_interval_does_not_hide_second_service_difference():
    left = _signature(
        "N->S", "N", 5.0, 20.0,
        intervals=((5.0, 20.0), (60.0, 75.0)),
    )
    right = _signature("N->W", "N", 6.0, 21.0)

    assert compare_movement_signatures(left, right) is SignalGroupRelation.CONTAINS


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
        origin_timestamp_ms=0,
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


def test_grouping_requires_equivalence_with_every_group_member():
    result = SignalGroupDiscovery().discover(
        [
            _signature("N->A", "N", 10.0, 40.0),
            _signature("N->B", "N", 10.0, 40.0),
            _signature("N->C", "N", 22.0, 52.0),
        ]
    )

    assert len(result.groups) == 2
    assert result.groups[0].movement_ids == ("N->A", "N->B")
    assert result.groups[0].evidence is SignalGroupEvidence.SUPPORTED
    assert result.groups[1].movement_ids == ("N->C",)
    assert result.groups[1].evidence is SignalGroupEvidence.STRUCTURAL_HYPOTHESIS


def test_singleton_logical_group_is_structural_hypothesis():
    result = SignalGroupDiscovery().discover(
        [_signature("N->S", "N", 10.0, 40.0)]
    )

    assert len(result.groups) == 1
    assert result.groups[0].movement_ids == ("N->S",)
    assert result.groups[0].evidence is SignalGroupEvidence.STRUCTURAL_HYPOTHESIS
    assert result.groups[0].to_dict()["evidence"] == "structural_hypothesis"


def test_group_numbering_is_approach_local_and_deterministic():
    result = SignalGroupDiscovery().discover(
        [
            _signature("E->N", "E", 10.0, 30.0),
            _signature("N->S", "N", 10.0, 30.0),
            _signature("N->W", "N", 10.0, 30.0),
            _signature("E->S", "E", 50.0, 70.0),
        ]
    )

    assert [group.group_id for group in result.groups] == [
        "E:SG1",
        "E:SG2",
        "N:SG1",
    ]


def test_identical_movements_share_one_logical_group():
    result = SignalGroupDiscovery().discover(
        [
            _signature("N->S", "N", 10.0, 40.0),
            _signature("N->W", "N", 11.0, 41.0),
        ]
    )

    assert len(result.groups) == 1
    assert result.groups[0].movement_ids == ("N->S", "N->W")
    assert result.groups[0].evidence is SignalGroupEvidence.SUPPORTED


def test_relation_evidence_marks_equivalent_as_supported():
    result = SignalGroupDiscovery().discover(
        [
            _signature("N->S", "N", 10.0, 40.0),
            _signature("N->W", "N", 11.0, 41.0),
        ]
    )

    assert len(result.relations) == 1
    relation = result.relations[0]
    assert relation.relation is SignalGroupRelation.EQUIVALENT
    assert relation.evidence is SignalGroupEvidence.SUPPORTED
    assert relation.to_dict()["evidence"] == "supported"


def test_relation_evidence_marks_containment_as_structural_hypothesis():
    result = SignalGroupDiscovery().discover(
        [
            _signature("N->E", "N", 20.0, 40.0),
            _signature("N->S", "N", 10.0, 50.0),
        ]
    )

    assert len(result.relations) == 1
    relation = result.relations[0]
    assert relation.relation is SignalGroupRelation.CONTAINED
    assert relation.evidence is SignalGroupEvidence.STRUCTURAL_HYPOTHESIS
    assert relation.to_dict()["evidence"] == "structural_hypothesis"


def test_relation_evidence_marks_cross_approach_as_structural_hypothesis():
    result = SignalGroupDiscovery().discover(
        [
            _signature("E->N", "E", 20.0, 40.0),
            _signature("N->E", "N", 20.0, 40.0),
        ]
    )

    assert len(result.relations) == 1
    relation = result.relations[0]
    assert relation.relation is SignalGroupRelation.CROSS_APPROACH
    assert relation.evidence is SignalGroupEvidence.STRUCTURAL_HYPOTHESIS
    assert relation.to_dict()["evidence"] == "structural_hypothesis"


def test_physical_head_redundancy_stays_a_single_logical_group():
    result = SignalGroupDiscovery().discover(
        [
            _signature("N->S", "N", 10.0, 40.0),
            _signature("N->W", "N", 10.0, 40.0),
        ]
    )

    assert len(result.groups) == 1


def test_separated_intervals_create_two_logical_groups():
    result = SignalGroupDiscovery().discover(
        [
            _signature("N->S", "N", 10.0, 30.0),
            _signature("N->W", "N", 50.0, 70.0),
        ]
    )

    assert len(result.groups) == 2


def test_strict_turn_subset_remains_inclusion_hypothesis():
    result = SignalGroupDiscovery().discover(
        [
            _signature("N->E", "N", 20.0, 40.0),
            _signature("N->S", "N", 10.0, 50.0),
        ]
    )

    assert len(result.groups) == 2
    assert any(
        relation.relation is SignalGroupRelation.CONTAINED
        for relation in result.relations
    )


def test_sparse_turn_evidence_is_not_promoted():
    result = SignalGroupDiscovery().discover(
        [
            _signature("N->S", "N", 10.0, 50.0),
            _signature("N->E", "N", 20.0, 40.0, support_cycles=2),
        ]
    )

    assert len(result.groups) == 1
    assert result.insufficient_movements == ("N->E",)


def test_sparse_permissive_gap_like_traffic_is_not_promoted():
    result = SignalGroupDiscovery().discover(
        [
            _signature("N->S", "N", 10.0, 50.0),
            _signature("N->E", "N", 35.0, 38.0, support_cycles=2),
        ]
    )

    assert len(result.groups) == 1
    assert result.insufficient_movements == ("N->E",)


def test_cross_approach_coincidence_stays_separate():
    result = SignalGroupDiscovery().discover(
        [
            _signature("N->S", "N", 20.0, 40.0),
            _signature("E->N", "E", 20.0, 40.0),
        ]
    )

    assert len(result.groups) == 2
    assert {group.approach for group in result.groups} == {"N", "E"}


def test_circular_group_interval_crossing_zero():
    result = SignalGroupDiscovery().discover(
        [
            _signature("N->S", "N", 95.0, 10.0),
            _signature("N->W", "N", 96.0, 11.0),
        ]
    )

    assert len(result.groups) == 1
    assert result.groups[0].intervals[0].contains(99.0)
    assert result.groups[0].intervals[0].contains(5.0)


def test_double_servicing_is_preserved_in_group_candidate():
    result = SignalGroupDiscovery().discover(
        [
            _signature(
                "N->S", "N", 5.0, 20.0,
                intervals=((5.0, 20.0), (60.0, 75.0)),
            ),
            _signature(
                "N->W", "N", 6.0, 21.0,
                intervals=((6.0, 21.0), (61.0, 76.0)),
            ),
        ]
    )

    assert len(result.groups) == 1
    assert len(result.groups[0].intervals) == 2
    assert result.groups[0].intervals[1].contains(70.0)


def test_variable_duration_does_not_force_a_split():
    result = SignalGroupDiscovery().discover(
        [
            _signature("N->S", "N", 10.0, 40.0),
            _signature("N->W", "N", 10.0, 48.0),
        ]
    )

    assert len(result.groups) == 1


def test_movement_without_demand_does_not_create_a_group():
    result = SignalGroupDiscovery().discover([])

    assert result.groups == ()
    assert result.insufficient_movements == ()


def test_signal_group_mapping_preserves_supported_group_membership():
    from app.core.signal_group_mapping import (
        SignalGroupMappingStatus,
        build_signal_group_mapping,
    )

    result = SignalGroupDiscovery().discover(
        [
            _signature("N->S", "N", 10.0, 40.0),
            _signature("N->W", "N", 11.0, 41.0),
        ]
    )

    mapping = build_signal_group_mapping(result)

    assert mapping.movement_to_group == {
        "N->S": "N:SG1",
        "N->W": "N:SG1",
    }
    assert mapping.group_to_movements == {
        "N:SG1": ("N->S", "N->W"),
    }
    assert mapping.unmapped_movements == ()
    assert all(
        entry.status is SignalGroupMappingStatus.MAPPED
        for entry in mapping.entries
    )


def test_signal_group_mapping_keeps_singleton_as_structural_hypothesis():
    from app.core.signal_group_mapping import build_signal_group_mapping

    result = SignalGroupDiscovery().discover(
        [_signature("N->S", "N", 10.0, 40.0)]
    )

    mapping = build_signal_group_mapping(result)

    assert len(mapping.entries) == 1
    entry = mapping.entries[0]
    assert entry.group_id == "N:SG1"
    assert entry.evidence is SignalGroupEvidence.STRUCTURAL_HYPOTHESIS
    assert mapping.to_dict()["entries"][0]["status"] == "mapped"


def test_signal_group_mapping_preserves_insufficient_movements_as_unmapped():
    from app.core.signal_group_mapping import (
        SignalGroupMappingStatus,
        build_signal_group_mapping,
    )

    result = SignalGroupDiscovery().discover(
        [
            _signature("N->S", "N", 10.0, 40.0),
            _signature("N->E", "N", 20.0, 40.0, support_cycles=2),
        ]
    )

    mapping = build_signal_group_mapping(result)

    assert mapping.movement_to_group == {"N->S": "N:SG1"}
    assert mapping.unmapped_movements == ("N->E",)
    assert mapping.entries[1].status is SignalGroupMappingStatus.UNMAPPED
    assert mapping.entries[1].evidence is SignalGroupEvidence.INSUFFICIENT_EVIDENCE
    assert mapping.entries[1].confidence == 0.0


def test_signal_group_mapping_is_deterministic_and_serializable():
    from app.core.signal_group_mapping import build_signal_group_mapping

    result = SignalGroupDiscovery().discover(
        [
            _signature("W->E", "W", 50.0, 70.0),
            _signature("N->W", "N", 10.0, 30.0),
            _signature("N->S", "N", 11.0, 31.0),
        ]
    )

    mapping = build_signal_group_mapping(result)

    assert [entry.movement_id for entry in mapping.entries] == [
        "N->S",
        "N->W",
        "W->E",
    ]
    payload = mapping.to_dict()
    assert payload["movement_to_group"]["N->S"] == "N:SG1"
    assert payload["group_to_movements"]["N:SG1"] == ["N->S", "N->W"]

