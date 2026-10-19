"""Validation infrastructure checks: physics, isolation, and honest metrics."""
import builtins
from copy import deepcopy
import io
import json
from pathlib import Path

import numpy as np
import pytest

from app.core.v9.events import _iter_json_records, load_event_streams
from scripts.corpus_validation import CorpusStats, inventory, predict_modes
from scripts.realistic_traffic_benchmark import (
    BASE_MS, generate, match_transitions, score_prediction, signal_at,
    movement_signal_plan,movement_color_at,signal_plan,
)


@pytest.fixture
def environment():
    return dict(vehicle_classes={'car':90,'bus':10},
        positive_raw_speed_quantiles=[20.,30.,40.,50.],
        detection_step_quantiles_s=[.11,.12,.13])


@pytest.fixture
def simulation(environment):
    return generate(dict(id='test',k=2,duration_s=360,period_s=80,
        arrival_rate_s=.08,seed=314159,all_red_s=1.),environment)


def test_stream_statistics_preserve_production_events(tmp_path, simulation):
    tracks,_=simulation
    path=tmp_path/'raw.json';path.write_text(json.dumps(tracks))
    named=load_event_streams(path)
    stats=CorpusStats(capacity=32)
    with path.open('rb') as stream:
        observed=load_event_streams(Path('records'),_records=stats.observe(_iter_json_records(stream)))
    # Adapter namespace differs deliberately; all actual timing/evidence must
    # remain equal to the production path's result.
    for a,b in zip(named.temporal_events,observed.temporal_events,strict=True):
        assert (a.timestamp_ms,a.event_type,a.movement,a.evidence_method)==(b.timestamp_ms,b.event_type,b.movement,b.evidence_method)
        pa,pb=deepcopy(a.provenance),deepcopy(b.provenance)
        pa.pop('source');pb.pop('source');assert pa==pb
    assert named[8:]==observed[8:]
    assert named.permission_streams==observed.permission_streams
    assert stats.tracks==len(tracks)
    assert stats.detections==sum(len(t['detections']) for t in tracks)
    assert all(len(v)<=32 for v in stats.samples.values())


def test_prediction_denies_video_and_evaluation_files(monkeypatch, simulation):
    tracks,_=simulation
    bundle=load_event_streams(Path('records'),_records=tracks)
    original_builtin,original_io=builtins.open,io.open
    denied=[]
    def wrap(original):
        def guarded(file,*args,**kwargs):
            name=str(file).replace('\\','/').lower()
            forbidden=(name.endswith(('.mp4','.avi','.mov')) or '/evidence/' in name or
                'manual_marks' in name or '/annotations/' in name or 'truth.json' in name)
            if forbidden:
                denied.append(name);raise AssertionError('evaluation/video access during prediction: '+name)
            return original(file,*args,**kwargs)
        return guarded
    monkeypatch.setattr(builtins,'open',wrap(original_builtin))
    monkeypatch.setattr(io,'open',wrap(original_io))
    rows=predict_modes(bundle,site='lenina_sverdlovsky')
    assert not denied
    assert rows and rows[0]['automatic']['status']=='ok'
    assert rows[0]['learned']['status']=='ok'
    assert rows[0]['learned']['count_source']=='operator_training_labels_NOT_automatic'


def test_simulation_physical_signal_precedes_vehicle_discharge(simulation):
    tracks,truth=simulation
    phase={movement:p for p,group in enumerate(truth['groups']) for movement in group}
    assert tracks and truth['counts']['detections']>10*len(tracks)
    assert any(t['stay_duration_millis']>=3000 for t in tracks)
    assert any(any(d['speed']==0 for d in t['detections']) for t in tracks)
    for row in truth['vehicle_crossings']:
        if row['crossing_s'] is not None:
            color,_=signal_at(truth['signal_plan'],phase[row['movement']],row['crossing_s'])
            assert color in ('GREEN','YELLOW')
    for track in tracks:
        assert not any('phase' in key or 'signal' in key or 'truth' in key for key in track)
        assert all(BASE_MS<=d['millis']<=BASE_MS+360000 for d in track['detections'])


