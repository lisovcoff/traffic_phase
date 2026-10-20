from copy import deepcopy

import numpy as np
import pytest

from app.experimental.intersection_change_point import ChangePointTimingIntersection
from app.experimental.intersection_front_waiting import FrontWaitingTimingIntersection
from tests.test_intersection_online import model,packet
from tests.test_intersection_queue_observations import reference
from tests.test_intersection_front_release import waiting_track


def summaries(e):
    return [f.summarize(1000,f.green,f.edge,f.evidence_ms) for f in e.filters]


def test_first_outlier_adds_a_bounded_competing_mode_without_replacing_ordinary_or_structure():
    m=model();original=deepcopy(m);e=ChangePointTimingIntersection(m)
    ordinary=[f.hazards[0].copy() for f in e.filters]
    banks=[f.green[0].copy() for f in e.filters]
    results,deltas=e._propose(0,0,48,1000,summaries(e),np.zeros(8))
    assert len(e.filters)==len(e.weights)==len(results)==len(deltas)==16
    assert e.weights[:8].sum()==pytest.approx(.5) and e.weights[8:].sum()==pytest.approx(.5)
    for i in range(8):
        np.testing.assert_array_equal(e.filters[i].hazards[0],ordinary[i])
        np.testing.assert_array_equal(e.filters[i].green[0],banks[i])
        np.testing.assert_array_equal(e.filters[i+8].green[0],banks[i])
        assert e.filters[i+8].medians[0][0]==pytest.approx(48-e.filters[i+8].prior.clearance_s)
        assert float(e.filters[i+8].initial[0].sum())==pytest.approx(1)
    assert m==original
    e._propose(0,0,60,2000,results,deltas)
    assert len(e.filters)==16 and e.proposals[0]==[60,60]


def test_ordinary_jitter_does_not_create_a_new_program():
    e=ChangePointTimingIntersection(model())
    e._propose(0,0,41,1000,summaries(e),np.zeros(8))
    assert len(e.filters)==8 and e.proposals=={}


def test_following_queue_start_remains_permission_evidence_but_not_a_duration_anchor(monkeypatch):
    m=model();m['queue_observations']=reference();e=ChangePointTimingIntersection(m)
    front,following=waiting_track(),waiting_track(-7)
    raw=[front,following];e.restart_changes=raw;seen=[]
    def tick(self,now,q,legacy,blocked):
        seen.append((list(self.restart_changes),list(q['restarts'])))
        return summaries(self),np.zeros(len(self.filters))
    monkeypatch.setattr(FrontWaitingTimingIntersection,'_tick_hypotheses',tick)
    q=dict(restarts=[('N',None,1.)],passages=[],stops=[],braking=[])
    e._tick_hypotheses(4000,q,[],{})
    assert seen==[([front],[('N',None,1.)])]
    assert e.restart_changes is raw


def test_change_point_engine_rejects_future_data_and_keeps_issued_prefix():
    a=ChangePointTimingIntersection(model());b=ChangePointTimingIntersection(model());issued=[];sealed=[]
    for second in range(14):
        if second==7:
            bad=packet(second);bad['vehicles'][0]['detections'][0]['millis']+=1
            with pytest.raises(ValueError,match='future'):a.ingest(bad)
        x=a.ingest(packet(second));assert x==b.ingest(packet(second))
        issued.append(x);sealed.append(deepcopy(x))
    assert issued==sealed


def test_transactional_deepcopy_keeps_legacy_events_in_the_copied_source():
    e=ChangePointTimingIntersection(model());direct=ChangePointTimingIntersection(model())
    for second in range(14):
        e=deepcopy(e)
        assert e.ingest(packet(second))==direct.ingest(packet(second))
