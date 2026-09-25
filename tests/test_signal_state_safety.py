from __future__ import annotations

from app.core.models import EventType, TrajectoryEvent
from app.core.observability import DiagnosticReason
from app.core.signal_state_estimator import SignalState, SignalStateEstimator
from tests.test_signal_state_estimator import model, states


def _event(t: float, approach: str, kind=EventType.RELEASE):
    return TrajectoryEvent(
        event_type=kind,
        timestamp_ms=int(t * 1000),
        approach=approach,
        movement=f"{approach}->x",
        confidence=1.0,
        quality="HIGH",
    )


def test_adversarial_single_vehicle_does_not_create_red_elsewhere():
    result = SignalStateEstimator(model()).estimate(
        20.0,
        [_event(10.0, "N")],
    )
    current = states(result)
    assert current["N_MAIN"].state is SignalState.GREEN
    assert current["E_MAIN"].state is SignalState.UNKNOWN
    assert current["E_MAIN"].diagnostic_reason is DiagnosticReason.INSUFFICIENT_EVENTS


def test_adversarial_false_crossing_is_unknown():
    result = SignalStateEstimator(model()).estimate(
        20.0,
        [_event(10.0, "N", EventType.CROSSING)],
    )
    assert states(result)["N_MAIN"].state is SignalState.UNKNOWN
