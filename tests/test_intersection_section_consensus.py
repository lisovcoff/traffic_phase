from copy import deepcopy

import numpy as np
import pytest

from app.core.intersection_project import model_fingerprint
from app.experimental.intersection_timing_ensemble import TimingEnsembleIntersection
from app.experimental.intersection_adaptive_timing import AdaptiveRobustTimingIntersection
from tests.test_intersection_online import model,packet


def shared_main_model():
    m=model();r=m['regimes'][0]
    r.update(phase_count=3,phase_names=['A','B','C'],period_s=120,
             phase_durations={n:dict(median_s=40,p10_s=38,p90_s=42) for n in 'ABC'},
             observed_transitions=[dict(source=i,target=(i+1)%3,observations=10) for i in range(3)])
    r['phase_head_states']=[deepcopy(r['phase_head_states'][i]) for i in [0,0,1]]
    r['signal_topology']['N']['arrows']=['N->E']
    for i,state in enumerate(r['phase_head_states']):
        state['N']['arrows']=[dict(movement='N->E',state='ON' if i==0 else 'OFF')]
    r['movement_probabilities']={'N->S':[.8,.8,.01],'S->N':[.8,.8,.01],
                               'E->W':[.01,.01,.8],'W->E':[.01,.01,.8],'N->E':[.7,.01,.01]}
    m['fingerprint']=model_fingerprint(m)
    return m


def injected_posterior(*,recent=True,weak=False):
    e=TimingEnsembleIntersection(shared_main_model(),point_estimator='joint_state')
    for f in e.filters:
        f.green[0][:]=0;f.edge[0][:]=0
        if weak:
            f.green[0][0,10]=.30;f.green[0][1,10]=.25;f.green[0][2,10:19]=.05
        else:
            f.green[0][0,10]=.45;f.green[0][1,10]=.45;f.green[0][2,10]=.10
        f.evidence_ms=1000 if recent else None
    results=[f.summarize(1000,f.green,f.edge,f.evidence_ms) for f in e.filters]
    q={k:[] for k in ('restarts','passages','stops','braking')}
    return e,e._summarize({},results,q,{})


def test_shared_green_is_not_unknown_when_only_arrow_phase_is_ambiguous():
    e,r=injected_posterior()
    assert r['phase_confidence']<.5
    assert r['heads']['N']['main']['state']=='GREEN'
    assert r['heads']['N']['main']['confidence']==pytest.approx(.9)
    arrow=r['heads']['N']['arrows'][0]
    assert arrow['state']=='UNKNOWN' and arrow['confidence']==pytest.approx(.45)
    assert r['heads']['E']['main']['state']=='RED'
    assert r['section_consensus_recoveries']


def test_consensus_cannot_invent_a_color_without_recent_evidence_or_sufficient_mass():
    for options in (dict(recent=False),dict(weak=True)):
        _,r=injected_posterior(**options)
        assert r['heads']['N']['main']['state']=='UNKNOWN'
        assert not r['section_consensus_recoveries']


def test_consensus_fills_only_states_of_the_selected_joint_configuration():
    # OFF is the most likely arrow marginal, but the selected joint point has
    # ON. It must remain unknown rather than inventing a different configuration.
    _,r=injected_posterior(weak=True)
    assert r['heads']['N']['arrows'][0]['state']=='UNKNOWN'


def test_arrow_can_be_supported_across_competing_logical_phases():
    e,_=injected_posterior()
    for f in e.filters:
        for configuration in f.configurations:
            if configuration['N']['main']['state']=='GREEN':
                configuration['N']['arrows'][0]['state']='ON'
    results=[f.summarize(1000,f.green,f.edge,f.evidence_ms) for f in e.filters]
    q={k:[] for k in ('restarts','passages','stops','braking')}
    result=e._summarize({},results,q,{})
    arrow=result['heads']['N']['arrows'][0]
    assert result['phase_confidence']<.5
    assert arrow['state']=='ON' and arrow['confidence']==pytest.approx(.9)
    assert arrow['source']=='JOINT_TIMING_SECTION_CONSENSUS'


def test_projection_change_does_not_change_latent_inference_or_previously_known_states():
    a=AdaptiveRobustTimingIntersection(shared_main_model())
    b=AdaptiveRobustTimingIntersection(shared_main_model());b.SECTION_CONSENSUS_SUPPORT=1.1
    for s in range(15):
        x=a.ingest(packet(s));y=b.ingest(packet(s))
        np.testing.assert_array_equal(a.weights,b.weights)
        for f,g in zip(a.filters,b.filters):
            for u,v in zip(f.green+f.edge,g.green+g.edge):np.testing.assert_array_equal(u,v)
        for approach,head in y['heads'].items():
            if head['main']['state']!='UNKNOWN':assert x['heads'][approach]['main']['state']==head['main']['state']
        assert a.source.motion.tracks==b.source.motion.tracks
