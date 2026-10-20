from copy import deepcopy

import numpy as np
import pytest

from app.experimental.intersection_adaptive_timing import AdaptiveRobustTimingIntersection
from app.experimental.intersection_front_release import FrontReleaseTimingIntersection,stopped_front
from app.experimental.intersection_front_waiting import FrontWaitingTimingIntersection
from tests.test_intersection_online import model,packet
from tests.test_intersection_queue_observations import reference,point


def waiting_track(offset=0):
    return dict(origin='N',target=None,last_restart_ms=3000,
                points=[point(t,offset) for t in range(0,3000,500)])


def test_release_anchor_requires_continuous_stationary_front_positions():
    ref=reference()['references']['N'];track=waiting_track()
    assert stopped_front(track,ref,3000)
    assert not stopped_front(waiting_track(-7),ref,3000)
    assert not stopped_front(waiting_track(6),ref,3000)
    moving=waiting_track()
    moving['points']=[point(t,-5+t/500) for t in range(0,3000,500)]
    assert not stopped_front(moving,ref,3000)
    missing=waiting_track();missing['points'][0].pop('lat')
    assert not stopped_front(missing,ref,3000)
    gapped=waiting_track();gapped['points']=[point(0,0),point(2200,0),point(2500,0)]
    assert not stopped_front(gapped,ref,3000)
    assert not stopped_front(track,ref,9000)


@pytest.mark.parametrize('blocked',[False,True])
def test_anchor_changes_only_conditional_age_and_retains_obstruction_ambiguity(monkeypatch,blocked):
    m=model();m['queue_observations']=reference();e=FrontReleaseTimingIntersection(m)
    e.restart_changes=[waiting_track()]
    for f in e.filters:
        f.green[0][:]=0;f.green[0][0,25]=.8;f.green[0][1,30]=.2
        f.edge[0][:]=0;f.evidence_ms=4000
    before=[f.green[0].copy() for f in e.filters]
    results=[f.summarize(4000,f.green,f.edge,f.evidence_ms) for f in e.filters]
    monkeypatch.setattr(AdaptiveRobustTimingIntersection,'_tick_hypotheses',lambda *args:(results,np.zeros(8)))
    q=dict(restarts=[('N',None,1.)],passages=[],stops=[],braking=[])
    e._tick_hypotheses(4000,q,[],{'N':.9 if blocked else .03})
    assert bool(e.release_age_observations) is not blocked
    for old,f in zip(before,e.filters):
        np.testing.assert_allclose(f.green[0].sum(axis=1),old.sum(axis=1))
        np.testing.assert_array_equal(f.green[0][1],old[1])
        if blocked:np.testing.assert_array_equal(f.green[0],old)
        else:
            assert f.green[0][0,25]==pytest.approx(.16)
            assert f.green[0][0,1:6].sum()==pytest.approx(.64)


@pytest.mark.parametrize('factory',[FrontReleaseTimingIntersection,FrontWaitingTimingIntersection])
def test_front_release_candidate_is_causal_and_does_not_modify_structure_or_issued_results(factory):
    m=model();original=deepcopy(m);a=factory(m);b=factory(m)
    issued=[];sealed=[]
    for s in range(12):
        if s==7:
            bad=packet(s);bad['vehicles'][0]['detections'][0]['millis']+=1000
            with pytest.raises(ValueError,match='future'):a.ingest(bad)
        x=a.ingest(packet(s));assert x==b.ingest(packet(s))
        issued.append(x);sealed.append(deepcopy(x))
        assert x['production_enabled'] is False
        for f in a.filters:
            assert sum(float(g.sum()+edge.sum()) for g,edge in zip(f.green,f.edge))==pytest.approx(1)
    assert issued==sealed and m==original
