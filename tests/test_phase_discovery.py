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
                            "stopped": False,
                        }
                    )
    return pd.DataFrame(rows)


def test_discovers_temporal_regimes():
    result = PhaseDiscovery(bin_seconds=2.0, min_phase_seconds=8.0).discover(
        _synthetic_frame(), cycle_seconds=120.0
    )
    assert len(result.phases) == 3
    phase_a, phase_mid, phase_b = result.phases
    assert phase_a.active_approaches == ("N", "S")
    assert phase_mid.active_approaches == ("N",)
    assert phase_b.active_approaches == ("E", "W")
    assert set(phase_a.active_movements) == {"N->_S", "S->_N"}
    assert set(phase_b.active_movements) == {"E->_W", "W->_E"}


def test_single_cycle_outlier_does_not_create_new_regime():
    frame = _synthetic_frame(repeats=6)
    outlier = {
        "t_s": 50.0,
        "zone_in": "N",
        "movement": "N->_S",
        "release_weight": 500.0,
        "stopped": False,
    }
    frame = pd.concat([frame, pd.DataFrame([outlier])], ignore_index=True)

    result = PhaseDiscovery(bin_seconds=2.0, min_phase_seconds=8.0).discover(
        frame, cycle_seconds=120.0
    )
    early_phase = next(phase for phase in result.phases if phase.phase_start < 10.0)
    assert early_phase.active_approaches == ("N", "S")


def test_phase_intervals_cover_cycle_without_overlap():
    result = PhaseDiscovery(bin_seconds=2.0, min_phase_seconds=8.0).discover(
        _synthetic_frame(cycle=100.0), cycle_seconds=100.0
    )
    bins = set()
    for phase in result.phases:
        start = int(phase.phase_start / 2)
        end = int(phase.phase_end / 2)
        current = set(range(start, end)) if start < end else set(range(start, 50)) | set(range(0, end))
        assert not bins.intersection(current)
        bins.update(current)
    assert len(bins) == 50


def test_does_not_hardcode_two_phase_order():
    result = PhaseDiscovery(bin_seconds=2.0, min_phase_seconds=8.0).discover(
        _synthetic_frame(cycle=100.0), cycle_seconds=100.0
    )
    assert result.cycle_seconds == 100.0
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