def test_repeatability_and_missing_detections_do_not_change_signal_truth(environment):
    config=dict(id='test',k=3,duration_s=180,period_s=100,arrival_rate_s=.1,seed=99)
    a,ta=generate(config,environment);b,tb=generate(config,environment)
    assert a==b and ta==tb
    c,tc=generate({**config,'dropout':.4,'gap_s':4},environment)
    assert ta['signal_plan']==tc['signal_plan']
    assert sum(len(t['detections']) for t in c)<sum(len(t['detections']) for t in a)


def test_boundary_scoring_is_one_to_one_and_optimizes_match_count():
    score=match_transitions([0.,.1,10.],[0.,10.],.5)
    assert score['matched']==2 and score['precision']==pytest.approx(2/3)
    assert match_transitions([0.,1.],[.9,1.9],1.)['matched']==2
    assert match_transitions([],[],1.)['recall'] is None


def test_anonymous_labels_can_be_permuted_without_changing_scores(simulation):
    _,truth=simulation
    segments=[[max(0,r['start_s']),min(360,r['end_s']),1-r['phase']]
        for r in truth['signal_plan'] if r['end_s']>0 and r['start_s']<360]
    result=dict(analysis_base_timestamp_ms=BASE_MS,schedule=dict(phase_count=2,
        phase_names=['x','y'],period_s=80,raw_hsmm_segments=segments,stream_activity_by_phase=[
            dict(stream=s,event_probability_by_phase={'x':float(p==1),'y':float(p==0)})
            for p,group in enumerate(truth['groups']) for s in group]))
    score=score_prediction(result,truth)
    assert score['k_correct'] and score['phase_state_error_fraction']==0
    assert score['movement_assignment_accuracy']==1.
    assert score['transition_metrics']['0.5']['precision']==1.
    # Perfect phase labels alone do not give the production mapper a hardware
    # plan. Evaluator truth must not silently supply that missing input.
    assert score['production_main_heads']['mapping_available'] is False
    assert all(h['coverage_fraction']==0 for h in score['production_main_heads']['heads'].values())


def test_inventory_excludes_predictions_and_fixture_zips(tmp_path):
    import zipfile
    (tmp_path/'17_2025_2_12_7.json').write_text('[]')
    (tmp_path/'17_2025_2_12_7_review.json').write_text('{}')
    with zipfile.ZipFile(tmp_path/'road.zip','w') as z:z.writestr('6_2025_2_23_13.json','[]')
    with zipfile.ZipFile(tmp_path/'code.zip','w') as z:z.writestr('tests/fixture.json','[]')
    inv=inventory(tmp_path)
    assert len(inv['jobs'])==2 and len(inv['exclusions'])==1


def test_continuing_shared_main_has_no_yellow_at_arrow_change():
    plan=signal_plan(dict(seed=1,k=3,duration_s=300,period_s=100))
    runs=movement_signal_plan(plan,{0,1})
    row=next(r for r in plan if r['phase']==0 and r['start_s']>=0)
    assert movement_color_at(runs,row['end_s']-.5)[0]=='GREEN'
    assert movement_color_at(runs,row['end_s']+.5)[0]=='GREEN'
    last=next(r for r in plan if r['phase']==1 and r['cycle']==row['cycle'])
    assert movement_color_at(runs,last['green_end_s']+.1)[0]=='YELLOW'


def test_selected_window_cannot_be_scored_as_full_recording_success(simulation):
    _,truth=simulation
    result=dict(analysis_base_timestamp_ms=BASE_MS,schedule=dict(phase_count=2,
        phase_names=['x','y'],period_s=80,raw_hsmm_segments=[[90.,180.,0]],
        stream_activity_by_phase=[dict(stream=s.replace('_',''),event_probability_by_phase={
            'x':float(p==0),'y':float(p==1)}) for p,g in enumerate(truth['groups']) for s in g]))
    score=score_prediction(result,truth)
    assert score['evaluated_s']==360
    assert score['coverage_fraction']==.25
    assert score['phase_state_error_fraction']>=.75
    assert all(s['coverage_fraction']<=.25 for s in score['movement_colors'].values())


