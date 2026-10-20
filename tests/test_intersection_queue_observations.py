from copy import deepcopy
import math
import numpy as np
import pytest

from app.core.intersection_queue_observations import QueueObservations,learn_queue_references,metric_xy,QueueReferenceLearner,IntersectionQueueLearner


def point(ms,x,y=0,zone='N'):
    return dict(millis=ms,lat=55+y/111000,lng=61+x/(111000*math.cos(math.radians(55))),zone=zone,speed=0)


def offline_tracks():
    tracks=[]
    for i in range(30):
        # Straight traffic, queued at a stable front and at varying upstream
        # queue positions. Future destinations exist only in offline records.
        stop=0 if i<20 else -20
        x=list(np.linspace(-60,stop,25))+[stop]*20+list(np.linspace(stop,60,25))
        tracks.append(dict(id=i,zone_in='N',zone_out='_S',detections=[point(j*200,float(p),zone='N' if p<=3 else '_S') for j,p in enumerate(x)]))
    return tracks


def reference():
    return dict(references={'N':dict(anchor_lat_lng=[55,61],point_m=[0,0],heading=[1,0],lateral_radius_m=4)})


def test_offline_reference_uses_repeated_front_stops_not_upstream_queue():
    rows=offline_tracks();original=deepcopy(rows);r=learn_queue_references(rows)['references']['N']
    assert np.linalg.norm(np.array(r['point_m'])-metric_xy(point(0,0),r['anchor_lat_lng']))<1 and r['heading'][0]>.99
    assert r['stopping_runs']>=20 and rows==original


def test_long_queues_do_not_erase_a_repeated_but_rare_front_cluster():
    rows=offline_tracks()
    # A long queue contains many more upstream stops than head-of-queue stops.
    # Population percentage is not evidence that the first car stops upstream.
    rows=rows[:20]+rows[20:]*100
    r=learn_queue_references(rows)['references']['N']
    assert np.linalg.norm(np.array(r['point_m'])-metric_xy(point(0,0),r['anchor_lat_lng']))<1


def test_offline_learner_is_bounded_and_skips_malformed_coordinate_samples():
    learner=QueueReferenceLearner(capacity=32)
    rows=offline_tracks()*4
    for row in rows:learner.add(row)
    assert all(len(v)<=32 for v in learner.stops.values())
    assert all(len(v)<=32 for v in learner.directions.values())
    learner.add(dict(zone_in='N',detections=[None,dict(lat='bad',lng=61,millis=0)]*10))
    assert learner.finish()['references']


def test_curved_main_route_uses_its_incoming_prefix_not_an_interior_turn_wait():
    learner=IntersectionQueueLearner()
    for i in range(20):
        xy=[(float(x),0.) for x in np.linspace(60,0,25)]+[(0.,0.)]*20+[(0.,float(y)) for y in np.linspace(0,60,25)]
        ds=[point(j*200,x,y,zone='E' if y<=3 else '_N') for j,(x,y) in enumerate(xy)]
        learner.add(dict(id=i,zone_in='E',zone_out='_N',detections=ds))
    assert learner.straight.finish()['references']=={}
    result=learner.finish([dict(signal_topology={'E':dict(main='E->N',arrows=[])})])
    assert result['references']['E']['heading']==pytest.approx([-1,0])
    assert result['references']['E']['training_route']=='E->N'
    assert learner.finish([dict(signal_topology={'E':dict(main='E->W',arrows=[])})])['references']=={}


def test_current_passage_is_emitted_once_without_future_target():
    q=QueueObservations(reference());track=dict(origin='N',target=None,points=[point(0,-2),point(1000,4)])
    a=q.extract({'x':track},['x'],1000,{})
    assert a['passages']==[('N',None,.7)]
    assert q.extract({'x':track},['x'],2000,{})['passages']==[]


def test_stopping_far_upstream_does_not_become_a_front_stop():
    q=QueueObservations(reference());track=dict(origin='N',target=None,points=[point(i*500,-30) for i in range(5)])
    assert q.extract({'x':track},['x'],2000,{})['stops']==[]


def test_positive_downstream_obstruction_is_separate_from_signal_color():
    q=QueueObservations(reference());track=dict(origin='N',target=None,points=[point(i*500,20) for i in range(5)])
    r=q.extract({'x':track},['x'],2000,{})
    assert r['downstream_occupied']==['N'] and r['blocked_probability']['N']>=.9
    assert r['stops']==[] and 'signal_state' not in r


def test_missing_geography_retains_legacy_observation_fallback():
    q=QueueObservations(reference());track=dict(origin='N',target=None,points=[dict(millis=0),dict(millis=1000)])
    assert q.extract({'x':track},['x'],1000,{})['covered']==set()


def test_local_deceleration_is_one_positive_braking_observation():
    q=QueueObservations(reference())
    # Decelerating towards the queue, 8 -> 2 m/s. This is evidence of braking,
    # not a ground-truth RED label, and is emitted only once for this vehicle.
    xs=[-20,-16,-12,-8,-7,-6,-5]
    track=dict(origin='N',target=None,points=[point(i*500,x) for i,x in enumerate(xs)])
    result=q.extract({'x':track},['x'],3000,{})
    assert result['braking']==['N'] and result['stops']==[]
    assert q.extract({'x':track},['x'],4000,{})['braking']==[]


def test_constant_speed_and_braking_far_upstream_are_not_signal_evidence():
    for xs in ([-20,-17,-14,-11,-8,-5,-2],[-60,-56,-52,-48,-47,-46,-45]):
        q=QueueObservations(reference())
        track=dict(origin='N',target=None,points=[point(i*500,x) for i,x in enumerate(xs)])
        assert q.extract({'x':track},['x'],3000,{})['braking']==[]
