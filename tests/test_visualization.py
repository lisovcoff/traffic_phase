from __future__ import annotations

import asyncio
import json
from io import BytesIO
import pytest

from fastapi import UploadFile

from app.api.visualization import visualization_analyze, visualization_page
from app.core.v9.signal_renderer import DEFAULT_ACTIVITY_THRESHOLD


def test_visualization_page_is_the_unified_v10_entrypoint():
    html = visualization_page()

    assert "V10 — Traffic Phase" in html
    assert "/visualization/analyze" in html
    assert 'accept=".json,.zip' in html
    assert "оценка фаз и движений" in html
    assert "По умолчанию показана оценка сигналов" in html
    assert "допсекциями" in html and "UNKNOWN" in html


@pytest.mark.parametrize('profile',['auto','lenina_sverdlovsky'])
def test_visualization_analyze_uses_canonical_spatial_builder(monkeypatch, tmp_path, profile):
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
    if profile!='auto':
        result['estimated_signals']={
            'available':True,'hardware_confirmed':True,'operating_phase_count':1,
            'observed_physical_state':'UNKNOWN',
            'topology':{'N':{'arrows':['N->E']},'E':{'arrows':['E->N']},
                        'W':{'arrows':[]},'S':{'arrows':[]}},
            'states':[{'name':'NS','heads':{'N':{'main':{'state':'GREEN'}}}}],
            'segments':[[0,10,0]]}

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
    response = asyncio.run(visualization_analyze(upload,intersection_profile=profile))

    assert response.status_code == 200
    assert response.body == b"<html><body>SPATIAL OK</body></html>"
    assert len(calls) == 1
    assert calls[0][0] == ".json"
    assert calls[0][1]["dt"] == 1.0
    assert calls[0][1]["yellow_duration_seconds"] == 3.0
    assert calls[0][1]["red_yellow_duration_seconds"] == 2.0
    assert calls[0][1]["activity_threshold"] == DEFAULT_ACTIVITY_THRESHOLD
    assert calls[0][1].get('intersection_profile','auto')==profile
    run_dir = next((tmp_path / "logs").iterdir())
    assert (run_dir / "v9_result.json").exists()
    assert (run_dir / "physical_signal_plan_v10.json").exists()
    assert (run_dir / "signal_timeline_0.1s.jsonl").exists()
    assert (run_dir / "viewer.html").exists()
    assert (run_dir / "manifest.json").exists()
    if profile!='auto':
        assert json.loads((run_dir/'estimated_signal_history.json').read_text(encoding='utf-8'))==result['estimated_signals']
        observed=json.loads((run_dir/'signal_timeline_0.1s.jsonl').read_text(encoding='utf-8').splitlines()[0])
        assert all(h['main']=='UNKNOWN' for h in observed['heads'].values())
        assert observed['heads']['N']['arrows']=={'N->E':'UNKNOWN'}
        assert observed['heads']['E']['arrows']=={'E->N':'UNKNOWN'}
        assert observed['heads']['W']['arrows']==observed['heads']['S']['arrows']=={}
