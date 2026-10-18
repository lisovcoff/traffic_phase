import numpy as np
import pytest
from app.core.state_contract import prepare_logical_query
from app.core.v9.signal_renderer import build_signal_model,signal_state_at
from app.core.v10.semantic_mapping import signal_state_at as v10_state
from app.core.v9 import model


def prediction():
    return {'schedule':{'phase_names':['A','B'],'period_s':80,'phase_count':2,
        'raw_hsmm_segments':[[0,40,0],[40,80,1]],'baseline_segments':[[0,40,0],[40,80,1]],
        'stream_activity_by_phase':[{'stream':'m','event_probability_by_phase':{'A':.8,'B':.1}}]},
        'reconstruction_history':{'status':'ok','segments':[[0,5,1],[10,15,0]],
            'abstention_intervals':[[5,10,'NO_LOCAL_VEHICLE_EVIDENCE']]}}


def test_default_queries_preserve_accepted_raw_even_if_experimental_payload_exists():
    p=prediction()
    assert prepare_logical_query(p).at(7).estimated_state=='A'
    assert signal_state_at(p,7)['logical_phase']['estimated_state']=='A'
    assert v10_state(p,7,[],{})['logical_phase']['estimated_state']=='A'
    assert signal_state_at(p,7)['streams'][0]['state']=='UNKNOWN'


def test_explicit_experimental_selection_has_no_hidden_fallback():
    p=prediction();query=prepare_logical_query(p,history_source='experimental')
    assert query.at(2).estimated_state=='B'
    assert query.at(2).observation_support['experimental_validation_status']=='NOT_APPROVED'
    assert 'NOT_identified' in query.at(2).observation_support['support_interpretation']
    assert query.at(7).abstention_reason=='NO_LOCAL_VEHICLE_EVIDENCE'
    assert query.at(15).estimated_state=='UNKNOWN'
    m=build_signal_model(p,history_source='experimental')
    assert signal_state_at(m,7)['logical_phase']['estimated_state']=='UNKNOWN'
    with pytest.raises(ValueError,match='source differs'):
        signal_state_at(m,7,history_source='accepted')
    p['reconstruction_history']={'status':'unavailable','reason':'TIMEOUT','segments':[]}
    assert signal_state_at(p,7,history_source='experimental')['logical_phase']['abstention_reason']=='TIMEOUT'
    del p['reconstruction_history']
    assert signal_state_at(p,7,history_source='experimental')['logical_phase']['abstention_reason']=='EXPERIMENTAL_HISTORY_UNAVAILABLE'


@pytest.mark.parametrize('enabled',[False,True])
def test_actual_discovery_call_site_runs_local_decoder_only_on_optin(monkeypatch,enabled):
    fit={'labels':np.repeat([0,1,0],[20,20,23]),'probs':np.array([[.9,.1],[.1,.9]]),
         'segments':[(0.,20.,0),(20.,40.,1),(40.,63.,0)],'decoder_info':{}}
    monkeypatch.setattr(model,'infer_period',lambda *a:(40.,{}))
    monkeypatch.setattr(model,'discover_phase_count',lambda *a,**kw:(2,[{'k':2}],{2:fit}))
    seen=[]
    def local(*a,**kw):
        seen.append(True);return {'status':'unavailable','reason':'TEST','segments':[]}
    monkeypatch.setattr(model,'decode_local_history',local)
    streams={'a':[1.,2.,41.,42.],'b':[21.,22.,61.,62.]}
    kwargs={'experimental_local_history':True} if enabled else {}
    output=model._discover_from_stream_views(streams,streams,{},{},release_streams=streams,**kwargs)
    assert len(seen)==int(enabled)
    assert ('reconstruction_history' in output)==enabled


def test_public_discovery_defaults_are_disabled_and_forward_explicit_choice(monkeypatch,tmp_path):
    import json
    from tests.test_v9_source_scope import track
    # Keep real extraction/session selection: public discovery now attaches scope
    # to a result mapping, so the old tuple/bool doubles violated its contract.
    monkeypatch.setattr(model,'_discover_bundle',lambda bundle,**kwargs:
                        {'experimental_local_history':kwargs['experimental_local_history']})
    assert model.discover_records([track()])['experimental_local_history'] is False
    assert model.discover_records([track()],experimental_local_history=True)['experimental_local_history'] is True
    source=tmp_path/'source.json';source.write_text(json.dumps([track()]),encoding='utf-8')
    assert model.discover_path(source)['experimental_local_history'] is False
    assert model.discover_path(source,experimental_local_history=True)['experimental_local_history'] is True


@pytest.mark.parametrize('value',['false',1,None])
def test_accidental_truthy_values_cannot_enable_experiment(value):
    with pytest.raises(ValueError,match='explicit boolean'):
        model.discover_records([{}],experimental_local_history=value)
