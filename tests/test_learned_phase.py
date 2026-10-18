from copy import deepcopy
import inspect
import numpy as np
import pytest
from app.core.temporal_evidence import TemporalEvent
from app.core.learned_phase import fit_profile,predict_profile


def data(end=500):
    return [TemporalEvent(t*1000,'RELEASE','N->S' if t%100<40 else 'E->W',t,'test',.7,'MEDIUM',None,
        {'track_fingerprint':str(t),'source':'test'}) for t in range(0,end,2)]


def marks():
    return [{'kind':kind,'timestamp_ms':t*1000} for t,kind in [(0,'A'),(40,'B'),(100,'A'),(140,'B'),(200,'A'),(240,'B')]]


def test_training_does_not_use_events_after_cut():
    a=fit_profile(data(250),marks(),base_ms=0,period_s=100,train_start_ms=0,train_end_ms=250000)
    b=fit_profile(data(500),marks(),base_ms=0,period_s=100,train_start_ms=0,train_end_ms=250000)
    assert a==b
    with pytest.raises(ValueError,match='beyond cut'):
        fit_profile(data(),marks(),base_ms=0,period_s=100,train_start_ms=0,train_end_ms=200000)


def test_prediction_has_no_test_label_input_and_preserves_time():
    model=fit_profile(data(),marks(),base_ms=0,period_s=100,train_start_ms=0,train_end_ms=250000)
    before=deepcopy(model)
    result=predict_profile(data(),model,start_ms=300000,end_ms=500000)
    assert model==before
    assert 'marks' not in inspect.signature(predict_profile).parameters
    rows=result['schedule']['raw_hsmm_segments']
    assert rows[0][0]==0 and rows[-1][1]==200
    assert all(a[1]==b[0] for a,b in zip(rows,rows[1:]))
    assert result['learned_phase']['test_marks_received'] is False
    assert result['learned_phase']['phase_count_source']=='training_labels_NOT_automatic_discovery'


def test_prediction_abstains_without_observed_events():
    model=fit_profile(data(),marks(),base_ms=0,period_s=100,train_start_ms=0,train_end_ms=250000)
    with pytest.raises(ValueError,match='no supported prediction'):
        predict_profile([],model,start_ms=300000,end_ms=400000)


def test_120_second_clock_does_not_turn_into_a_100_second_clock_in_silence():
    # Uniform observation density gives no phase information. The declared
    # time prior alone must retain a 120s cycle, independently of training labels.
    model=dict(schema='learned-traffic-phase-v1',period_s=120.,channels=[['N->S','RELEASE']],
        profile=[[.01] for _ in range(100)],phase_onsets_bins=[0.,50.],phase_labels=['A','B'],
        training_range_ms=[0,1000])
    observed=[TemporalEvent(1000,'RELEASE','N->S',1,'test',.7,'MEDIUM',None,
        {'track_fingerprint':'1','source':'test'})]
    result=predict_profile(observed,model,start_ms=0,end_ms=360000)
    rows=result['schedule']['raw_hsmm_segments']
    internal=[r[1]-r[0] for r in rows[1:-1]]
    assert internal and all(duration==60 for duration in internal)
