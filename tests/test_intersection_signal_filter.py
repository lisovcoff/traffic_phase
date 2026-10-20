from copy import deepcopy
import numpy as np
import pytest

from app.core.intersection_signal_filter import JointSignalFilter,CoherentIntersection,TransitionPrior,transition_heads
from tests.test_intersection_online import model,packet


def test_explicit_transition_has_yellow_red_and_red_yellow_without_median_override():
    m=model();f=JointSignalFilter(m);f.green[0][:]=0;f.green[0][0,10]=1;f.edge[0][:]=0
    f.hazards[0][:]=0;f.hazards[0][0,10]=1
    f.last_ms=0;f.evidence_ms=0
    colors=[]
    for s in range(1,6):
        r=f.tick(s*1000,[]);colors.append((r['heads']['N']['main']['state'],r['heads']['E']['main']['state']))
        assert sum(g.sum()+e.sum() for g,e in zip(f.green,f.edge))==pytest.approx(1,abs=1e-10)
    assert colors==[('YELLOW','RED'),('YELLOW','RED'),('YELLOW','RED_YELLOW'),('RED','RED_YELLOW'),('RED','GREEN')]


def test_continuing_green_survives_arrow_only_change():
    a={'N':dict(main=dict(state='GREEN'),arrows=[dict(movement='N->E',state='ON')])}
    b={'N':dict(main=dict(state='GREEN'),arrows=[dict(movement='N->E',state='OFF')])}
    for second in range(4):
        h=transition_heads(a,b,second,TransitionPrior())
        assert h['N']['main']['state']=='GREEN' and h['N']['arrows'][0]['state']=='OFF'


def test_no_demand_or_long_gap_is_unknown_not_observed_red():
    f=JointSignalFilter(model())
    assert all(h['main']['state']=='UNKNOWN' for h in f.tick(0,[])['heads'].values())
    f.tick(1000,[('N','S',1.)])
    out=f.tick(1000000,[])
    assert out['status']=='AWAITING_EVIDENCE'
    assert all(h['main']['state']=='UNKNOWN' for h in out['heads'].values())


def test_joint_filter_has_no_point_of_forced_red_at_the_nominal_median():
    f=JointSignalFilter(model());f.green[0][:]=0;f.green[0][0,38]=1
    # Old forty-second phase median is passed while this green hypothesis has
    # explicitly not transitioned; colors must come from it, not another timer.
    f.hazards[0][:]=0;f.last_ms=0;f.evidence_ms=0
    for s in range(1,16):
        r=f.tick(s*1000,[('N','S',1.)])
        assert r['heads']['N']['main']['state']=='GREEN'


def test_raw_adapter_rejects_future_atomically_and_preserves_offline_structure():
    m=model();original=deepcopy(m);a=CoherentIntersection(m);b=CoherentIntersection(m)
    for s in range(9):assert a.ingest(packet(s))==b.ingest(packet(s))
    bad=packet(9);bad['vehicles'][0]['detections'][0]['millis']=10000
    with pytest.raises(ValueError,match='future'):a.ingest(bad)
    assert a.ingest(packet(9))==b.ingest(packet(9))
    assert m==original


def test_bad_internal_observation_does_not_advance_state():
    f=JointSignalFilter(model());f.tick(0,[]);old=f.green[0].copy()
    with pytest.raises(ValueError):f.tick(1000,[('N','S',float('nan'))])
    assert f.last_ms==0 and np.array_equal(old,f.green[0])


def test_backward_message_is_adjoint_of_the_full_probability_transition():
    f=JointSignalFilter(model());rng=np.random.default_rng(42)
    g=[rng.random(a.shape) for a in f.green];e=[rng.random(a.shape) for a in f.edge]
    total=sum(float(a.sum()+b.sum()) for a,b in zip(g,e))
    g=[a/total for a in g];e=[a/total for a in e]
    bg=[rng.random(a.shape) for a in g];be=[rng.random(a.shape) for a in e]
    f.green=[a.copy() for a in g];f.edge=[a.copy() for a in e];f.advance(1)
    expected=sum(float((a*b).sum()) for a,b in zip(f.green+f.edge,bg+be))
    old_g,old_e=f.smoother.backward(bg,be)
    actual=sum(float((a*b).sum()) for a,b in zip(g+e,old_g+old_e))
    assert actual==pytest.approx(expected,abs=1e-12)


def test_fixed_lag_history_has_explicit_availability_and_does_not_change_instant_output():
    a=JointSignalFilter(model(),history_lag_s=4);b=JointSignalFilter(model(),history_lag_s=0)
    sealed=[]
    for s in range(15):
        events=[('N','S',1.)] if s in (1,5,9) else []
        x=a.tick(s*1000,events);y=b.tick(s*1000,events)
        history=x.pop('finalized_history');y.pop('finalized_history')
        x.pop('history_lag_s');y.pop('history_lag_s')
        assert x==y
        if s<4:assert history==[]
        else:
            h=history[0];assert h['timestamp_ms']==(s-4)*1000 and h['available_at_ms']==s*1000
            assert h['estimate_kind']=='CAUSAL_FIXED_LAG_RECONSTRUCTION' and h['observed_lamp'] is False
            sealed.append(deepcopy(h))
    assert len(sealed)==11 and sealed[0]['available_at_ms']==4000
    assert len(a.smoother.rows)==4


def test_invalid_obstruction_does_not_mutate_filter_and_packet_gap_clears_smoothing():
    f=JointSignalFilter(model(),history_lag_s=2);f.tick(0,[])
    with pytest.raises(ValueError,match='obstruction'):f.tick(1000,[],blocked={'N':float('nan')})
    assert f.last_ms==0
    f.tick(1000,[])
    assert f.tick(5000,[])['finalized_history']==[]
