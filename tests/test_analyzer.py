from __future__ import annotations

import json

import pandas as pd

from app.core.analyzer import build_movement_profiles, load_trajectories


def test_load_trajectories_filters_non_cars(tmp_path):
    payload = [
        {
            "id": 1,
            "millis": 1000,
            "zone_in": "N",
            "zone_out": "_S",
            "category_name": "car",
            "stay_duration_millis": 5000,
        },
        {
            "id": 2,
            "millis": 2000,
            "zone_in": "S",
            "zone_out": "_N",
            "category_name": "truck",
            "stay_duration_millis": 9000,
        },
    ]

    path = tmp_path / "trajectories.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    frame = load_trajectories(path)

    assert len(frame) == 1
    assert frame.loc[0, "movement"] == "N->_S"
    assert frame.loc[0, "wait_s"] == 5.0
    assert bool(frame.loc[0, "delayed"])


def test_build_movement_profiles_returns_normalized_profiles():
    frame = pd.DataFrame(
        {
            "movement": ["N->_S", "N->_S", "E->_W", "E->_W"],
            "t_s": [10.0, 110.0, 50.0, 150.0],
            "wait_s": [10.0, 10.0, 8.0, 8.0],
            "release_weight": [5.0, 5.0, 3.0, 3.0],
            "delayed": [True, True, True, True],
        }
    )

    raw, normalized, centers = build_movement_profiles(
        frame,
        cycle_s=100.0,
        phase_bin_s=2.0,
    )

    assert set(raw.index) == {"N->_S", "E->_W"}
    assert len(centers) == 50
    assert normalized.max(axis=1).tolist() == [1.0, 1.0]
