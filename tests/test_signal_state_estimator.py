from __future__ import annotations

import pandas as pd
import pytest

from app.core.phase_discovery import Phase, PhaseDiscoveryResult
from app.core.signal_state_estimator import (
    DEFAULT_YELLOW_DURATION_SECONDS,
    SignalState,
    SignalStateEstimator,
)


def phase_model() -> PhaseDiscoveryResult:
    return PhaseDiscoveryResult(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=(
            Phase(1, 0.0, 40.0, ("N", "S"), ("N->_S", "S->_N"), 0.9, ("N", "S")),
            Phase(2, 50.0, 90.0, ("E", "W"), ("E->_W", "W->_E"), 0.9, ("E", "W")),
        ),
        profiles=(),
        similarities={},
    )


def traffic_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "t_s": [4.0, 5.0, 54.0, 55.0, 6.0, 7.0, 56.0, 57.0],
            "zone_in": ["N", "S", "E", "W", "E", "W", "N", "S"],
            "movement": ["N->_S", "S->_N", "E->_W", "W->_E", "E->_W", "W->_E", "N->_S", "S->_N"],
            "release_weight": [5.0, 4.0, 5.0, 4.0, 0.0, 0.0, 0.0, 0.0],
            "stopped": [False, False, False, False, True, True, True, True],
        }
    )


def states(result):
    return {item.approach: item.state for item in result.approaches}


def test_green_and_red_follow_phase_model():
    result = SignalStateEstimator(phase_model()).estimate(10.0, traffic_frame())
    current = states(result)
    assert current["N"] == SignalState.GREEN
    assert current["S"] == SignalState.GREEN
    assert current["E"] == SignalState.RED
    assert current["W"] == SignalState.RED
    assert result.transition is False


def test_yellow_is_only_transition_state_before_next_phase():
    estimator = SignalStateEstimator(phase_model())
    result = estimator.estimate(49.0, traffic_frame())
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
    assert states(estimator.estimate(46.0, traffic_frame()))["N"] == SignalState.YELLOW
    assert states(estimator.estimate(44.0, traffic_frame()))["N"] != SignalState.YELLOW


def test_zero_yellow_duration_disables_transition_state():
    estimator = SignalStateEstimator(phase_model(), yellow_duration_seconds=0.0)
    result = estimator.estimate(49.0, traffic_frame())
    assert result.transition is False


def test_unknown_when_no_evidence():
    empty = traffic_frame().iloc[0:0]
    result = SignalStateEstimator(phase_model()).estimate(10.0, empty)
    assert all(item.state == SignalState.UNKNOWN for item in result.approaches)


def test_unknown_when_phase_confidence_is_low():
    model = phase_model()
    low_confidence = PhaseDiscoveryResult(
        cycle_seconds=model.cycle_seconds,
        bin_seconds=model.bin_seconds,
        phases=tuple(
            Phase(
                phase.phase_id,
                phase.phase_start,
                phase.phase_end,
                phase.active_approaches,
                phase.active_movements,
                0.2,
                phase.members,
            )
            for phase in model.phases
        ),
        profiles=(),
        similarities={},
    )
    result = SignalStateEstimator(low_confidence).estimate(10.0, traffic_frame())
    assert all(item.state != SignalState.GREEN for item in result.approaches)


def test_unmodelled_gap_is_unknown_not_false_green():
    result = SignalStateEstimator(phase_model()).estimate(45.0, traffic_frame())
    assert result.transition is False
    assert result.phase_id is None
    assert all(item.state == SignalState.UNKNOWN for item in result.approaches)


def test_cycle_wrap_preserves_phase_timeline():
    result = SignalStateEstimator(phase_model()).estimate(110.0, traffic_frame())
    assert result.cycle_phase_s == 10.0
    assert result.phase_id == 1


def test_invalid_yellow_duration():
    with pytest.raises(ValueError):
        SignalStateEstimator(phase_model(), yellow_duration_seconds=100.0)
