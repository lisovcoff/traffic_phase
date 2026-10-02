from __future__ import annotations

import numpy as np
import pytest

from app.core.v9.spatial import (
    apply_projection,
    build_spatial_projection,
    compact_trajectories,
)


def _track(identifier, approach, target, x0, y0, x1=None, y1=None):
    if x1 is None:
        x1 = x0 + 0.01
    if y1 is None:
        y1 = y0 + 0.01
    return {
        "id": identifier,
        "zone_in": approach,
        "zone_out": target,
        "detections": [
            {"millis": 1000, "centroid_x": x0, "centroid_y": y0},
            {"millis": 2000, "centroid_x": x1, "centroid_y": y1},
        ],
    }


def _projected_heading(projection, track, reverse=False):
    start = apply_projection(
        projection,
        track["detections"][0]["centroid_x"],
        track["detections"][0]["centroid_y"],
    )
    end = apply_projection(
        projection,
        track["detections"][-1]["centroid_x"],
        track["detections"][-1]["centroid_y"],
    )
    vector = np.subtract(end, start)
    if reverse:
        vector = -vector
    vector = vector / np.linalg.norm(vector)
    return vector


def test_four_approach_projection_aligns_median_straight_headings():
    tracks = [
        # S->N is intentionally ~20 deg to the right of vertical.
        _track(1, "N", "S", 0.28, 0.10, 0.45, 0.90),
        _track(2, "S", "N", 0.58, 0.90, 0.37, 0.10),
        # W->E is intentionally ~9 deg below horizontal.
        _track(3, "E", "W", 0.90, 0.58, 0.10, 0.55),
        _track(4, "W", "E", 0.10, 0.43, 0.90, 0.55),
    ]
    projection = build_spatial_projection(tracks)

    assert projection["method"] == "heading_aligned_four_point_homography"
    alignment = projection["heading_alignment"]
    assert alignment["available"] is True
    assert alignment["observed_orthogonality_error_deg"] > 1.0
    assert alignment["isotropic_scale"] > 0.0

    horizontal = np.median(
        np.asarray(
            [
                _projected_heading(
                    projection, tracks[2], reverse=True
                ),
                _projected_heading(
                    projection, tracks[3]
                ),
            ],
            dtype=float,
        ),
        axis=0,
    )
    vertical = np.median(
        np.asarray(
            [
                _projected_heading(
                    projection, tracks[0], reverse=True
                ),
                _projected_heading(
                    projection, tracks[1]
                ),
            ],
            dtype=float,
        ),
        axis=0,
    )
    horizontal /= np.linalg.norm(horizontal)
    vertical /= np.linalg.norm(vertical)

    assert horizontal[1] == pytest.approx(0.0, abs=0.01)
    assert horizontal[0] > 0.0
    assert vertical[0] == pytest.approx(0.0, abs=0.01)
    assert vertical[1] < 0.0
    assert np.linalg.norm(horizontal) == pytest.approx(
        np.linalg.norm(vertical), rel=1e-7
    )


def test_four_approach_projection_keeps_anchors_near_cardinal_regions():
    tracks = [
        _track(1, "N", "S", 0.28, 0.10, 0.45, 0.90),
        _track(2, "S", "N", 0.58, 0.90, 0.37, 0.10),
        _track(3, "E", "W", 0.90, 0.58, 0.10, 0.55),
        _track(4, "W", "E", 0.10, 0.43, 0.90, 0.55),
    ]
    projection = build_spatial_projection(tracks)
    assert projection["base_method"] == "four_point_homography"
    assert projection["method"] == "heading_aligned_four_point_homography"

    expected = {
        "N": (0.50, 0.10),
        "S": (0.50, 0.90),
        "E": (0.90, 0.50),
        "W": (0.10, 0.50),
    }
    for approach, target in expected.items():
        anchor = projection["anchors"][approach]
        actual = apply_projection(projection, *anchor)
        assert (actual[0] - 0.5) * (target[0] - 0.5) >= -1e-6
        assert (actual[1] - 0.5) * (target[1] - 0.5) >= -1e-6
        assert np.linalg.norm(np.subtract(actual, target)) < 0.12


