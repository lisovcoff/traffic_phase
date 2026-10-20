from types import SimpleNamespace
import numpy as np
import pytest
from app.core.intersection_signal_path import SignalPath,logarithm
from app.experimental.intersection_signal_path import PathIntersection
from tests.test_intersection_online import model,packet


def tiny():
    g=np.full((2,3),1/6);e=np.zeros((2,2,2));hazard=np.full_like(g,.2)
    f=SimpleNamespace(green=[g],edge=[e],initial=[g.copy()],hazards=[hazard],transitions=[np.array([[0.,1.],[1.,0.]])],
        locations=[(0,(0,'green',0,None,None)),(1,(0,'green',1,None,None))],configurations=[{'color':'A'},{'color':'B'}])
    for a in range(2):
        for b in range(2):
            for s in range(2):
                f.locations.append((len(f.configurations),(0,'edge',a,b,s)));f.configurations.append({'edge':[a,b,s]})
    return f


def test_path_dynamic_program_matches_explicit_dense_max_product_transition():
    f=tiny();p=SignalPath(f,lag_s=10);g=f.green;e=f.edge
    p.update(0,g,e,g,e);before=p.delta.copy();matrix=np.zeros((p.size,p.size))
    for a in range(2):
        for age in range(3):
            matrix[p.gid[0][a,age],p.gid[0][a,min(age+1,2)]]+=.8*.9999
            matrix[p.gid[0][a,age],p.eid[0][a,1-a,0]]+=.2*.9999
        for b in range(2):
            matrix[p.eid[0][a,b,0],p.eid[0][a,b,1]]=.9999
            matrix[p.eid[0][a,b,1],p.gid[0][b,0]]=.9999
    matrix[:,p.gid[0].ravel()]=np.maximum(matrix[:,p.gid[0].ravel()],.0001/6)
    # Emission=1 also for currently unoccupied edge states in this isolated DP check.
    ones_g=[np.ones_like(g[0])];ones_e=[np.ones_like(e[0])]
    for second in range(1,6):
        expected=np.max(before[:,None]+logarithm(matrix),axis=0);expected-=np.max(expected)
        p.update(second*1000,ones_g,ones_e,ones_g,ones_e)
        np.testing.assert_allclose(p.delta,expected,atol=1e-12);before=expected


def test_raw_path_history_is_delayed_bounded_and_published_objects_are_immutable():
    engine=PathIntersection(model(),history_lag_s=3);issued=[]
    for s in range(15):
        r=engine.ingest(packet(s));issued.append(r)
        if s<3:assert r['finalized_history']==[]
        else:
            h=r['finalized_history'][0]
            assert h['timestamp_ms']==(s-3)*1000 and h['available_at_ms']==s*1000
            assert h['observed_lamp'] is False
    assert len(engine.path.pointers)==3
    old=issued[-1]['heads']['N']['main']['state']
    engine.ingest(packet(15));assert issued[-1]['heads']['N']['main']['state']==old


def test_future_packet_rejected_without_changing_path():
    a=PathIntersection(model());b=PathIntersection(model())
    for s in range(8):assert a.ingest(packet(s))==b.ingest(packet(s))
    bad=packet(8);bad['vehicles'][0]['detections'][0]['millis']=9000
    with pytest.raises(ValueError,match='future'):a.ingest(bad)
    assert a.ingest(packet(8))==b.ingest(packet(8))


def test_no_observations_produce_unknown_in_both_instant_and_delayed_history():
    engine=PathIntersection(model(),history_lag_s=3)
    for s in range(12):
        result=engine.ingest(dict(sequence=s,timestamp_ms=s*1000,vehicles=[]))
        assert all(h['main']['state']=='UNKNOWN' for h in result['heads'].values())
        for historical in result['finalized_history']:
            assert all(h['main']['state']=='UNKNOWN' for h in historical['heads'].values())
