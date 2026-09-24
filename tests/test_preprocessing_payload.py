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


def test_load_trajectory_payload_accepts_unknown_destination():
    trajectories = load_trajectory_payload([
        {
            "id": 2,
            "millis": 2000,
            "zone_in": "N",
            "category_name": "car",
            "detections": [
                {
                    "millis": 2000,
                    "lat": 55.0,
                    "lng": 61.0,
                    "zone": "N",
                }
            ],
        }
    ])
    assert len(trajectories) == 1
    assert trajectories[0].zone_out == "UNKNOWN"
    assert trajectories[0].movement == "N->UNKNOWN"


def test_load_trajectory_payload_still_filters_non_car():
    trajectories = load_trajectory_payload([
        {
            "id": 3,
            "millis": 3000,
            "zone_in": "N",
            "zone_out": "_S",
            "category_name": "bus",
        }
    ])
    assert trajectories == []
