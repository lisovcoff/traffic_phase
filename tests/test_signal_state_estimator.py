from __future__ import annotations

from app.core.event_phase_discovery import (
    EventPhase,
    EventPhaseDiscoveryResult,
)
from app.core.intersection_topology import (
    IntersectionTopology,
    SignalFamily,
)
from app.core.models import EventType, TrajectoryEvent
from app.core.signal_state_estimator import (
    DEFAULT_RED_YELLOW_DURATION_SECONDS,
    DEFAULT_YELLOW_DURATION_SECONDS,
    SignalState,
    SignalStateEstimator,
)


def event(kind, t, approach, confidence=1.0):
    return TrajectoryEvent(
        event_type=kind,
        timestamp_ms=int(t * 1000),
        approach=approach,
        movement=f"{approach}->x",
        confidence=confidence,
        quality="HIGH",
    )


def model(gapped=False):
    phases = (
        EventPhase(1, 0.0, 40.0, ("N", "S"), 0.9, 10, 1, ("N", "S")),
        EventPhase(
            2,
            50.0 if gapped else 40.0,
            90.0 if gapped else 100.0,
            ("E", "W"),
            0.9,
            10,
            1,
            ("E", "W"),
        ),
    )
    return EventPhaseDiscoveryResult(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=phases,
        profiles=(),
        cycle_coverage=0.8 if gapped else 1.0,
        overlap=0.0,
        supporting_event_count=20,
        contradictory_event_count=2,
    )


def states(result):
    return {item.approach: item for item in result.approaches}


def test_green_uses_phase_and_real_release_evidence():
    result = SignalStateEstimator(model()).estimate(
        20.0,
        [event(EventType.RELEASE, 10, "N"), event(EventType.CROSSING, 11, "N")],
    )
    assert states(result)["N"].state == SignalState.GREEN
    assert states(result)["N"].traffic_evidence_confidence > 0
    assert states(result)["N"].phase_confidence > 0


def test_green_does_not_require_stop_or_wait_evidence():
    result = SignalStateEstimator(model()).estimate(20.0, [])
    assert states(result)["N"].state == SignalState.GREEN


def test_green_yellow_red_sequence_for_ns_uses_exact_three_second_yellow():
    estimator = SignalStateEstimator(model())
    before = estimator.estimate(36.999, [])
    yellow_start = estimator.estimate(
        37.0,
        [event(EventType.CROSSING, 37.0, "N")],
    )
    yellow_end = estimator.estimate(
        39.999,
        [event(EventType.CROSSING, 39.9, "N")],
    )
    red = estimator.estimate(
        40.0,
        [event(EventType.CROSSING, 39.9, "N")],
    )

    assert DEFAULT_YELLOW_DURATION_SECONDS == 3.0
    assert states(before)["N"].state == SignalState.GREEN
    assert states(yellow_start)["N"].state == SignalState.YELLOW
    assert states(yellow_end)["N"].state == SignalState.YELLOW
    assert states(red)["N"].state == SignalState.RED
    assert states(yellow_end)["N"].supporting_event_count > 0


def test_red_yellow_is_separate_two_second_pre_green_state():
    estimator = SignalStateEstimator(model())
    start = estimator.estimate(40.0, [])
    end = estimator.estimate(41.999, [])
    green = estimator.estimate(
        42.0,
        [event(EventType.RELEASE, 42.0, "E")],
    )

    assert DEFAULT_RED_YELLOW_DURATION_SECONDS == 2.0
    assert states(start)["E"].state == SignalState.RED_YELLOW
    assert states(end)["E"].state == SignalState.RED_YELLOW
    assert states(start)["N"].state == SignalState.RED
    assert states(green)["E"].state == SignalState.GREEN


def test_missing_phase_is_unknown():
    result = SignalStateEstimator(model(gapped=True)).estimate(45.0, [])
    assert all(item.state == SignalState.UNKNOWN for item in result.approaches)


def test_confidence_dimensions_are_separate():
    result = SignalStateEstimator(model()).estimate(
        20.0,
        [event(EventType.RELEASE, 10, "N", 0.2)],
    )
    n = states(result)["N"]
    assert n.phase_confidence != n.traffic_evidence_confidence
    assert n.confidence == n.probability


def test_short_conflicting_event_does_not_flip_green():
    result = SignalStateEstimator(
        model(),
        conflict_persistence_seconds=3.0,
    ).estimate(
        20.0,
        [
            event(EventType.RELEASE, 10, "N"),
            event(EventType.CROSSING, 19.0, "E"),
        ],
    )
    assert states(result)["N"].state == SignalState.GREEN
    assert states(result)["N"].contradictory_event_count > 0
    assert states(result)["N"].probability <= 0.55


def test_event_confidence_changes_probability_not_state():
    high = SignalStateEstimator(model()).estimate(
        20.0, [event(EventType.RELEASE, 10, "N", 1.0)]
    )
    low = SignalStateEstimator(model()).estimate(
        20.0, [event(EventType.RELEASE, 10, "N", 0.1)]
    )
    assert states(high)["N"].state == SignalState.GREEN
    assert states(low)["N"].state == SignalState.GREEN
    assert states(high)["N"].probability > states(low)["N"].probability


def test_red_is_opposite_phase_not_waiting_evidence():
    result = SignalStateEstimator(model()).estimate(45.0, [])
    assert states(result)["N"].state == SignalState.RED
    assert states(result)["E"].state == SignalState.GREEN


def test_estimator_accepts_event_sequence():
    result = SignalStateEstimator(model()).estimate(
        20.0,
        [event(EventType.RELEASE, 10, "N")],
    )
    assert result.approaches


