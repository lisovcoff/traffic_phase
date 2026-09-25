from __future__ import annotations

from io import BytesIO
import json
from zipfile import ZIP_DEFLATED, ZipFile

from app.core.archive_analysis import (
    ArchiveProgress,
    SegmentEventStore,
    analyze_trajectory_stream,
)
from app.core.preprocessing import iter_trajectory_payload_stream


def _record(
    vehicle_id: int,
    timestamp_ms: int,
    approach: str = "N",
) -> dict[str, object]:
    return {
        "id": vehicle_id,
        "millis": timestamp_ms + 1000,
        "zone_in": approach,
        "zone_out": "_S" if approach == "N" else "_N",
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
                "zone": "_S" if approach == "N" else "_N",
            },
        ],
    }


def _zip_bytes(members: list[tuple[str, bytes]]) -> bytes:
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return stream.getvalue()


class _ChunkedBytesIO(BytesIO):
    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = 31
        return super().read(min(size, 31))


def test_large_json_member_is_decoded_incrementally():
    records = [
        _record(index, 1_000_000 + index * 1_000)
        for index in range(300)
    ]
    stream = _ChunkedBytesIO(json.dumps(records).encode("utf-8"))
    trajectories = list(
        iter_trajectory_payload_stream(
            stream,
            chunk_size=64,
        )
    )
    assert len(trajectories) == 300
    assert trajectories[0].vehicle_id == 0
    assert trajectories[-1].vehicle_id == 299


def test_large_zip_processing_keeps_only_current_session_in_memory():
    members = [
        (
            f"member-{index:03d}.json",
            json.dumps(
                [_record(index, 1_000_000 + index * 120_000)]
            ).encode("utf-8"),
        )
        for index in range(180)
    ]
    updates: list[ArchiveProgress] = []

    analysis = analyze_trajectory_stream(
        BytesIO(_zip_bytes(members)),
        filename="synthetic-large.zip",
        session_gap_seconds=30.0,
        progress_callback=updates.append,
    )

    assert analysis.source_format == "zip"
    assert analysis.json_member_count == 180
    assert analysis.trajectory_count == 180
    assert analysis.event_count > 0
    assert len(analysis.sessions) == 180
    assert isinstance(analysis.segment_events, SegmentEventStore)
    assert analysis.progress is not None
    assert analysis.progress.done is True
    assert analysis.progress.processed_members == 180
    assert analysis.progress.trajectories == 180
    assert analysis.progress.events == analysis.event_count
    assert analysis.progress.peak_session_trajectories == 1
    assert analysis.progress.peak_session_events <= 4
    assert updates
    assert updates[-1].done is True


def test_one_bad_zip_member_isolated_from_other_members():
    members = [
        (
            "good-1.json",
            json.dumps([_record(1, 1_000_000)]).encode("utf-8"),
        ),
        ("broken.json", b"[{\"id\":"),
        (
            "good-2.json",
            json.dumps([_record(2, 3_000_000)]).encode("utf-8"),
        ),
    ]

    analysis = analyze_trajectory_stream(
        BytesIO(_zip_bytes(members)),
        filename="mixed-members.zip",
        session_gap_seconds=30.0,
    )

    assert analysis.trajectory_count == 2
    assert analysis.member_errors
    assert analysis.member_errors[0]["member"] == "broken.json"
    assert len(analysis.sessions) == 2


def test_non_chronological_zip_member_is_skipped_safely():
    members = [
        (
            "good.json",
            json.dumps([_record(1, 1_000_000)]).encode("utf-8"),
        ),
        (
            "unordered.json",
            json.dumps(
                [
                    _record(2, 3_000_000),
                    _record(3, 2_500_000),
                ]
            ).encode("utf-8"),
        ),
    ]

    analysis = analyze_trajectory_stream(
        BytesIO(_zip_bytes(members)),
        filename="unordered-members.zip",
        session_gap_seconds=30.0,
    )

    assert analysis.trajectory_count == 1
    assert len(analysis.sessions) == 1
    assert analysis.member_errors
    assert "ordered by trajectory start time" in analysis.member_errors[0]["error"]


def test_streamed_json_matches_compact_result_shape_of_existing_payload():
    payload = [
        _record(index, 2_000_000 + index * 120_000, approach)
        for index, approach in enumerate(("N", "S", "E", "W") * 3)
    ]
    analysis = analyze_trajectory_stream(
        BytesIO(json.dumps(payload).encode("utf-8")),
        filename="synthetic.json",
        session_gap_seconds=30.0,
    )
    result = analysis.to_dict()

    assert result["mode"] == "session_based_event_inference"
    assert result["source"]["format"] == "json"
    assert result["source"]["cars_used"] == len(payload)
    assert result["source"]["events_used"] == analysis.event_count
    assert result["progress"]["processed_members"] == 1
    assert result["progress"]["done"] is True
    assert all(
        len(session["timeline"]) <= 240
        for session in result["sessions"]
    )
