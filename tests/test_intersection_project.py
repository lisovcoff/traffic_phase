from copy import deepcopy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import intersection_project as project
from tests.test_v9_source_scope import track,zip_bytes


def prediction(rotation=0,k=2):
    names=[f'PHASE_{chr(65+z)}' for z in range(k)]
    rows=[dict(stream=m,event_probability_by_phase={name:(.8 if (z+rotation)%k==phase else .01)
          for z,name in enumerate(names)}) for m,phase in [('N->S',0),('S->N',0),('E->W',1),('W->E',1)]]
    return dict(schedule=dict(phase_count=k,phase_names=names,period_s=80.,
        raw_hsmm_segments=[[0,40,0],[40,80,1],[80,120,0],[120,160,1]],
        baseline_segments=[[0,40,0],[40,80,1]],stream_activity_by_phase=rows))


def test_catalogue_aligns_rotated_labels_and_does_not_mutate_inputs():
    a,b=prediction(),prediction(1);before=deepcopy((a,b))
    result=project.build_catalogue([('one',a),('two',b)])
    assert len(result)==1 and result[0]['phase_count']==2
    assert result[0]['members'][1]['phase_mapping']=={'0':1,'1':0}
    assert result[0]['movement_probabilities']['N->S']==pytest.approx([.8,.01])
    assert (a,b)==before
    assert result[0]['online_structure_frozen']


def test_catalogue_keeps_different_counts_periods_and_signatures_separate():
    a,b,c,d=prediction(),prediction(k=3),prediction(),prediction()
    c['schedule']['period_s']=120
    for row in d['schedule']['stream_activity_by_phase']:
        row['event_probability_by_phase']={name:.2 for name in d['schedule']['phase_names']}
    assert len(project.build_catalogue([('a',a),('b',b),('c',c),('d',d)]))==4


def test_working_k_counts_unique_head_configurations_and_preserves_repeat_visits():
    from app.core.v10.automatic_physical import infer_physical_signal_plan
    names=['PHASE_A','PHASE_B','PHASE_C','PHASE_D']
    groups=[{'E->W','W->E'},{'N->S','S->N'},{'N->E','E->N'},{'N->S','S->N'}]
    value=dict(analysis_base_timestamp_ms=0,schedule_base_timestamp_ms=0,recording_start_timestamp_ms=0,
        schedule=dict(phase_count=4,phase_names=names,period_s=80,
            raw_hsmm_segments=[[0,20,0],[20,40,1],[40,60,2],[60,80,3]],
            baseline_segments=[[0,20,0],[20,40,1],[40,60,2],[60,80,3]],
            stream_activity_by_phase=[dict(stream=m,event_probability_by_phase={name:(.8 if m in group else .01)
                for name,group in zip(names,groups)}) for m in sorted(set.union(*groups))]))
    value['physical_signal_plan']=infer_physical_signal_plan(value);before=deepcopy(value)
    template=project.operating_template(value)
    assert value==before and template['latent_phase_count']==4
    assert template['schedule']['phase_count']==3
    phases=[z for a,b,z in template['schedule']['raw_hsmm_segments']]
    assert phases[1]==phases[3] and len(set(phases))==3
    catalogue=project.build_catalogue([('one',template),('two',template)])
    assert len(catalogue)==1 and catalogue[0]['phase_count']==3
    assert catalogue[0]['observed_transitions']


def test_all_zip_sources_and_sessions_are_processed_without_choice(tmp_path):
    source=tmp_path/'renamed.zip'
    source.write_bytes(zip_bytes([('a.json',[track(),track(2,start=86401000)]),
                                  ('b.json',[track(origin='E',target='_W')])]))
    calls=[]
    def fitter(bundle,**kwargs):
        calls.append(bundle)
        assert len({e.provenance['source'] for e in bundle.temporal_events})==1
        assert max(e.timestamp_ms for e in bundle.temporal_events)-min(e.timestamp_ms for e in bundle.temporal_events)<10000
        assert kwargs['input_name']=='intersection trajectory archive'
        return prediction()
    model=project.run_project(source,tmp_path/'project',predictor=fitter)
    assert len(calls)==3 and len(model['sessions'])==3
    assert model['completeness']=='COMPLETE'
    assert model['observed_approach_count']==4
    assert len({s['session_id'] for s in model['sessions']})==3
    assert model['known_hardware_profile_used'] is False
    assert model['input']['source_count']==2
    restored=project.read_json(tmp_path/'project/model.json')
    assert restored==model
    for session in model['sessions']:
        _,_,value=project.load_prediction(tmp_path/'project',session['session_id'])
        assert value['input_scope']['selected_session']['source_member']==session['source_member']


