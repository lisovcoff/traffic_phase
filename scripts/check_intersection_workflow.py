"""Cold real-archive HTTP job, persistent model, and cached-prediction viewer."""
from pathlib import Path
import json
import re
import time
from unittest.mock import patch

from scripts.corpus_validation import ROOT,save,prepare_worker_environment
prepare_worker_environment()


def main(output=None):
    from fastapi.testclient import TestClient
    from app.main import app
    inventory=json.loads((ROOT/'evidence/all_archives_synthetic_20261019/inventory.json').read_text(encoding='utf8'))
    job=next(j for j in inventory['jobs'] if j['id']=='0091')
    source=Path(job['path']);out=Path(output) if output is not None else ROOT/'evidence/intersection_project_20261019/real_archive'
    out.mkdir(parents=True,exist_ok=False)
    begin=time.monotonic();previous=None;health=[]
    with TestClient(app) as client:
        with source.open('rb') as stream:
            response=client.post('/api/v1/intersections',files={'file':(source.name,stream,'application/zip')})
        assert response.status_code==202,response.text
        identifier=response.json()['model_id'];save(out/'job.json',response.json())
        while time.monotonic()-begin<1200:
            state=client.get(f'/api/v1/intersections/{identifier}').json()
            progress=(state['status'],state.get('stage'),state.get('sources_done'),state.get('current_source'))
            if progress!=previous:print(progress,flush=True);previous=progress
            tick=time.monotonic();assert client.get('/health').status_code==200;health.append(time.monotonic()-tick)
            if state['status'] in ('READY','PARTIAL','FAILED'):break
            time.sleep(1)
        assert state['status']=='READY',state
        model=client.get(f'/api/v1/intersections/{identifier}/model').json()
        assert model['input']['source_count']==3 and len(model['sessions'])==3
        assert model['known_hardware_profile_used'] is False
        assert model['annotations_used'] is False and model['video_used'] is False
        assert model['offline_structure_frozen'] is True
        save(out/'public_model.json',model);save(out/'status.json',state)
        session=model['sessions'][0]['session_id']
        with patch('scripts.v9_spatial_visualizer.discover_path',side_effect=AssertionError('viewer refitted model')):
            viewer=client.get(f'/api/v1/intersections/{identifier}/sessions/{session}/viewer')
        assert viewer.status_code==200,viewer.text[:1000]
        estimate=json.loads(re.search(r'^const ESTIMATED_SIGNALS = (.*);$',viewer.text,re.M).group(1))
        assert estimate['profile_id'] is None and not estimate['hardware_confirmed']
        (out/'viewer.html').write_bytes(viewer.content)
        panel=client.get('/visualization');assert panel.status_code==200
        (out/'panel.html').write_bytes(panel.content)
    with TestClient(app) as client:
        restored=client.get(f'/api/v1/intersections/{identifier}/model').json()
        assert restored==model
    save(out/'receipt.json',dict(status='PASS',model_id=identifier,whole_original_zip=True,
        input=str(source),input_bytes=source.stat().st_size,sources=3,sessions=3,regimes=len(model['regimes']),
        k=[r['phase_count'] for r in model['regimes']],profile_used=False,video_used=False,
        human_phase_labels=False,persistent_restore=True,viewer_refit=False,
        max_health_response_s=max(health),runtime_s=time.monotonic()-begin,
        ready_url=f'http://127.0.0.1:8017/visualization?project={identifier}'))
    print('whole archive PASS',identifier,'seconds',time.monotonic()-begin,flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path)
    main(parser.parse_args().output)
