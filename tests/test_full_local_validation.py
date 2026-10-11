from __future__ import annotations

import io
import json
from pathlib import Path

from scripts.full_local_validation import prepare_sorted_member


def test_external_sort_reorders_out_of_order_trajectories(tmp_path: Path):
    payload = [
        {
            "id": "late",
            "millis": 1000,
            "zone_in": "N",
            "zone_out": "_S",
            "category_name": "car",
            "detections": [{"millis": 3000, "lat": 54.0, "lng": 61.0}],
        },
        {
            "id": "early",
            "millis": 3000,
            "zone_in": "S",
            "zone_out": "_N",
            "category_name": "car",
            "detections": [{"millis": 1000, "lat": 54.0, "lng": 61.0}],
        },
        {
            "id": "middle",
            "millis": 2000,
            "zone_in": "E",
            "zone_out": "_W",
            "category_name": "car",
            "detections": [{"millis": 2000, "lat": 54.0, "lng": 61.0}],
        },
    ]
    output, audit = prepare_sorted_member(
        io.BytesIO(json.dumps(payload).encode("utf-8")),
        name="sample.json",
        work_dir=tmp_path / "work",
        chunk_trajectories=1,
    )
    try:
        normalized = json.load(output)
    finally:
        output.close()

    assert [item["id"] for item in normalized] == ["early", "middle", "late"]
    assert audit.order_violation_count == 1
    assert audit.usable_car_count == 3


def test_external_sort_keeps_non_car_out_of_production_stream(tmp_path: Path):
    payload = [
        {"id": "bus", "millis": 1000, "zone_in": "N", "zone_out": "_S", "category_name": "bus", "detections": []},
        {"id": "car", "millis": 2000, "zone_in": "N", "zone_out": "_S", "category_name": "car", "detections": []},
    ]
    output, audit = prepare_sorted_member(
        io.BytesIO(json.dumps(payload).encode("utf-8")),
        name="sample.json",
        work_dir=tmp_path / "work",
        chunk_trajectories=10,
    )
    try:
        normalized = json.load(output)
    finally:
        output.close()

    assert [item["id"] for item in normalized] == ["car"]
    assert audit.category_counts["bus"] == 1
    assert audit.category_counts["car"] == 1


def test_external_sort_matches_explicit_two_trajectory_start_time_contract(tmp_path: Path):
    payload = [
        {
            "id": "A",
            "millis": 3000,
            "zone_in": "N",
            "zone_out": "_S",
            "category_name": "car",
            "detections": [{"millis": 1000, "lat": 54.0, "lng": 61.0}],
        },
        {
            "id": "B",
            "millis": 2000,
            "zone_in": "S",
            "zone_out": "_N",
            "category_name": "car",
            "detections": [{"millis": 2000, "lat": 54.0, "lng": 61.0}],
        },
    ]
    output, _audit = prepare_sorted_member(
        io.BytesIO(json.dumps(payload).encode("utf-8")),
        name="sample.json",
        work_dir=tmp_path / "work",
        chunk_trajectories=1,
    )
    try:
        normalized = json.load(output)
    finally:
        output.close()

    assert [item["id"] for item in normalized] == ["A", "B"]


def test_order_audit_uses_trajectory_start_not_top_level_millis(tmp_path: Path):
    payload = [
        {
            "id": "first",
            "millis": 1000,
            "zone_in": "N",
            "zone_out": "_S",
            "category_name": "car",
            "detections": [{"millis": 3000, "lat": 54.0, "lng": 61.0}],
        },
        {
            "id": "second",
            "millis": 2000,
            "zone_in": "S",
            "zone_out": "_N",
            "category_name": "car",
            "detections": [{"millis": 2000, "lat": 54.0, "lng": 61.0}],
        },
        {
            "id": "third",
            "millis": 3000,
            "zone_in": "E",
            "zone_out": "_W",
            "category_name": "car",
            "detections": [{"millis": 1000, "lat": 54.0, "lng": 61.0}],
        },
    ]
    output, audit = prepare_sorted_member(
        io.BytesIO(json.dumps(payload).encode("utf-8")),
        name="sample.json",
        work_dir=tmp_path / "work",
        chunk_trajectories=1,
    )
    try:
        normalized = json.load(output)
    finally:
        output.close()

    assert [item["id"] for item in normalized] == ["third", "second", "first"]
    assert audit.order_violation_count == 2