def test_failed_source_kept_as_partial_and_metadata_not_used(tmp_path):
    import zipfile
    source=tmp_path/'mixed.zip'
    with zipfile.ZipFile(source,'w') as archive:
        archive.writestr('good.json',json.dumps([track()]))
        archive.writestr('marks.json',json.dumps({'marks':[{'kind':'GREEN','timestamp_ms':1}]}))
        archive.writestr('broken.json','[{broken')
    model=project.run_project(source,tmp_path/'out',predictor=lambda *a,**kw:prediction())
    assert model['completeness']=='PARTIAL'
    assert len(model['sessions'])==1
    statuses={s['source_member']:s['status'] for s in model['source_inventory']}
    assert statuses=={'broken.json':'FAILED','good.json':'READY','marks.json':'SKIPPED_NON_TRAJECTORY_JSON'}


@pytest.mark.parametrize('zipped',[False,True])
def test_metadata_only_upload_has_actionable_failure_without_running_inference(tmp_path,zipped):
    source=tmp_path/('input.zip' if zipped else 'feed_manifest.json')
    metadata=dict(source='source-sha',member='recording.json',start_ms=1000,end_ms=61000,packets=61,future_fields=False)
    if zipped:
        source.write_bytes(zip_bytes([('feed_manifest.json',metadata)]))
    else:
        source.write_text(json.dumps(metadata),encoding='utf8')
    def unexpected_fit(*args,**kwargs):
        pytest.fail('metadata must never reach inference')
    with pytest.raises(ValueError,match='No session'):
        project.run_project(source,tmp_path/'out',predictor=unexpected_fit)
    status=project.read_json(tmp_path/'out/status.json')
    assert status['status']=='FAILED' and status['reason_code']=='NON_TRAJECTORY_INPUT'
    assert 'original vehicle JSON or ZIP' in status['user_message']
    assert status['sources_done']==1 and status['sessions_done']==0
    assert not (tmp_path/'out/model.json').exists()


def test_corrupt_json_is_not_reported_as_metadata(tmp_path):
    source=tmp_path/'broken.json';source.write_text('[{broken',encoding='utf8')
    with pytest.raises(ValueError,match='No session'):
        project.run_project(source,tmp_path/'out')
    status=project.read_json(tmp_path/'out/status.json')
    assert status['sources'][0]['status']=='FAILED'
    assert 'reason_code' not in status
    assert status['errors']


def test_persistent_prediction_checksum_is_checked(tmp_path):
    source=tmp_path/'input.json';source.write_text(json.dumps([track()]))
    model=project.run_project(source,tmp_path/'out',predictor=lambda *a,**kw:prediction())
    session=model['sessions'][0];stored=tmp_path/'out'/session['prediction']
    stored.write_bytes(stored.read_bytes()+b'x')
    with pytest.raises(ValueError,match='checksum'):
        project.load_prediction(tmp_path/'out',session['session_id'])
    with pytest.raises(ValueError,match='already exists'):
        project.run_project(source,tmp_path/'out')