def _multi_track(identifier, approach, target, points):
    return {
        "id": identifier,
        "zone_in": approach,
        "zone_out": target,
        "detections": [
            {
                "millis": 1000 + index * 1000,
                "centroid_x": x,
                "centroid_y": y,
            }
            for index, (x, y) in enumerate(points)
        ],
    }


def test_t_intersection_projection_uses_three_approaches_and_side_road_heading():
    tracks = [
        _multi_track(
            1, "N", "S",
            [(0.32, 0.05), (0.335, 0.16), (0.35, 0.27), (0.36, 0.40),
             (0.38, 0.54), (0.40, 0.68), (0.43, 0.82), (0.46, 0.95)],
        ),
        _multi_track(
            2, "S", "N",
            [(0.54, 0.95), (0.525, 0.83), (0.51, 0.70), (0.49, 0.56),
             (0.47, 0.43), (0.45, 0.30), (0.43, 0.18), (0.41, 0.05)],
        ),
        # The E leg approaches the junction horizontally, then turns.
        _multi_track(
            3, "E", "N",
            [(0.95, 0.47), (0.88, 0.475), (0.81, 0.48), (0.74, 0.485),
             (0.67, 0.49), (0.60, 0.50), (0.55, 0.54), (0.51, 0.58)],
        ),
        _multi_track(
            4, "E", "S",
            [(0.95, 0.53), (0.88, 0.525), (0.81, 0.52), (0.74, 0.515),
             (0.67, 0.51), (0.60, 0.50), (0.55, 0.46), (0.51, 0.42)],
        ),
    ]
    projection = build_spatial_projection(tracks)

    assert set(projection["anchors"]) == {"N", "S", "E"}
    assert projection["method"] == "heading_aligned_least_squares_affine_partial"
    alignment = projection["heading_alignment"]
    assert alignment["available"] is True
    assert alignment["samples"]["horizontal_approach_fallback"] == 2

    s_start = apply_projection(projection, 0.54, 0.95)
    s_end = apply_projection(projection, 0.41, 0.05)
    # Check only the straight incoming portion of the E leg, before
    # the synthetic vehicle starts turning toward N/S.
    e_vectors = []
    for x0, y0 in ((0.95, 0.47), (0.95, 0.53)):
        start = apply_projection(projection, x0, y0)
        end = apply_projection(projection, 0.81, 0.48 if y0 < 0.5 else 0.52)
        vector = np.subtract(end, start)
        vector /= np.linalg.norm(vector)
        e_vectors.append(vector)

    sn = np.subtract(s_end, s_start)
    sn /= np.linalg.norm(sn)
    e_in = np.median(np.asarray(e_vectors, dtype=float), axis=0)
    e_in /= np.linalg.norm(e_in)

    assert abs(float(sn[0])) < 0.03
    assert sn[1] < 0.0
    assert e_in[0] < 0.0
    assert abs(float(e_in[1])) < 0.03


def test_compact_trajectories_uses_recorded_detection_geometry():
    tracks = [
        {
            "id": 10,
            "zone_in": "N",
            "zone_out": "S",
            "detections": [
                {"millis": 500, "centroid_x": 0.5, "centroid_y": 0.9},
                {"millis": 1000, "centroid_x": 0.5, "centroid_y": 0.8},
            ],
        }
    ]
    anchors = [
        _track(1, "N", "S", 0.60, 0.95),
        _track(2, "S", "N", 0.40, 0.10),
        _track(3, "E", "W", 0.90, 0.50),
        _track(4, "W", "E", 0.10, 0.50),
    ]
    projection = build_spatial_projection(anchors)
    compact = compact_trajectories(
        tracks,
        analysis_base_timestamp_ms=500,
        projection=projection,
    )
    assert len(compact) == 1
    assert compact[0][0] == 10
    assert compact[0][1] == "N"
    assert compact[0][2] == "N->S"
    assert compact[0][3][0][0] == 0.0
    assert compact[0][3][1][0] == 0.5
    assert len(compact[0][3]) == 2
