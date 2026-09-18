from __future__ import annotations

from app.core.event_phase_discovery import (
    EventPhase,
    EventPhaseDiscoveryResult,
)
from app.core.models import EventType, TrajectoryEvent
from app.core.signal_state_estimator import SignalState, SignalStateEstimator


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


def test_green_yellow_red_sequence_for_ns():
    estimator = SignalStateEstimator(model())
    green = estimator.estimate(20.0, [event(EventType.RELEASE, 10, "N")])
    yellow = estimator.estimate(39.0, [event(EventType.RELEASE, 10, "N")])
    red = estimator.estimate(45.0, [event(EventType.RELEASE, 10, "N")])
    assert states(green)["N"].state == SignalState.GREEN
    assert states(yellow)["N"].state == SignalState.YELLOW
    assert states(red)["N"].state == SignalState.RED


def test_red_yellow_then_green_for_ew():
    estimator = SignalStateEstimator(model())
    red_yellow = estimator.estimate(40.0, [event(EventType.RELEASE, 60, "E")])
    green = estimator.estimate(43.0, [event(EventType.RELEASE, 42, "E")])
    assert states(red_yellow)["E"].state == SignalState.RED_YELLOW
    assert states(red_yellow)["N"].state == SignalState.RED
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
