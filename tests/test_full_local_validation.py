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