def test_external_sort_falls_back_to_top_level_millis_without_detections(tmp_path: Path):
    payload = [
        {
            "id": "late",
            "millis": 3000,
            "zone_in": "N",
            "zone_out": "_S",
            "category_name": "car",
            "detections": [],
        },
        {
            "id": "early",
            "millis": 1000,
            "zone_in": "S",
            "zone_out": "_N",
            "category_name": "car",
            "detections": [],
        },
    ]
    output, _audit = prepare_sorted_member(
        io.BytesIO(json.dumps(payload).encode("utf-8")),
        name="empty-detections.json",
        work_dir=tmp_path / "work",
        chunk_trajectories=1,
    )
    try:
        normalized = json.load(output)
    finally:
        output.close()

    assert [item["id"] for item in normalized] == ["early", "late"]


def test_external_sort_is_stable_for_equal_trajectory_start_times(tmp_path: Path):
    payload = [
        {
            "id": "second",
            "millis": 2000,
            "zone_in": "N",
            "zone_out": "_S",
            "category_name": "car",
            "detections": [{"millis": 1000, "lat": 54.0, "lng": 61.0}],
        },
        {
            "id": "first",
            "millis": 3000,
            "zone_in": "S",
            "zone_out": "_N",
            "category_name": "car",
            "detections": [{"millis": 1000, "lat": 54.0, "lng": 61.0}],
        },
    ]
    output, _audit = prepare_sorted_member(
        io.BytesIO(json.dumps(payload).encode("utf-8")),
        name="stable.json",
        work_dir=tmp_path / "work",
        chunk_trajectories=1,
    )
    try:
        normalized = json.load(output)
    finally:
        output.close()

    assert [item["id"] for item in normalized] == ["second", "first"]


def test_malformed_detection_is_ignored_without_breaking_member(tmp_path: Path):
    payload = [
        {
            "id": "car",
            "millis": 2000,
            "zone_in": "N",
            "zone_out": "_S",
            "category_name": "car",
            "detections": [
                {"millis": 1000, "lat": 91.0, "lng": 61.0},
                {"millis": 2000, "lat": 54.0, "lng": 61.0},
            ],
        },
    ]
    output, audit = prepare_sorted_member(
        io.BytesIO(json.dumps(payload).encode("utf-8")),
        name="malformed-detection.json",
        work_dir=tmp_path / "work",
        chunk_trajectories=1,
    )
    try:
        normalized = json.load(output)
    finally:
        output.close()

    assert [item["id"] for item in normalized] == ["car"]
    assert audit.usable_car_count == 1
    assert audit.error is None


def test_quick_limit_stops_after_usable_trajectories(tmp_path: Path):
    payload = [
        {
            "id": str(index),
            "millis": index + 1000,
            "zone_in": "N",
            "zone_out": "_S",
            "category_name": "car",
            "detections": [
                {"millis": index, "lat": 54.0, "lng": 61.0},
            ],
        }
        for index in range(10)
    ]
    output, audit = prepare_sorted_member(
        io.BytesIO(json.dumps(payload).encode("utf-8")),
        name="limited.json",
        work_dir=tmp_path / "work",
        chunk_trajectories=2,
        max_trajectories=3,
    )
    try:
        normalized = json.load(output)
    finally:
        output.close()

    assert len(normalized) == 3
    assert audit.usable_car_count == 3


def test_quick_limit_validation_is_rejected(tmp_path: Path):
    payload = [
        {
            "id": "car",
            "millis": 1000,
            "zone_in": "N",
            "zone_out": "_S",
            "category_name": "car",
            "detections": [],
        }
    ]
    try:
        prepare_sorted_member(
            io.BytesIO(json.dumps(payload).encode("utf-8")),
            name="invalid.json",
            work_dir=tmp_path / "work",
            max_trajectories=0,
        )
    except ValueError as exc:
        assert "max_trajectories" in str(exc)
    else:
        raise AssertionError("Expected ValueError for non-positive max_trajectories")
