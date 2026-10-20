from copy import deepcopy

import numpy as np

from app.core.intersection_emissions import MovementMarks
from app.core.intersection_online import CausalIntersection
from tests.test_intersection_online import model


def test_panel_uses_current_backend_engine_and_preserves_explicit_history():
    from app.api.intersection_panel import PAGE
    from app.core.intersection_engine import VERSION
    assert 'const ONLINE_ENGINE="'+VERSION+'";' in PAGE
    assert "!SUPPORTED_ENGINES.includes(state.engine)&&!explicitHistory" in PAGE
    assert 'causal-intersection-v7' in PAGE
    assert "state.engine!=='causal-intersection-v4'" not in PAGE


def test_online_renderer_accepts_current_and_historical_schemas():
    import json
    import re
    from scripts.v9_spatial_visualizer import render_html
    from app.core.intersection_engine import VERSION
    from tests.test_intersection_project import prediction
    page=render_html(prediction(),{'matrix':[[1,0,0],[0,1,0],[0,0,1]]},[],intersection_profile='none',online_mode=True)
    schemas=json.loads(re.search(r'const SUPPORTED_ONLINE_SCHEMAS = (.*);',page).group(1))
    assert VERSION in schemas and 'causal-intersection-v4' in schemas
    assert 'causal-intersection-v999' not in schemas
    assert 'SUPPORTED_ONLINE_SCHEMAS.includes(value.schema)' in page


def test_shared_alphabet_and_probability_mass_conservation():
    narrow=dict(phase_count=2,movement_probabilities={'N->S':[.8,.01],'E->W':[.01,.8]})
    broad=dict(phase_count=2,movement_probabilities={'N->S':[.8,.8],'E->W':[.8,.8]})
    marks=MovementMarks([narrow,broad])
    for matrix in marks.distributions:assert np.allclose(matrix.sum(axis=0),1)
    assert marks.likelihoods('N','S')[0][0]>marks.likelihoods('N','S')[1][0]
    assert marks.likelihoods('E','W')[0][0]<marks.likelihoods('E','W')[1][0]


def test_unknown_destination_is_marginalized_and_missing_mark_is_finite():
    regimes=[dict(phase_count=2,movement_probabilities={'N->_S':[.8,.01],'N->_E':[.2,.5]}),
             dict(phase_count=3,movement_probabilities={'E->W':[.8,.01,.01]})]
    marks=MovementMarks(regimes)
    for unknown,straight,turn in zip(marks.likelihoods('N',None),marks.likelihoods('N','S'),marks.likelihoods('N','E')):
        assert np.allclose(unknown,straight+turn)
        assert np.all(np.isfinite(unknown)) and np.all(unknown>0)


def test_normalization_is_invariant_to_alphabet_order_and_phase_permutation():
    m=model();r=m['regimes'][0];other=deepcopy(r)
    other['movement_probabilities']={name:list(reversed(values)) for name,values in reversed(list(r['movement_probabilities'].items()))}
    marks=MovementMarks([r,other])
    for a,b in [('N','S'),('S',None),('E','W')]:
        one,two=marks.likelihoods(a,b)
        assert np.allclose(one,two[::-1])


def test_duration_forecast_does_not_revert_yellow_to_green_on_expiry():
    engine=CausalIntersection(model());engine.banks[0][:]=0;engine.banks[0][0,38]=1
    engine.evidence_ms=0
    colors=[]
    for second in range(5):
        result=engine.ingest(dict(sequence=second,timestamp_ms=second*1000,vehicles=[]))
        colors.append(result['heads']['N']['main']['state'])
    assert colors[0]=='YELLOW'
    assert 'RED' in colors and 'GREEN' not in colors


def test_section_does_not_disappear_when_program_without_observations_wins():
    m=model();other=deepcopy(m['regimes'][0]);other['regime_id']='rare_program'
    other['signal_topology']['N']['arrows']=['N->E']
    for h in other['phase_head_states']:h['N']['arrows']=[dict(movement='N->E',state='RED')]
    m['regimes'].append(other);engine=CausalIntersection(m)
    engine.banks[1][:]=0
    r=engine.ingest(dict(sequence=0,timestamp_ms=0,vehicles=[]))
    assert r['regime_id']=='regime_001'
    assert [a['movement'] for a in r['heads']['N']['arrows']]==['N->E']
    assert r['heads']['N']['arrows'][0]['state']=='UNKNOWN'


def test_duration_learning_requires_repeated_distinct_positive_evidence():
    from app.core.intersection_durations import DurationLearning
    m=model();saved=deepcopy(m);engine=CausalIntersection(m);clock=0
    learning=DurationLearning(engine.medians)
    for index in range(8):
        phase=index%2;engine.banks[0][:]=0;engine.banks[0][phase,1]=1
        events=[('N' if phase==0 else 'E',None,1.)]
        learning.observe(engine,events,clock*1000)
        if index<5:assert engine.medians[0]==[40.,40.]
        clock+=50 if phase==0 else 30
    assert engine.medians[0][0]>40 and engine.medians[0][1]<40
    assert m==saved
    before=deepcopy(engine.medians)
    learning.observe(engine,[],1000000)
    assert engine.medians==before
    learning.reset_observations()
    assert all(row is None for row in learning.last)
