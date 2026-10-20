from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient

from app.core.intersection_project import SCHEMA,model_fingerprint,write_json
from app.core.intersection_online import CausalIntersection
from app.core import intersection_online_store as store


def model():
    states=[]
    topology={a:dict(main=a+'->'+dict(N='S',S='N',E='W',W='E')[a],arrows=[]) for a in 'NSEW'}
    for active in ('NS','EW'):
        states.append({a:dict(main=dict(state='GREEN' if a in active else 'RED'),arrows=[]) for a in 'NSEW'})
    result=dict(schema=SCHEMA,model_id='a'*32,approaches=['N','S','E','W'],geometries={
        'reference':dict(projection=dict(matrix=[[1,0,0],[0,1,0],[0,0,1]]))},regimes=[dict(
        regime_id='regime_001',phase_count=2,phase_names=['A','B'],period_s=80,
        phase_durations={n:dict(median_s=40,p10_s=38,p90_s=42) for n in ['A','B']},
        observed_transitions=[dict(source=0,target=1,observations=10),dict(source=1,target=0,observations=10)],
        signal_topology=topology,phase_head_states=states,
        movement_probabilities={'N->S':[.8,.01],'S->N':[.8,.01],'E->W':[.01,.8],'W->E':[.01,.8]})])
    result['fingerprint']=model_fingerprint(result)
    return result


def packet(second,*,sequence=None,origin='E'):
    d=dict(millis=second*1000,centroid_x=.8,centroid_y=.5,zone=origin,speed=0 if second<5 else 20)
    return dict(sequence=second if sequence is None else sequence,timestamp_ms=second*1000,
        vehicles=[dict(id=1,zone_in=origin,detections=[d])])


def test_positive_restart_synchronizes_fixed_offline_structure_without_future_exit():
    m=model();original=deepcopy(m);engine=CausalIntersection(m)
    outputs=[engine.ingest(packet(s)) for s in range(9)]
    assert outputs[0]['status']=='AWAITING_EVIDENCE'
    assert outputs[-1]['heads']['E']['main']['state']=='GREEN'
    assert outputs[-1]['phase_count']==2 and outputs[-1]['phase_id']==1
    assert m==original


def test_future_invalid_packet_leaves_published_prefix_and_engine_unchanged():
    engine=CausalIntersection(model());a=engine.ingest(packet(0))
    bad=packet(1);bad['vehicles'][0]['detections'][0]['millis']=2000
    with pytest.raises(ValueError,match='future'):engine.ingest(bad)
    assert engine.last_ms==0 and a['timestamp_ms']==0
    fresh=CausalIntersection(model());fresh.ingest(packet(0))
    assert engine.ingest(packet(1))==fresh.ingest(packet(1))


def test_no_demand_and_link_gap_are_not_red_observations():
    engine=CausalIntersection(model())
    for s in range(9):engine.ingest(packet(s))
    result=engine.ingest(dict(sequence=9,timestamp_ms=300000,vehicles=[]))
    assert result['status']=='AWAITING_EVIDENCE'
    assert all(h['main']['state']=='UNKNOWN' for h in result['heads'].values())
    assert result['missing_interval_ms']==[9000,300000]
    assert result['vehicles']==[]


def test_future_zone_out_and_foreign_approach_are_rejected():
    engine=CausalIntersection(model());bad=packet(0);bad['vehicles'][0]['zone_out']='W'
    with pytest.raises(ValueError,match='future'):engine.ingest(bad)
    m=model();m['approaches']=['N','S','E'];engine=CausalIntersection(m)
    with pytest.raises(ValueError,match='offline'):engine.ingest(packet(0,origin='W'))


def test_journal_idempotency_restart_and_original_history(tmp_path):
    folder=tmp_path/'project';write_json(folder/'model.json',model())
    stream=store.create_stream(folder)['stream_id']
    issued=[]
    for s in range(9):issued.append(store.accept_packet(folder,stream,packet(s)))
    assert store.accept_packet(folder,stream,packet(0))==issued[0]
    bad=packet(8);bad['vehicles'][0]['detections'][0]['speed']=90
    with pytest.raises(ValueError,match='sequence'):store.accept_packet(folder,stream,bad)
    store._cache.clear()
    result=store.accept_packet(folder,stream,packet(9))
    fresh=CausalIntersection(model())
    for s in range(10):expected=fresh.ingest(packet(s))
    assert result==expected
    assert store.stream_history(folder,stream)['snapshots']==issued+[result]


