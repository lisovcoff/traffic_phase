import copy
import math
import numpy as np
import pytest

from app.core.temporal_evidence import TemporalEvent
from app.experimental.local_evidence import build_local_evidence
from app.experimental.joint_track_model import (
    infer_joint, observation_components, path_loglik, tracks_from_view, ModelUnavailable,
)


def spec(h=8):
    return {'horizon_s':h,'movements':['m0','m1'],'rates_per_s':[[.2,.03],[.03,.2]],
        'latent_demand_exposure':np.ones((2,h//2)).tolist(),'observation_windows_s':[[0,h+12]],
        'release_delay_s':[[0,1.]],'transit_delay_s':[[2,1.]],
        'release_detection_probability':.5,'crossing_detection_probability':.25,
        'release_method':'synthetic_release','crossing_method':'synthetic_crossing',
        'rate_source':'test generator','delay_source':'test generator',
        'initial_phase':0,'initial_phase_start_s':0,'observed_segment_count':4}


def view(patterns,h=8):
    events=[]
    for i,(release,crossing,movement) in enumerate(patterns):
        for ts,kind,method in [(release,'RELEASE','synthetic_release'),(crossing,'CROSSING_PROXY','synthetic_crossing')]:
            if ts is not None:
                events.append(TemporalEvent(ts,kind,movement,i,method,.5,'MEDIUM',None,
                    {'source':'test','track_fingerprint':str(i),'eligible_proxy':True}))
    return build_local_evidence(events,source_namespace='test').query(0,(h+12)*1000)


def test_joint_observed_pattern_normalizes_to_thinning_probability():
    patterns=[]
    for u in range(0,8000,2000):
        r,c=u+250,u+2250
        patterns.extend([(r,None,'m0'),(None,c,'m0'),(r,c,'m0')])
    c=observation_components(view(patterns),spec())
    np.testing.assert_allclose(c['q'].sum(axis=0),c['detected_probability'])
    np.testing.assert_allclose(c['detected_probability'],.625)


def test_counts_and_exposure_poisson_likelihood_matches_closed_form():
    c=observation_components(view([(250,None,'m0')]),spec())
    expected=-8*(.2+.03)*.625+math.log(.2*2*(.5*.75))
    assert path_loglik([0,0,0,0],c)==pytest.approx(expected)


def test_redundant_second_mark_does_not_double_vehicle_evidence():
    s=spec();s['release_detection_probability']=1;s['crossing_detection_probability']=.5
    one=observation_components(view([(250,None,'m0')]),s)
    pair=observation_components(view([(250,2250,'m0')]),s)
    np.testing.assert_allclose(one['q'],pair['q'])
    assert path_loglik([0,1,0,1],one)==path_loglik([0,1,0,1],pair)
    assert len(pair['tracks'])==1


def test_missing_crossing_at_window_edge_uses_censoring_probability():
    v=view([(6250,None,'m0')]);full=spec();cut=spec();cut['observation_windows_s']=[[0,8]]
    qfull=observation_components(v,full)['q'][0,-1]
    qcut=observation_components(v,cut)['q'][0,-1]
    assert qcut==pytest.approx(.5)
    assert qfull==pytest.approx(.5*.75)


def test_observed_event_in_supplied_gap_rejected():
    s=spec();s['observation_windows_s']=[[0,2],[4,20]]
    with pytest.raises(ModelUnavailable,match='OUTSIDE_SUPPLIED'):
        observation_components(view([(2250,None,'m0')]),s)


def test_permissive_positive_background_and_supplied_structural_zero():
    v=view([(250,None,'m0')]);s=spec();c=observation_components(v,s)
    assert math.isfinite(path_loglik([1,1,1,1],c))
    s['rates_per_s'][1][0]=0
    assert path_loglik([1,1,1,1],observation_components(v,s))==-math.inf


def test_duplicate_mark_and_unknown_track_identity():
    v=view([(250,2250,'m0')]);extra=copy.deepcopy(v);extra['events']+=copy.deepcopy(extra['events'])
    assert tracks_from_view(v,spec())==tracks_from_view(extra,spec())
    v['events'][0]['vehicle_group_id']=None
    with pytest.raises(ModelUnavailable,match='IDENTITY_UNKNOWN'): tracks_from_view(v,spec())


def test_multiple_incompatible_track_times_not_silently_chosen():
    v=view([(250,None,'m0')]);e=copy.deepcopy(v['events'][0]);e['event']['timestamp_ms']=2250;v['events'].append(e)
    with pytest.raises(ModelUnavailable,match='MULTIPLE_DISTINCT'): tracks_from_view(v,spec())


def test_wrong_method_or_off_grid_time_unavailable():
    v=view([(250,None,'m0')]);v['events'][0]['event']['evidence_method']='unvalidated_real_method'
    assert infer_joint(v,spec(18))['status']=='unavailable'
    v=view([(251,None,'m0')])
    assert 'DISCRETE_CLOCK' in infer_joint(v,spec(18))['reason']


@pytest.mark.parametrize('missing', ['rates_per_s','latent_demand_exposure','observation_windows_s','rate_source'])
def test_missing_metadata_abstains(missing):
    s=spec(18);s[missing]=None
    r=infer_joint(view([],18),s)
    assert not r['complete'] and r['status']=='unavailable'
    assert r['physical_section']['estimated_state']=='UNKNOWN'


def test_no_demand_and_no_observations_prior_only_and_unknown():
    for mode in ('zero-demand','missing-observation'):
        s=spec(18)
        if mode=='zero-demand': s['latent_demand_exposure']=np.zeros((2,9)).tolist()
        else: s['observation_windows_s']=[]
        r=infer_joint(view([],18),s)
        assert r['complete'] and r['prior_only_numerically']
        assert r['likelihood_range']==[0,0]
        assert r['logical_phase']['estimated_state']=='UNKNOWN'
        assert r['logical_phase']['level']=='logical_phase'
        assert r['physical_section']['calibrated_lamp_probability'] is None
        for p in r['results'].values(): assert p['posterior_vs_prior_kl_nats']==pytest.approx(0,abs=1e-12)


def test_batch_scores_match_scalar_reference_and_probabilities_normalize():
    s=spec(18);v=view([(250,2250,'m0'),(10250,None,'m1')],18)
    r=infer_joint(v,s);assert r['complete']
    c=observation_components(v,s)
    for p in r['results'].values():
        labels=[]
        for a,b,z in p['diagnostic_segments']:labels.extend([z]*((b-a)//2))
        assert p['map_log_likelihood']==pytest.approx(path_loglik(labels,c))
        for boundary in p['boundary_posteriors']:
            assert sum(boundary['posterior_mass'])==pytest.approx(1)
        np.testing.assert_allclose(np.asarray(p['phase_posterior']).sum(axis=1),1)


def test_renaming_and_input_immutability():
    s=spec(18);v=view([(250,2250,'m0'),(10250,None,'m1')],18)
    saved=copy.deepcopy((v,s));r=infer_joint(v,s)
    assert (v,s)==saved
    renamed=copy.deepcopy(v);ss=copy.deepcopy(s);ss['movements']=['turn-x','arbitrary-y']
    for e in renamed['events']:e['event']['movement']={'m0':'turn-x','m1':'arbitrary-y'}[e['event']['movement']]
    rr=infer_joint(renamed,ss)
    assert r['results']==rr['results']


@pytest.mark.parametrize('limits', [{'max_seconds':0},{'max_paths':0},{'max_tracks':0},
                                  {'max_q_cells':0},{'max_memory_bytes':0},{'max_seconds':float('nan')}])
def test_resource_exhaustion_never_returns_partial_posterior(limits):
    r=infer_joint(view([(250,None,'m0')],18),spec(18),**limits)
    assert r['status']=='unavailable' and not r['complete'] and not r['results']


def test_unknown_count_or_anchor_not_fabricated_and_no_truth_interface():
    for key in ('observed_segment_count','initial_phase','initial_phase_start_s'):
        s=spec(18);s[key]=None
        assert infer_joint(view([],18),s)['status']=='unavailable'
    with pytest.raises(TypeError): infer_joint(view([],18),spec(18),truth_segments=[])


def test_generator_repeatable_and_truth_separate_from_inference_input():
    from scripts.joint_track_suite import generate
    a=generate('stable_K2',2027);b=generate('stable_K2',2027)
    assert a==b
    assert set(a['inference_input'])=={'view','spec'}
    assert 'truth_segments' not in a['inference_input']
    assert 'durations_s' not in a['inference_input']['spec']
    assert len(a['truth_segments'])==4
    assert a['inference_input']['spec']['horizon_s']==38


def test_worker_never_reads_truth_and_evaluation_requires_seal(tmp_path,monkeypatch):
    import json
    from scripts import run_joint_track_experiment as runner
    inputs=[{'case':str(i),'seed':1,'inference_input':{'view':{},'spec':{}}} for i in range(2)]
    runner.write_json(tmp_path/'inputs.json',inputs)
    runner.write_json(tmp_path/'manifest.json',{'inputs_sha256':runner.sha256_file(tmp_path/'inputs.json'),
        'max_calls':24,'suite_cpu_s':60,'limits':{'max_seconds':5},'priors':{}})
    calls=[]
    def fake(**kwargs):
        assert set(kwargs)=={'view','spec','priors','max_seconds'}
        calls.append(kwargs)
        return {'status':'test_mock','cpu_s':0}
    monkeypatch.setattr(runner,'infer_joint',fake)
    runner.worker(tmp_path)
    assert len(calls)==2
    assert not (tmp_path/'suite.json').exists()
    with pytest.raises(ValueError,match='seal missing'): runner.evaluate(tmp_path,{'predictions':[]})
