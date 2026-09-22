from __future__ import annotations

import asyncio
from io import BytesIO
import json
import zipfile

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.api.routes import phase_analyze
from app.core.archive_analysis import (
    DEFAULT_TIMELINE_POINTS,
    analyze_trajectory_stream,
)


def _record(vehicle_id, timestamp_ms, approach, zone_out):
    return {
        "id": vehicle_id,
        "millis": timestamp_ms + 1000,
        "zone_in": approach,
        "zone_out": zone_out,
        "category_name": "car",
        "detections": [
            {
                "millis": timestamp_ms - 1000,
                "lat": 55.0,
                "lng": 61.0,
                "zone": approach,
            },
            {
                "millis": timestamp_ms,
                "lat": 55.00003,
                "lng": 61.0,
                "zone": None,
            },
            {
                "millis": timestamp_ms + 1000,
                "lat": 55.00006,
                "lng": 61.0,
                "zone": zone_out,
            },
        ],
    }


def _payload(*, origin_ms=0, cycles=10, cycle_seconds=120):
    result = []
    vehicle_id = 0
    movements = (
        (10, "N", "_S"),
        (25, "S", "_N"),
        (70, "E", "_W"),
        (85, "W", "_E"),
    )
    for cycle in range(cycles):
        base_ms = origin_ms + cycle * cycle_seconds * 1000
        for offset_s, approach, zone_out in movements:
            vehicle_id += 1
            result.append(
                _record(
                    vehicle_id,
                    base_ms + offset_s * 1000,
                    approach,
                    zone_out,
                )
            )
    return result


def _upload(name, content):
    return UploadFile(file=BytesIO(content), filename=name)


def _zip_bytes(members):
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members:
            archive.writestr(
                name,
                json.dumps(payload).encode("utf-8"),
            )
    return stream.getvalue()


def test_json_api_returns_session_based_result():
    upload = _upload(
        "sample.json",
        json.dumps(_payload()).encode("utf-8"),
    )

    response = asyncio.run(phase_analyze(upload))

    assert response["source"]["format"] == "json"
    assert response["source"]["session_count"] == 1
    assert len(response["sessions"]) == 1
    session = response["sessions"][0]
    assert session["status"] == "ok"
    assert session["cycle"]["estimated_cycle"] is not None
    assert session["cycle"]["confidence"] >= 0.0
    assert len(session["phase_model"]["phases"]) == 2
    assert session["phase_model"]["model_type"] == "recurring_signal_stages"
    assert session["phase_model"]["stages"] == session["phase_model"]["phases"]
    assert "distinct_movement_candidates" in session["phase_model"]
    assert "movement_stages" in session["phase_model"]
    assert session["phase_model"]["movement_stages"] == []
    assert session["timeline"]
    assert "active_movements" in session["timeline"][0]
    first_point = session["timeline"][0]
    assert set(first_point["states"]) == {"N", "S", "E", "W"}
    assert set(first_point["axis_states"]) == {"NS", "EW"}
    assert first_point["axis_states"]["NS"] in {
        "GREEN",
        "YELLOW",
        "RED",
        "RED_YELLOW",
        "UNKNOWN",
        "MIXED",
    }
    assert response["cycle"] is not None
    assert response["phase_model"] is not None
    assert "cycle_coverage" in session["phase_model"]
    assert "unknown_metrics" in session
    assert "uncovered_cycle_intervals" in session



def test_zip_members_are_sorted_by_trajectory_time_not_archive_order():
    content = _zip_bytes(
        [
            (
                "later.json",
                _payload(
                    origin_ms=5 * 120 * 1000,
                    cycles=5,
                ),
            ),
            ("earlier.json", _payload(cycles=5)),
        ]
    )

    analysis = analyze_trajectory_stream(
        BytesIO(content),
        filename="reverse-order.zip",
    ).to_dict()

    assert analysis["source"]["json_members"] == 2
    assert analysis["source"]["session_count"] == 1
    assert analysis["source"]["cars_used"] == 40
    assert len(analysis["sessions"]) == 1
    assert analysis["sessions"][0]["status"] == "ok"


def test_zip_api_processes_members_and_returns_sessions():
    content = _zip_bytes(
        [
            ("part-1.json", _payload(cycles=5)),
            (
                "part-2.json",
                _payload(
                    origin_ms=5 * 120 * 1000,
                    cycles=5,
                ),
            ),
        ]
    )
    upload = _upload("sample.zip", content)

    response = asyncio.run(phase_analyze(upload))

    assert response["source"]["format"] == "zip"
    assert response["source"]["json_members"] == 2
    assert response["source"]["session_count"] == 1
    assert response["source"]["cars_used"] == 40
    assert response["sessions"][0]["event_count"] >= 40


def test_zip_with_large_gap_returns_two_sessions():
    content = _zip_bytes(
        [
            ("part-1.json", _payload(cycles=5)),
            (
                "part-2.json",
                _payload(
                    origin_ms=3 * 60 * 60 * 1000,
                    cycles=5,
                ),
            ),
        ]
    )

    analysis = analyze_trajectory_stream(
        BytesIO(content),
        filename="two-sessions.zip",
    ).to_dict()

    assert analysis["source"]["session_count"] == 2
    assert len(analysis["sessions"]) == 2
    assert analysis["sessions"][0]["end_timestamp_ms"] < (
        analysis["sessions"][1]["start_timestamp_ms"]
    )


def test_corrupted_zip_api_returns_422():
    upload = _upload("broken.zip", b"not a zip archive")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(phase_analyze(upload))

    assert exc.value.status_code == 422
    assert "corrupted ZIP" in exc.value.detail


def test_zip_without_json_returns_422():
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("readme.txt", "no trajectories")
    upload = _upload("empty.zip", stream.getvalue())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(phase_analyze(upload))

    assert exc.value.status_code == 422
    assert "contains no JSON" in exc.value.detail


def test_insufficient_json_session_is_reported_not_raised():
    upload = _upload(
        "short.json",
        json.dumps([_record(1, 10_000, "N", "_S")]).encode("utf-8"),
    )

    response = asyncio.run(phase_analyze(upload))

    assert response["source"]["session_count"] == 1
    assert response["sessions"][0]["status"] == "insufficient_data"
    assert response["sessions"][0]["cycle"] is None
    assert response["sessions"][0]["error_reason"]


def test_timeline_is_bounded():
    upload = _upload(
        "long.json",
        json.dumps(_payload(cycles=30)).encode("utf-8"),
    )

    response = asyncio.run(phase_analyze(upload))

    assert len(response["sessions"][0]["timeline"]) <= DEFAULT_TIMELINE_POINTS
