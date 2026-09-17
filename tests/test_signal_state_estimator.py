from __future__ import annotations

import pandas as pd
import pytest

from app.core.phase_discovery import Phase, PhaseDiscoveryResult
from app.core.signal_state_estimator import DEFAULT_YELLOW_DURATION_SECONDS, SignalState, SignalStateEstimator


def phase_model() -> PhaseDiscoveryResult:
    return PhaseDiscoveryResult(
        100.0,
        2.0,
        (
            Phase(1, 0.0, 40.0, ("N", "S"), ("N->_S", "S->_N"), 0.05, ("N", "S")),
            Phase(2, 50.0, 90.0, ("E", "W"), ("E->_W", "W->_E"), 0.05, ("E", "W")),
        ),
        (),
        {},
    )


def traffic_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "t_s": [4.0, 5.0, 54.0, 55.0],
            "zone_in": ["N", "S", "E", "W"],
            "movement": ["N->_S", "S->_N", "E->_W", "W->_E"],
            "wait_s": [1.0, 1.0, 1.0, 1.0],
            "release_weight": [0.0, 0.0, 0.0, 0.0],
            "stopped": [False, False, False, False],
        }
    )


def states(result):
    return {item.approach: item.state for item in result.approaches}


def test_low_confidence_phase_still_returns_binary_pair():
    empty = traffic_frame().iloc[0:0]
    result = SignalStateEstimator(phase_model()).estimate(10.0, empty)
    current = states(result)
    assert current["N"] == SignalState.GREEN
    assert current["S"] == SignalState.GREEN
    assert current["E"] == SignalState.RED
    assert current["W"] == SignalState.RED
    assert result.phase_confidence == 0.05


def test_recent_traffic_is_diagnostic_not_a_gate():
    result = SignalStateEstimator(phase_model()).estimate(10.0, traffic_frame())
    assert states(result)["N"] == SignalState.GREEN
    assert states(result)["E"] == SignalState.RED
    assert result.approaches[0].evidence_weight > 0
    assert result.approaches[0].confidence == result.phase_confidence


def test_yellow_is_only_transition_state_before_next_phase():
    estimator = SignalStateEstimator(phase_model())
    result = estimator.estimate(39.0, traffic_frame())
    current = states(result)
    assert estimator.yellow_duration_seconds == DEFAULT_YELLOW_DURATION_SECONDS
    assert result.transition is True
    assert result.phase_id == 1
    assert current["N"] == SignalState.YELLOW
    assert current["S"] == SignalState.YELLOW
    assert current["E"] == SignalState.RED
    assert current["W"] == SignalState.RED


def test_custom_yellow_duration_changes_transition_boundary():
    estimator = SignalStateEstimator(phase_model(), yellow_duration_seconds=5.0)
    assert states(estimator.estimate(35.0, traffic_frame()))["N"] == SignalState.YELLOW
    assert states(estimator.estimate(33.0, traffic_frame()))["N"] != SignalState.YELLOW


def test_zero_yellow_duration_disables_transition_state():
    estimator = SignalStateEstimator(phase_model(), yellow_duration_seconds=0.0)
    result = estimator.estimate(39.0, traffic_frame())
    assert result.transition is False


def test_unmodelled_gap_is_unknown_not_false_green():
    result = SignalStateEstimator(phase_model()).estimate(45.0, traffic_frame())
    assert result.phase_id is None
    assert all(item.state == SignalState.UNKNOWN for item in result.approaches)


def test_cycle_wrap_preserves_phase_timeline():
    result = SignalStateEstimator(phase_model()).estimate(110.0, traffic_frame())
    assert result.cycle_phase_s == 10.0
    assert result.phase_id == 1


def test_invalid_yellow_duration():
    with pytest.raises(ValueError):
        SignalStateEstimator(phase_model(), yellow_duration_seconds=100.0)