def test_v8_journal_transaction_cache_cold_restore_and_legacy_stream(tmp_path):
    from app.core.intersection_engine import AdaptiveIntersection,VERSION
    from tests.test_intersection_queue_observations import reference
    legacy=tmp_path/'legacy';write_json(legacy/'model.json',model())
    old=store.create_stream(legacy)
    assert old['engine']=='causal-intersection-v7'
    prior=store.accept_packet(legacy,old['stream_id'],packet(0))
    m=model();m['queue_observations']=reference();m['fingerprint']=model_fingerprint(m)
    folder=tmp_path/'adaptive';write_json(folder/'model.json',m)
    manifest=store.create_stream(folder);assert manifest['engine']==VERSION
    stream=manifest['stream_id'];direct=AdaptiveIntersection(m);issued=[]
    for second in range(14):
        if second in (5,10):store._cache.clear()
        expected=direct.ingest(packet(second))
        actual=store.accept_packet(folder,stream,packet(second))
        assert actual==expected and actual['schema']==VERSION
        issued.append(actual)
    assert store.accept_packet(folder,stream,packet(0))==issued[0]
    assert store.stream_history(folder,stream)['snapshots']==issued
    assert store.snapshot_at(folder,stream,3500)['snapshot']==issued[3]
    store._cache.clear()
    old_next=store.accept_packet(legacy,old['stream_id'],packet(1))
    baseline=CausalIntersection(model());assert baseline.ingest(packet(0))==prior
    assert baseline.ingest(packet(1))==old_next


def test_api_accepts_current_batches_rejects_future_fields_and_restores(monkeypatch,tmp_path):
    from app.api import intersection_projects as api
    from app.main import app
    monkeypatch.setattr(api,'PROJECT_ROOT',tmp_path)
    folder=tmp_path/('a'*32);write_json(folder/'model.json',model())
    base='/api/v1/intersections/'+('a'*32)
    with TestClient(app) as client:
        result=client.post(base+'/online');assert result.status_code==201,result.text
        stream=result.json()['stream_id'];url=base+'/online/'+stream
        for s in range(9):
            r=client.post(url+'/packets',json=packet(s));assert r.status_code==200,r.text
        assert r.json()['heads']['E']['main']['state']=='GREEN'
        bad=packet(9);bad['vehicles'][0]['zone_out']='W'
        assert client.post(url+'/packets',json=bad).status_code==422
        bad=packet(9);bad['vehicles'][0]['detections'][0]['millis']=10000
        assert client.post(url+'/packets',json=bad).status_code==409
        assert client.get(url).json()['snapshot']['timestamp_ms']==8000
        assert len(client.get(url+'/history').json()['snapshots'])==9
        assert len(client.get(url+'/history?after=6').json()['snapshots'])==2
        historical=client.get(url+'/at?timestamp_ms=3500').json()
        assert historical['historical'] and historical['snapshot']['timestamp_ms']==3000
        assert client.get(url+'/at?timestamp_ms=1').json()['snapshot']['timestamp_ms']==0
        assert client.get(url).json()['snapshot']['timestamp_ms']==8000
    store._cache.clear()
    with TestClient(app) as client:
        assert client.post(url+'/packets',json=packet(9)).status_code==200


def test_packet_driver_omits_future_destinations_and_future_detections():
    from scripts.online_packets import packets_from_tracks
    tracks=[dict(id=1,zone_in='E',zone_out='W',detections=[packet(s)['vehicles'][0]['detections'][0] for s in range(20)])]
    a=list(packets_from_tracks(tracks,end_ms=8000))
    changed=deepcopy(tracks);changed[0]['zone_out']='N'
    for d in changed[0]['detections']:
        if d['millis']>8000:d['centroid_x']=10000;d['speed']=0
    b=list(packets_from_tracks(changed,end_ms=8000))
    assert a==b
    first=CausalIntersection(model());second=CausalIntersection(model())
    assert [first.ingest(p) for p in a]==[second.ingest(p) for p in b]
    assert all(d['millis']<=p['timestamp_ms'] for p in a for v in p['vehicles'] for d in v['detections'])


def test_conflicting_detections_in_one_packet_fail_without_advancing():
    engine=CausalIntersection(model());p=packet(0)
    p['vehicles'][0]['detections'].append({**p['vehicles'][0]['detections'][0],'speed':30})
    with pytest.raises(ValueError,match='conflicting'):engine.ingest(p)
    assert engine.last_ms is None


def test_online_phase_does_not_use_historical_absolute_clock():
    a=CausalIntersection(model());m=model();m['historical_clock_ms']=9999999999999;b=CausalIntersection(m)
    for s in range(9):
        one=packet(s);other=deepcopy(one);other['timestamp_ms']+=86400000
        for v in other['vehicles']:
            for d in v['detections']:d['millis']+=86400000
        x,y=a.ingest(one),b.ingest(other)
        assert x['heads']==y['heads'] and x['phase_age_estimate_s']==y['phase_age_estimate_s']


def test_queue_creep_does_not_hide_the_later_departure_restart():
    engine=CausalIntersection(model());observed=[]
    for s in range(22):
        p=packet(s);p['vehicles'][0]['detections'][0]['speed']=20 if 5<=s<=8 or s>=15 else 0
        r=engine.ingest(p)
        if r['evidence_count']:observed.append(s)
    assert len(observed)==2 and observed[0]<10 and observed[1]>=17


def test_position_motion_supports_stale_nonzero_vendor_speed():
    engine=CausalIntersection(model())
    for s in range(11):
        p=packet(s);p['vehicles'][0]['detections'][0].update(speed=100,lat=55+.00005*max(0,s-4),lng=61.)
        r=engine.ingest(p)
    assert r['event_count']>=1 and r['heads']['E']['main']['state']=='GREEN'
