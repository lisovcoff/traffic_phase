import numpy as np
import pandas as pd

from app.core.phase_discovery import PhaseDiscovery


def _synthetic_frame(cycle=120.0, bin_s=2.0, repeats=6):
    rows = []
    for repeat in range(repeats):
        base = repeat * cycle
        for start, approaches, movements in (
            (0, ("N", "S"), ("N->_S", "S->_N")),
            (50, ("E", "W"), ("E->_W", "W->_E")),
        ):
            for offset in np.arange(0, 18, bin_s):
                t = base + start + float(offset)
                for approach in approaches:
                    movement = movements[0] if approach == approaches[0] else movements[1]
                    rows.append(
                        {
                            "t_s": t,
                            "zone_in": approach,
                            "movement": movement,
                            "release_weight": 5.0,
                        }
                    )
    return pd.DataFrame(rows)


def test_discovers_coactivated_approaches_and_movements():
    result = PhaseDiscovery(bin_seconds=2.0, correlation_threshold=0.85).discover(
        _synthetic_frame(), cycle_seconds=120.0
    )

    assert len(result.phases) == 2
    phase_a, phase_b = result.phases
    assert phase_a.active_approaches == ("N", "S")
    assert phase_b.active_approaches == ("E", "W")
    assert set(phase_a.active_movements) == {"N->_S", "S->_N"}
    assert set(phase_b.active_movements) == {"E->_W", "W->_E"}
    assert phase_a.phase_start < phase_a.phase_end
    assert phase_b.phase_start < phase_b.phase_end


def test_does_not_hardcode_two_phase_order():
    frame = _synthetic_frame(cycle=100.0)
    result = PhaseDiscovery(bin_seconds=2.0, correlation_threshold=0.85).discover(
        frame, cycle_seconds=100.0
    )
    assert result.cycle_seconds == 100.0
    assert sorted(len(phase.members) for phase in result.phases) == [4, 4]
    assert any("N" in phase.active_approaches for phase in result.phases)
    assert any("E" in phase.active_approaches for phase in result.phases)


def test_missing_columns_are_rejected():
    frame = pd.DataFrame({"t_s": [0.0], "zone_in": ["N"]})
    try:
        PhaseDiscovery().discover(frame, cycle_seconds=120.0)
    except ValueError as exc:
        assert "missing required columns" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