def test_video_brackets_match_once_and_use_interval_uncertainty():
    from scripts.validation_report import bracket_matches
    result=bracket_matches([1000.,1100.],[[900.,1050.]],100.)
    assert result['matched']==1 and result['precision']==.5
    assert result['pairs'][0]['distance_to_bracket_s']==0


def test_uturn_waits_inside_intersection_and_is_not_faked_into_straight_evidence(environment):
    from app.core.v9.vehicle_evidence import extract_vehicle_evidence
    tracks,truth=generate(dict(id='uturn',k=2,duration_s=900,period_s=100,arrival_rate_s=.2,
        seed=6902,uturn=True,realistic_turns=True),environment)
    uturns=[t for t in tracks if t['zone_in']=='E' and t['zone_out']=='_E']
    assert uturns
    assert any(any(d['zone']=='_E' and d['speed']==0 for d in t['detections']) for t in uturns)
    # Existing production semantics collapse E/_E as the same approach. Record
    # this as missing U-turn coverage rather than manufacturing a straight event.
    assert all(extract_vehicle_evidence(t)[0]==[] for t in uturns)


def test_bounded_zip_serializer_preserves_frozen_input_bytes(tmp_path,simulation):
    import zipfile
    from scripts.realistic_traffic_benchmark import write_tracks_zip
    tracks,_=simulation;target=tmp_path/'tracks.zip'
    write_tracks_zip(target,tracks)
    with zipfile.ZipFile(target) as archive:
        actual=archive.read('trajectories.json')
    expected=''.join(json.JSONEncoder(separators=(',',':')).iterencode(tracks)).encode()
    assert actual==expected


def test_normal_viewer_never_looks_up_reference_video_bias(tmp_path,simulation,monkeypatch):
    import app.core.learned_visualization as viewer
    import app.core.v10.timing_profiles as timing
    tracks,_=simulation;path=tmp_path/'cars.json';path.write_text(json.dumps(tracks))
    def forbidden(*args,**kwargs):raise AssertionError('video-derived source bias requested in normal inference')
    monkeypatch.setattr(timing,'resolve_timing_profile',forbidden)
    # Also catch an early imported alias, if it is reintroduced later.
    monkeypatch.setattr(viewer,'resolve_timing_profile',forbidden,raising=False)
    built=viewer.build_learned_visualization(path,model_id='lenina_sverdlovsky')
    result=built['result']
    assert result['learned_phase']['reference_video_timing_bias_applied'] is False
    assert result['estimated_signals']['transition_timing']['phase_boundary_calibration'] is None


def test_absent_traffic_allows_different_signal_plans_for_same_observations(environment):
    from scripts.realistic_traffic_benchmark import split_empty_phase
    tracks,truth=generate(dict(id='empty_witness',k=3,duration_s=360,period_s=100,
        arrival_rate_s=.1,seed=3903,starved=True),environment)
    before=json.dumps(tracks,sort_keys=True)
    alternate=split_empty_phase(truth)
    assert truth['config']['k']==3 and alternate['config']['k']==4
    for movement in {t['zone_in']+'->'+t['zone_out'] for t in tracks if t['zone_out']}:
        original_phases={i for i,g in enumerate(truth['groups']) if movement in g}
        alternate_phases={i for i,g in enumerate(alternate['groups']) if movement in g}
        a=movement_signal_plan(truth['signal_plan'],original_phases)
        b=movement_signal_plan(alternate['signal_plan'],alternate_phases)
        assert [movement_color_at(a,t)[0] for t in np.arange(0,360,.25)]==[
            movement_color_at(b,t)[0] for t in np.arange(0,360,.25)]
    assert json.dumps(tracks,sort_keys=True)==before
