from __future__ import annotations

import asyncio
from io import BytesIO

from fastapi import UploadFile

from app.api.visualization import visualization_analyze, visualization_page


def test_visualization_page_is_the_unified_v10_entrypoint():
    html = visualization_page()

    assert "V10 — Traffic Phase" in html
    assert "/visualization/analyze" in html
    assert 'accept=".json,.zip' in html
    assert "V9 discovery" in html
    assert "V10 физическая семантика" in html


def test_visualization_analyze_builds_v9_v10_spatial_html(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        "app.api.visualization.LOG_ROOT",
        tmp_path / "logs",
    )

    tracks = [
        {
            "id": 1,
            "zone_in": "N",
            "zone_out": "S",
            "detections": [
                {"millis": 1000, "centroid_x": 0.5, "centroid_y": 0.9},
                {"millis": 2000, "centroid_x": 0.5, "centroid_y": 0.8},
            ],
        }
    ]
    result = {
        "algorithm": "direction-agnostic traffic phase discovery V9",
        "analysis_base_timestamp_ms": 1000.0,
        "trajectory_count": 1,
        "event_count": 1,
        "recording_duration_s": 10.0,
        "schedule": {
            "period_s": 10.0,
            "phase_count": 1,
            "phase_names": ["PHASE_A"],
            "baseline_segments": [[0.0, 10.0, 0]],
            "stream_activity_by_phase": [],
        },
        "physical_signal_plan": {
            "enabled": True,
            "mapping": {"PHASE_A": "NS"},
            "phases": [
                {
                    "name": "NS",
                    "green_movements": ["N->S"],
                    "additional_movements": [],
                    "duration_s": 10.0,
                }
            ],
            "segments": [[0.0, 10.0, "NS"]],
        },
    }

    def fake_load_source(path):
        calls.append(("load_source", path.suffix))
        return tracks, ["input.json"]

    def fake_discover_records(records, *, input_name, dt):
        calls.append(("discover_records", len(records), dt))
        return result

    def fake_projection(records):
        calls.append(("projection", len(records)))
        return {"anchors": {"N": [0.5, 0.9]}}

    def fake_compact(
        records,
        *,
        analysis_base_timestamp_ms,
        display_base_timestamp_ms,
        projection,
    ):
        calls.append(
            (
                "compact",
                analysis_base_timestamp_ms,
                display_base_timestamp_ms,
            )
        )
        return [[1, "N", "N->S", [[0.0, 0.5, 0.9], [1.0, 0.5, 0.8]]]]

    def fake_render_html(result_arg, projection_arg, compact_arg, **kwargs):
        calls.append(("render", compact_arg, kwargs))
        return "<html><body>V10 OK</body></html>"

    monkeypatch.setattr("app.api.visualization.load_source", fake_load_source)
    monkeypatch.setattr(
        "app.api.visualization.discover_records",
        fake_discover_records,
    )
    monkeypatch.setattr(
        "app.api.visualization.build_spatial_projection",
        fake_projection,
    )
    monkeypatch.setattr(
        "app.api.visualization.compact_trajectories",
        fake_compact,
    )
    monkeypatch.setattr(
        "app.api.visualization.render_html",
        fake_render_html,
    )

    upload = UploadFile(
        file=BytesIO(b"{}"),
        filename="input.json",
    )
    response = asyncio.run(visualization_analyze(upload))

    assert response.status_code == 200
    assert response.body == b"<html><body>V10 OK</body></html>"
    assert calls[0] == ("load_source", ".json")
    assert ("discover_records", 1, 1.0) in calls
    assert ("projection", 1) in calls
    assert ("compact", 1000.0, 1000.0) in calls
    render_call = next(item for item in calls if item[0] == "render")
    assert render_call[2]["physical_plan"]["enabled"] is True
    assert render_call[2]["time_offset_s"] == 0.0
    assert render_call[2]["display_duration_s"] == 10.0
    run_dir = next((tmp_path / "logs").iterdir())
    assert (run_dir / "v9_result.json").exists()
    assert (run_dir / "physical_signal_plan_v10.json").exists()
    assert (run_dir / "signal_timeline_0.1s.jsonl").exists()
    assert (run_dir / "viewer.html").exists()
    assert (run_dir / "manifest.json").exists()
    assert render_call[2]["time_offset_s"] == 0.0
    assert render_call[2]["display_duration_s"] == 10.0
