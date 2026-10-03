from __future__ import annotations

import asyncio
from io import BytesIO

from fastapi import UploadFile

from app.api.visualization import visualization_analyze, visualization_page
from app.core.v9.signal_renderer import DEFAULT_ACTIVITY_THRESHOLD


def test_visualization_page_is_the_unified_v10_entrypoint():
    html = visualization_page()

    assert "V10 — Traffic Phase" in html
    assert "/visualization/analyze" in html
    assert 'accept=".json,.zip' in html
    assert "V9 discovery" in html
    assert "V10 физическая семантика" in html


def test_visualization_analyze_uses_canonical_spatial_builder(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        "app.api.visualization.LOG_ROOT",
        tmp_path / "logs",
    )

    result = {
        "algorithm": "direction-agnostic traffic phase discovery V9",
        "trajectory_count": 1,
        "event_count": 1,
        "recording_duration_s": 10.0,
        "analysis_base_timestamp_ms": 1000.0,
        "recording_start_timestamp_ms": 1000.0,
        "schedule": {
            "period_s": 10.0,
            "phase_count": 1,
            "phase_names": ["PHASE_A"],
            "baseline_segments": [[0.0, 10.0, 0]],
        },
    }
    physical_plan = {
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
        "stages": [
            {
                "stage_id": 1,
                "name": "NS",
                "phase_start": 0.0,
                "phase_end": 10.0,
                "active_movements": ["N->S"],
                "heads": {
                    "N": {"main": "GREEN", "arrows": {}},
                    "S": {"main": "RED", "arrows": {}},
                    "E": {"main": "RED", "arrows": {}},
                    "W": {"main": "RED", "arrows": {}},
                },
            }
        ],
    }

    def fake_builder(path, **kwargs):
        calls.append((path.suffix, kwargs))
        return {
            "html": "<html><body>SPATIAL OK</body></html>",
            "result": result,
            "physical_plan": physical_plan,
            "projection": {"method": "test"},
            "rendered_trajectory_count": 1,
            "trajectory_count": 1,
        }

    monkeypatch.setattr(
        "app.api.visualization.build_spatial_visualization",
        fake_builder,
    )

    upload = UploadFile(
        file=BytesIO(b"{}"),
        filename="input.json",
    )
    response = asyncio.run(visualization_analyze(upload))

    assert response.status_code == 200
    assert response.body == b"<html><body>SPATIAL OK</body></html>"
    assert len(calls) == 1
    assert calls[0][0] == ".json"
    assert calls[0][1]["dt"] == 1.0
    assert calls[0][1]["yellow_duration_seconds"] == 3.0
    assert calls[0][1]["red_yellow_duration_seconds"] == 2.0
    assert calls[0][1]["activity_threshold"] == DEFAULT_ACTIVITY_THRESHOLD
    run_dir = next((tmp_path / "logs").iterdir())
    assert (run_dir / "v9_result.json").exists()
    assert (run_dir / "physical_signal_plan_v10.json").exists()
    assert (run_dir / "signal_timeline_0.1s.jsonl").exists()
    assert (run_dir / "viewer.html").exists()
    assert (run_dir / "manifest.json").exists()
