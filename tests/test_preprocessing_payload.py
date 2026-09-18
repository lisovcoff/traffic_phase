from __future__ import annotations

from app.core.preprocessing import load_trajectory_payload


def test_load_trajectory_payload_reuses_normalization():
    trajectories = load_trajectory_payload([
        {
            "id": 1,
            "millis": 1000,
            "zone_in": "N",
            "zone_out": "_S",
            "category_name": "car",
        }
    ])
    assert len(trajectories) == 1
    assert trajectories[0].movement == "N->_S"