def test_job_api_saves_and_restores_model_without_human_profile(monkeypatch,tmp_path):
    from app.api import intersection_projects as api
    from app.main import app
    class Inline:
        def submit(self,fn,source,folder):
            project.run_project(source,folder,predictor=lambda *a,**kw:prediction())
    monkeypatch.setattr(api,'PROJECT_ROOT',tmp_path)
    monkeypatch.setattr(api,'_executor',Inline())
    with TestClient(app) as client:
        response=client.post('/api/v1/intersections',files={'file':('named.json',json.dumps([track()]))})
        assert response.status_code==202,response.text
        identifier=response.json()['model_id']
        status=client.get(f'/api/v1/intersections/{identifier}').json()
        assert status['status']=='READY' and status['input_name']=='named.json'
        model=client.get(f'/api/v1/intersections/{identifier}/model').json()
        assert 'input_path_private' not in model
        assert model['offline_structure_frozen']
        assert client.get('/api/v1/intersections/not-a-path/model').status_code==404
        assert client.post('/api/v1/intersections',files={'file':('bad.txt','bad')}).status_code==400


def test_project_body_budget_prevents_multipart_spooling():
    import asyncio
    from app.core.upload_limits import UploadLimitMiddleware,PROJECT_REQUEST_BYTES
    messages=[]
    async def downstream(*args):pytest.fail('oversized body must not reach parser')
    async def receive():pytest.fail('oversized declared body must not be read')
    async def send(message):messages.append(message)
    asyncio.run(UploadLimitMiddleware(downstream)({'type':'http','method':'POST','path':'/api/v1/intersections',
        'headers':[(b'content-length',str(PROJECT_REQUEST_BYTES+1).encode())]},receive,send))
    assert messages[0]['status']==413


def t_prediction():
    from app.core.v10.automatic_physical import infer_physical_signal_plan
    value=prediction()
    value.update(analysis_base_timestamp_ms=0,schedule_base_timestamp_ms=0,recording_start_timestamp_ms=0)
    for row in value['schedule']['stream_activity_by_phase']:
        row['stream']={'E->W':'E->N','W->E':'N->E'}.get(row['stream'],row['stream'])
    value['physical_signal_plan']=infer_physical_signal_plan(value)
    return value


def test_observed_t_geometry_removes_ghost_leg_and_uses_supported_main():
    from app.core.observed_topology import project_observed_topology
    value=t_prediction();original=deepcopy(value)
    projected=project_observed_topology(value,['N','S','E'])
    assert value==original
    template=project.operating_template(projected)
    assert set(template['signal_topology'])=={'N','S','E'}
    assert template['signal_topology']['E']['main']=='E->N'
    assert 'E->N' not in template['signal_topology']['E']['arrows']
    assert all(set(h)=={'N','S','E'} for h in template['phase_head_states'])
    assert {h['E']['main']['state'] for h in template['phase_head_states']}=={'GREEN','RED'}
    assert not projected['intersection_geometry']['physical_absence_certified']


def test_four_approach_projection_preserves_numeric_fit_and_existing_hardware():
    from app.core.observed_topology import project_observed_topology
    value=t_prediction()
    projected=project_observed_topology(value,['N','S','E','W'])
    assert projected['schedule']==value['schedule']
    assert projected['physical_signal_plan']==value['physical_signal_plan']


def test_exit_only_t_leg_does_not_invent_main_permission():
    from app.core.observed_topology import project_observed_topology
    value=t_prediction()
    value['schedule']['stream_activity_by_phase']=[row for row in value['schedule']['stream_activity_by_phase']
        if not row['stream'].startswith('E->')]
    projected=project_observed_topology(value,['N','S','E'])
    assert not projected['physical_signal_plan']['enabled']


def test_archive_approach_union_is_used_instead_of_one_sparse_record(tmp_path):
    source=tmp_path/'sparse.zip'
    source.write_bytes(zip_bytes([('first.json',[track()]),('second.json',[track(origin='E',target='_W')])]))
    value=t_prediction()
    model=project.run_project(source,tmp_path/'out',predictor=lambda *a,**kw:deepcopy(value))
    assert model['approaches']==['N','S','E','W']
    assert all(set(r['signal_topology'])=={'N','S','E','W'} for r in model['regimes'])