def test_recent_events_use_normalized_timeline():
    result = SignalStateEstimator(model(), recent_window_s=12.0).estimate(
        20.0,
        [event(EventType.RELEASE, 10, "N")],
    )
    n = states(result)["N"]
    assert n.supporting_event_count == 1
    assert n.evidence_weight > 0
    assert n.traffic_evidence_confidence > 0


def test_absolute_event_timestamps_can_be_rebased_explicitly():
    estimator = SignalStateEstimator(
        model(),
        recent_window_s=12.0,
        event_origin_ms=1_000_000,
    )
    result = estimator.estimate(
        20.0,
        [TrajectoryEvent(
            event_type=EventType.RELEASE,
            timestamp_ms=1_010_000,
            approach="N",
            movement="N->x",
            confidence=1.0,
            quality="HIGH",
        )],
    )
    assert states(result)["N"].supporting_event_count == 1



def staggered_model():
    phases = (
        EventPhase(1, 0.0, 20.0, ("N",), 0.9, 20, 1, ("N",)),
        EventPhase(2, 20.0, 50.0, ("N", "S"), 0.9, 30, 1, ("N", "S")),
        EventPhase(3, 55.0, 100.0, ("E", "W"), 0.9, 40, 1, ("E", "W")),
    )
    return EventPhaseDiscoveryResult(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=phases,
        profiles=(),
        cycle_coverage=0.95,
        overlap=0.0,
        supporting_event_count=90,
        contradictory_event_count=3,
    )


def test_staggered_stage_states_and_clearance_are_explicit():
    estimator = SignalStateEstimator(staggered_model())

    n_only = states(estimator.estimate(10.0, []))
    assert n_only["N"].state == SignalState.GREEN
    assert n_only["S"].state == SignalState.RED
    assert n_only["E"].state == SignalState.RED

    overlap = states(estimator.estimate(30.0, []))
    assert overlap["N"].state == SignalState.GREEN
    assert overlap["S"].state == SignalState.GREEN
    assert overlap["E"].state == SignalState.RED

    clearance = states(estimator.estimate(52.0, []))
    assert {item.state for item in clearance.values()} == {
        SignalState.UNKNOWN
    }

    cross = states(estimator.estimate(70.0, []))
    assert cross["N"].state == SignalState.RED
    assert cross["S"].state == SignalState.RED
    assert cross["E"].state == SignalState.GREEN
    assert cross["W"].state == SignalState.GREEN


def test_internal_stage_boundary_does_not_turn_continuing_n_yellow():
    estimator = SignalStateEstimator(staggered_model())
    result = states(estimator.estimate(20.5, []))

    assert result["N"].state == SignalState.GREEN
    assert result["S"].state == SignalState.RED_YELLOW



def test_yellow_and_red_yellow_durations_are_independent():
    estimator = SignalStateEstimator(
        model(),
        yellow_duration_seconds=3.0,
        red_yellow_duration_seconds=0.0,
    )
    assert states(estimator.estimate(37.0, []))["N"].state == SignalState.YELLOW
    assert states(estimator.estimate(40.0, []))["E"].state == SignalState.GREEN


def test_signal_result_exposes_backend_transition_timing():
    result = SignalStateEstimator(model()).estimate(20.0, [])
    payload = result.to_dict()
    assert result.yellow_duration_seconds == 3.0
    assert result.red_yellow_duration_seconds == 2.0
    assert payload["yellow_duration_seconds"] == 3.0
    assert payload["red_yellow_duration_seconds"] == 2.0


def test_continuing_approach_stays_green_across_internal_stage_boundary():
    estimator = SignalStateEstimator(staggered_model())
    before = states(estimator.estimate(19.0, []))
    just_after = states(estimator.estimate(20.5, []))
    after_red_yellow = states(estimator.estimate(22.0, []))

    assert before["N"].state == SignalState.GREEN
    assert just_after["N"].state == SignalState.GREEN
    assert just_after["S"].state == SignalState.RED_YELLOW
    assert after_red_yellow["N"].state == SignalState.GREEN
    assert after_red_yellow["S"].state == SignalState.GREEN



def test_default_topology_keeps_orthogonal_release_as_contradiction():
    result = SignalStateEstimator(model()).estimate(
        20.0,
        [
            event(EventType.RELEASE, 19.0, "N"),
            event(EventType.RELEASE, 19.5, "E"),
        ],
    )
    current = states(result)
    assert current["N"].contradictory_event_count == 1
    assert current["E"].contradictory_event_count == 1


def test_explicit_movement_compatibility_suppresses_false_conflict_evidence():
    topology = IntersectionTopology(
        families=(
            SignalFamily("MAIN", ("N", "S")),
            SignalFamily("CROSS", ("E", "W")),
        ),
        family_conflicts=(("MAIN", "CROSS"),),
        movement_compatibilities=(("N->x", "E->x"),),
    )
    result = SignalStateEstimator(
        model(),
        topology=topology,
    ).estimate(
        20.0,
        [
            event(EventType.RELEASE, 19.0, "N"),
            event(EventType.RELEASE, 19.5, "E"),
        ],
    )
    current = states(result)

    assert current["N"].contradictory_event_count == 0
    assert current["E"].contradictory_event_count == 0
    assert current["E"].state == SignalState.RED


def test_no_traffic_is_not_positive_green_evidence_for_inactive_family():
    topology = IntersectionTopology(
        families=(
            SignalFamily("MAIN", ("N", "S")),
            SignalFamily("CROSS", ("E", "W")),
        ),
        family_conflicts=(("MAIN", "CROSS"),),
    )
    result = SignalStateEstimator(
        model(),
        topology=topology,
    ).estimate(20.0, [])
    current = states(result)

    assert current["E"].state == SignalState.RED
    assert current["E"].supporting_event_count == 0
    assert current["E"].traffic_evidence_confidence == 0.0
