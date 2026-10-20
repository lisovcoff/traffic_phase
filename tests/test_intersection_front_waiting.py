import numpy as np
import pytest

from app.experimental.intersection_front_release import FrontReleaseTimingIntersection
from app.experimental.intersection_front_waiting import FrontWaitingTimingIntersection,waiting_survival,currently_waiting_front
from tests.test_intersection_online import model
from tests.test_intersection_queue_observations import reference,point


def test_newest_motion_is_not_relabelled_as_continued_waiting():
    ref=reference()['references']['N']
    track=dict(origin='N',points=[point(t,0) for t in range(500,4500,500)])
    assert currently_waiting_front(track,ref,4000)
    track['points'][-1]=point(4000,1)
    assert not currently_waiting_front(track,ref,4000)
    track['points'][-1]=point(4000,0,zone='_S')
    assert not currently_waiting_front(track,ref,4000)


def test_conditional_waiting_factors_do_not_repeatedly_count_the_same_survival():
    survival=waiting_survival(np.arange(21),4,.2)
    ratios=survival[1:]/survival[:-1]
    assert np.prod(ratios)==pytest.approx(.2)
    np.testing.assert_array_equal(ratios[4:],np.ones(16))
    assert np.all(np.isfinite(ratios)) and np.all((0<ratios)&(ratios<=1))


@pytest.mark.parametrize('blocked',[False,True])
def test_only_observed_front_waiting_supplies_current_evidence(monkeypatch,blocked):
    m=model();m['queue_observations']=reference();e=FrontWaitingTimingIntersection(m)
    e.last_waiting_ms=3000
    e.source.motion.tracks={'x':dict(origin='N',last_ms=4000,
        points=[point(t,0) for t in range(500,4500,500)])}
    for f in e.filters:
        f.green[0][:]=0;f.green[0][0,2]=.5;f.green[0][1,2]=.5
        f.edge[0][:]=0;f.evidence_ms=None
    results=[f.summarize(4000,f.green,f.edge,None) for f in e.filters]
    monkeypatch.setattr(FrontReleaseTimingIntersection,'_tick_hypotheses',lambda *args:(results,np.zeros(8)))
    e._tick_hypotheses(4000,{},[],{'N':.9 if blocked else .03})
    assert e.waiting_origins==([] if blocked else ['N'])
    for f in e.filters:
        assert f.evidence_ms==(None if blocked else 4000)
        assert f.green[0].sum()==pytest.approx(1)
        assert f.green[0][0].sum()==pytest.approx(.5) if blocked else f.green[0][0].sum()<.5


def test_absence_of_vehicles_does_not_become_a_waiting_or_red_observation():
    e=FrontWaitingTimingIntersection(model())
    for second in range(20):
        result=e.ingest(dict(timestamp_ms=second*1000,sequence=second,vehicles=[]))
        assert result['continued_front_waiting']==[]
        assert result['status']=='AWAITING_EVIDENCE'
        assert all(h['main']['state']=='UNKNOWN' for h in result['heads'].values())


def test_waiting_for_unknown_arrow_is_not_negative_evidence_for_main_green(monkeypatch):
    m=model();m['queue_observations']=reference()
    m['regimes'][0]['signal_topology']['N']['arrows']=['N->E']
    e=FrontWaitingTimingIntersection(m);e.last_waiting_ms=3000
    e.source.motion.tracks={'x':dict(origin='N',last_ms=4000,
        points=[point(t,0) for t in range(500,4500,500)])}
    results=[f.summarize(4000,f.green,f.edge,None) for f in e.filters]
    before=[f.green[0].copy() for f in e.filters]
    monkeypatch.setattr(FrontReleaseTimingIntersection,'_tick_hypotheses',lambda *args:(results,np.zeros(8)))
    e._tick_hypotheses(4000,{},[],{})
    assert e.waiting_origins==[]
    for old,f in zip(before,e.filters):np.testing.assert_array_equal(old,f.green[0])
