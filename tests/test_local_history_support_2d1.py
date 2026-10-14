import numpy as np
import pytest
from app.core.v9.decoder import decode_local_history, decode_cyclic_hsmm, LocalHistoryConfig
from app.core.state_contract import prepare_logical_query


def test_identical_emissions_do_not_turn_prior_into_observed_history():
    history=decode_local_history(np.ones((80,1)),np.array([[.5],[.5]]),80.,[40,40])
    assert history['segments']==[] and history['status']=='unavailable'
    assert history['reason']=='NO_IDENTIFIABLE_LOCAL_EVIDENCE'
    assert history['abstention_intervals']==[[0.,80.,'NON_IDENTIFIABLE_PHASE_EMISSIONS']]


def test_deadline_is_enforced_inside_decoder():
    with pytest.raises(TimeoutError):
        decode_cyclic_hsmm(np.eye(2)[np.tile([0,1],40)],np.array([[.9,.1],[.1,.9]]),80.,2,
                           initial_phase=0,deadline_monotonic=0.)


def test_new_history_cannot_assert_support_and_abstention_at_same_time():
    pred={'schedule':{'phase_names':['A','B']},'reconstruction_history':{
        'segments':[[0,10,0]],'abstention_intervals':[[5,15,'UNKNOWN_SUPPORT']]}}
    assert prepare_logical_query(pred,history_source="experimental").validation_error=='CONTRADICTORY_OBSERVATION_SUPPORT'


@pytest.mark.parametrize('kwargs',[{'max_seconds':float('inf')},{'max_bins':-1},{'duration_min_factor':0}])
def test_invalid_resource_contract_is_rejected(kwargs):
    with pytest.raises(ValueError):LocalHistoryConfig(**kwargs)


@pytest.mark.parametrize('hold',[10,30])
def test_uncompensated_hold_has_only_the_generated_delay_not_a_fitted_global_offset(hold):
    durations=[40,40,40+hold,40,40,40,40,40]
    truth=np.cumsum([0]+durations)
    labels=np.repeat(np.tile([0,1],4),durations)
    history=decode_local_history(np.eye(2)[labels],np.array([[.98,.02],[.02,.98]]),80.,[40,40])
    recovered=[s[0] for s in history['segments'][1:]]
    assert np.max(np.abs(np.array(recovered)-truth[1:-1]))<=1
    assert recovered[:2]==[40.,80.]
    assert np.diff(recovered[-4:]).tolist()==[40.,40.,40.]


def test_no_unavailable_history_can_secretly_supply_a_phase():
    result={'schedule':{'phase_names':['A','B']},'reconstruction_history':{
        'status':'unavailable','reason':'TIMEOUT','segments':[[0,80,0]]}}
    assert prepare_logical_query(result,history_source="experimental").at(30).abstention_reason=='INVALID_PHASE_HISTORY'


def test_default_decoder_equals_all_observed_legacy_path():
    x=np.eye(2)[np.repeat([0,1],40)];templates=np.array([[.9,.1],[.1,.9]])
    default=decode_cyclic_hsmm(x,templates,80.,2,initial_phase=0)
    explicit=decode_cyclic_hsmm(x,templates,80.,2,initial_phase=0,
        observation_mask=np.ones(80,dtype=bool),duration_penalty_strength=2.)
    assert np.array_equal(default[0],explicit[0]) and default[1:]==explicit[1:]


def test_reconstruction_worker_rejects_annotations_before_open(tmp_path,monkeypatch):
    from scripts.local_history_2d1 import reconstruct_frozen
    from pathlib import Path
    source=tmp_path/'record.json_manual_marks.json'
    monkeypatch.setattr(Path,'read_text',lambda *a,**k:pytest.fail('label file was read'))
    with pytest.raises(ValueError,match='annotation files are forbidden'):
        reconstruct_frozen(source,tmp_path/'output.json')
