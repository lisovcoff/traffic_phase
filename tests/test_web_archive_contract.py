import asyncio
from io import BytesIO
import json
import errno

import pytest
from fastapi import UploadFile, HTTPException

from app.api import visualization as api
from scripts.v9_spatial_visualizer import render_html, build_spatial_visualization


def model():
    return dict(schedule_base_timestamp_ms=6000, analysis_base_timestamp_ms=6000,
        recording_start_timestamp_ms=1000, recording_duration_s=30,
        schedule=dict(phase_names=['A','B'],phase_count=2,period_s=20,
            raw_hsmm_segments=[[0,10,0],[12,20,1]],baseline_segments=[[0,10,0],[10,20,1]],
            stream_activity_by_phase=[{'stream':'N->E','event_probability_by_phase':{'A':.9,'B':.1}}]))


def test_reconstructed_spatial_payload_uses_common_contract_and_distinct_anchor():
    page=render_html(model(),{},[])
    assert 'const RECONSTRUCTED = true' in page
    assert 'const HISTORY_OFFSET_S = 5.0;' in page
    assert 'const PHYSICAL = {"enabled":false' in page
    assert 'PHYSICAL_STATES_UNKNOWN_NOT_OBSERVED' in page


def test_assumed_plan_requires_explicit_mode():
    assert 'const RECONSTRUCTED = false' in render_html(model(),{},[],mode='configured')
    with pytest.raises(ValueError,match='invalid report mode'):
        render_html(model(),{},[],mode='unverified')


def test_invalid_zip_returns_422_not_internal_server_error():
    with pytest.raises(HTTPException) as caught:
        asyncio.run(api.visualization_analyze(UploadFile(file=BytesIO(b'bad zip'),filename='bad.zip')))
    assert caught.value.status_code==422


def test_no_disk_space_is_reported_explicitly(monkeypatch):
    def fail(*a,**k):raise OSError(errno.ENOSPC,'disk full')
    monkeypatch.setattr(api,'TemporaryDirectory',fail)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(api.visualization_analyze(UploadFile(file=BytesIO(b'[]'),filename='raw.json')))
    assert caught.value.status_code==507


@pytest.mark.parametrize('enabled',[False,True])
def test_existing_explicit_plan_fix_preserves_operator_input(monkeypatch,tmp_path,enabled):
    import scripts.v9_spatial_visualizer as module
    data=model();data['physical_signal_plan']={'enabled':True,'source':'auto'}
    plan={'enabled':enabled,'source':'operator'}
    source=tmp_path/'raw.json';source.write_text('[]')
    planpath=tmp_path/'plan.json';planpath.write_text(json.dumps(plan))
    monkeypatch.setattr(module,'discover_path',lambda *a,**kw:data)
    monkeypatch.setattr(module,'load_tracks',lambda *a,**kw:[])
    monkeypatch.setattr(module,'build_spatial_projection',lambda *a,**kw:{})
    monkeypatch.setattr(module,'compact_trajectories',lambda *a,**kw:[])
    monkeypatch.setattr(module,'render_html',lambda *a,**kw:json.dumps(kw['physical_plan']))
    built=build_spatial_visualization(source,physical_plan_path=planpath)
    assert built['physical_plan']==plan


def test_exported_timeline_does_not_publish_unverified_lamps(tmp_path):
    # Redirect only the logger, never a user's existing logs.
    from unittest.mock import patch
    with patch.object(api,'LOG_ROOT',tmp_path):
        folder=api._write_visualization_logs(run_id='test',input_name='fixture',result=model(),
            physical_plan={'enabled':True,'cycle_seconds':20,'stages':[
                {'name':'fake','phase_start':0,'phase_end':20,'heads':{'N':{'main':'GREEN'}}}]},
            html='',request_params={})
    rows=[json.loads(line) for line in (folder/'signal_timeline_0.1s.jsonl').read_text().splitlines()]
    assert rows[0]['phase']=='UNKNOWN'
    assert all(h['main']=='UNKNOWN' for row in rows for h in row['heads'].values())
    assert next(r for r in rows if r['video_time_s']==6)['phase']=='A'
    assert next(r for r in rows if r['video_time_s']==16)['phase']=='UNKNOWN'
