from pathlib import Path

from app.core.models import TrafficWindow
from app.core.preprocessing import (
    STOP_THRESHOLD_S,
    build_traffic_windows,
    load_trajectory_file,
    load_trajectory_files,
    trajectories_to_frame,
)


FIXTURE = Path(__file__).parent / "fixtures" / "reference_trajectory_sample.json"


def test_real_format_fixture_is_filtered_and_normalized():
    trajectories = load_trajectory_file(FIXTURE)

    assert len(trajectories) == 3
    assert trajectories[0].vehicle_id == 272
    assert trajectories[0].movement == "N->_W"
    assert trajectories[0].timestamp_ms == 1739952000000
    assert trajectories[0].wait_s == 27.51

    frame = trajectories_to_frame(trajectories)
    assert frame["t_s"].min() == 0.0
    assert frame.loc[0, "stopped"]
    assert frame.loc[0, "release_weight"] == 27.51 - STOP_THRESHOLD_S


def test_multiple_files_and_window_features():
    trajectories = load_trajectory_files([FIXTURE, FIXTURE])
    windows = build_traffic_windows(trajectories, window_s=10.0)

    assert windows
    assert all(isinstance(window, TrafficWindow) for window in windows)

    n_to_w = next(
        window
        for window in windows
        if window.movement == "N->_W"
    )
    assert n_to_w.flow == 2
    assert n_to_w.stopped_count == 2
    assert n_to_w.mean_wait == 27.51
    assert n_to_w.release_weight == 2 * (27.51 - STOP_THRESHOLD_S)


def test_invalid_window_is_rejected():
    trajectories = load_trajectory_file(FIXTURE)

    try:
        build_traffic_windows(trajectories, window_s=0)
    except ValueError as exc:
        assert "window_s" in str(exc)
    else:
        raise AssertionError("Expected ValueError for non-positive window")