@pytest.mark.parametrize('rotation',range(4))
def test_t_signature_keeps_two_states_in_all_rotations(rotation):
    from app.core.observed_topology import project_observed_topology
    from app.core.v10.automatic_physical import infer_physical_signal_plan
    order='NESW';mapping={a:order[(i+rotation)%4] for i,a in enumerate(order)}
    value=t_prediction()
    for row in value['schedule']['stream_activity_by_phase']:
        row['stream']='->'.join(mapping[a] for a in row['stream'].split('->'))
    value['physical_signal_plan']=infer_physical_signal_plan(value)
    projected=project_observed_topology(value,[mapping[a] for a in ['N','S','E']])
    template=project.operating_template(projected)
    assert template['schedule']['phase_count']==2
    assert set(template['signal_topology'])=={mapping[a] for a in ['N','S','E']}
    assert template['signal_topology'][mapping['E']]['main']==mapping['E']+'->'+mapping['N']


def test_inherited_empty_turn_phase_is_not_erased_by_hardware_projection():
    from app.core.observed_topology import project_observed_topology
    from app.core.v10.automatic_physical import infer_physical_signal_plan
    groups=[{'N->S','S->N'},{'N->E','E->N'},{'E->W','W->E'}]
    value=prediction(k=3);s=value['schedule'];names=s['phase_names']
    s['raw_hsmm_segments']=s['baseline_segments']=[[0,25,0],[25,50,1],[50,80,2]]
    s['stream_activity_by_phase']=[dict(stream=m,event_probability_by_phase={n:(.15 if m in g else .01)
        for n,g in zip(names,groups)}) for m in sorted(set.union(*groups))]
    value.update(analysis_base_timestamp_ms=0,schedule_base_timestamp_ms=0,recording_start_timestamp_ms=0)
    value['physical_signal_plan']=infer_physical_signal_plan(value);original=deepcopy(value)
    assert project.operating_template(value)['schedule']['phase_count']==2
    old=project_observed_topology(value,['N','S','E','W'])
    assert old['physical_signal_plan']==value['physical_signal_plan']
    new=project_observed_topology(value,['N','S','E','W'],repair_missing_phases=True)
    assert project.operating_template(new)['schedule']['phase_count']==3
    assert new['physical_signal_plan']['projection_repair']['resolved_inherited_phases']==['PHASE_B']
    assert value==original


def test_restart_age_prior_is_learned_only_from_offline_events(tmp_path):
    value=prediction();value['schedule_base_timestamp_ms']=0
    value['event_extraction']=dict(temporal_events=[dict(event_type='RELEASE',movement='N->S',timestamp_ms=s*1000)
        for s in range(1,12)])
    source=tmp_path/'input.json';source.write_text(json.dumps([track()]))
    result=project.run_project(source,tmp_path/'out',predictor=lambda *a,**kw:deepcopy(value))
    r=result['regimes'][0];hist=r['restart_age_histograms']['N->S']
    assert hist[0][0]>hist[0][-1] and hist[1]==[1.]*16
    assert r['restart_age_samples']['N->S']==[11,0]
    assert not result['annotations_used'] and not result['video_used']


def test_explicit_prepared_source_adapter_preserves_product_model(tmp_path):
    from app.core.v9.events import load_event_streams
    from app.core.recovery.motion import extract_motion_evidence
    source=tmp_path/'input.json';record=track()
    source.write_text(json.dumps([record]),encoding='utf8')
    raw=project.run_project(source,tmp_path/'raw',predictor=lambda *a,**kw:prediction())
    def loader(path,selected):
        assert path==source.resolve() and selected['source_member']=='input.json'
        bundle=load_event_streams(path,source_member=selected['source_member'],_event_extractor=extract_motion_evidence)
        points=[{k:d.get(k) for k in ('millis','centroid_x','centroid_y','zone')} for d in record['detections']]
        return bundle,dict(record_counts=dict(trajectory_records=1,detections=2),samples={'N':[
            dict(zone_in='N',zone_out='_S',detections=points)]})
    prepared=project.run_project(source,tmp_path/'prepared',predictor=lambda *a,**kw:prediction(),_source_loader=loader)
    for value in (raw,prepared):
        value.pop('model_id');value.pop('fingerprint')
    assert prepared==raw
