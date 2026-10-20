from copy import deepcopy
import pytest
from app.experimental.intersection_sensor_delay import SensorDelayIntersection
from tests.test_intersection_online import model,packet


def test_delayed_restart_is_applied_at_observed_onset_without_changing_issued_predictions():
    engine=SensorDelayIntersection(model());issued=[];corrected=[]
    for s in range(15):
        result=engine.ingest(packet(s));issued.append(deepcopy(result));corrected.extend(result['corrected_restart_observations'])
    assert corrected and any(r['assigned_ms']<r['available_at_ms'] for r in corrected)
    assert all(r['onset_estimate_ms']<=r['available_at_ms'] for r in corrected)
    assert len(engine.rows)<=10 and issued[0]['status']=='AWAITING_EVIDENCE'
    assert engine.ingest(packet(15))['timestamp_ms']==15000
    assert issued[0]['timestamp_ms']==0


def test_future_packet_is_rejected_atomically_before_correction_history_mutates():
    a=SensorDelayIntersection(model());b=SensorDelayIntersection(model())
    for s in range(9):assert a.ingest(packet(s))==b.ingest(packet(s))
    bad=packet(9);bad['vehicles'][0]['detections'][0]['millis']=10000
    with pytest.raises(ValueError,match='future'):a.ingest(bad)
    assert a.ingest(packet(9))==b.ingest(packet(9))


def test_empty_demand_and_long_link_gap_do_not_create_red_or_bridge_history():
    engine=SensorDelayIntersection(model())
    for s in range(12):
        r=engine.ingest(dict(sequence=s,timestamp_ms=s*1000,vehicles=[]))
        assert all(h['main']['state']=='UNKNOWN' for h in r['heads'].values())
    r=engine.ingest(dict(sequence=12,timestamp_ms=300000,vehicles=[]))
    assert r['finalized_history']==[] and len(engine.rows)==1


def test_offline_structure_is_not_mutated_and_restarts_are_never_counted_twice():
    m=model();old=deepcopy(m);engine=SensorDelayIntersection(m);seen=0
    for s in range(20):
        r=engine.ingest(packet(s));seen+=len(r['corrected_restart_observations'])
    assert m==old and seen==1
