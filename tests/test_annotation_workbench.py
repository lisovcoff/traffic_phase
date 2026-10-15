import asyncio
import copy
from io import BytesIO
import hashlib
import json
import pytest
from fastapi import HTTPException,UploadFile
from app.api.annotation import preview,demo,page
from app.core.annotation_workbench import prepare_preview,validate_review,VERSION


def record(points=None):
    return {'id':7,'zone_in':'leg_A','zone_out':'leg_C','detections':points or [
        {'millis':1000,'centroid_x':1,'centroid_y':2,'speed':3},
        {'millis':2000,'centroid_x':2,'centroid_y':4,'speed':0}]}


def prepared(records=None,**kw):
    raw=json.dumps(records if records is not None else [record()]).encode()
    return prepare_preview(BytesIO(raw),'tracks.json',**kw),raw


def review():
    p,_=prepared()
    return {'schema':VERSION,'reviewer':'operator','source':p['source'],'annotations':[{
        'id':'one','kind':'phase_hypothesis','label':'группа N/S',
        'interval_start_ms':1100,'interval_end_ms':1900,'vehicle_timing_uncertainty_ms':None,
        'evidence_source':{'kind':'trajectory_with_onsite_knowledge'},
        'independently_verified':False,'interpretation':'trajectory_based_hypothesis'}]}


def test_raw_time_coordinates_arbitrary_movements_source_hash_and_no_mutation():
    records=[record()];before=copy.deepcopy(records);p,raw=prepared(records)
    assert records==before and p['source']['sha256']==hashlib.sha256(raw).hexdigest()
    assert p['tracks'][0]['movement']=='leg_A->leg_C'
    assert p['tracks'][0]['points']==[[0,1.,2.,3],[1000,2.,4.,0]]
    assert p['source']['timestamp_origin_ms']==1000
    assert p['source']['units']['speed']=='UNKNOWN' and p['inference_used'] is False


def test_sort_duplicates_conflicts_and_gaps_preserved():
    rows=[{'millis':t,'centroid_x':x,'centroid_y':0} for t,x in [(5000,5),(1000,1),(1000,1),(2000,2),(2000,3)]]
    p,_=prepared([record(rows),record(rows)])
    assert [p[0] for p in p['tracks'][0]['points']]==[0,4000]
    assert p['stats']['duplicate_records']==1
    assert p['stats']['conflicting_timestamps_removed']==1
    assert p['stats']['duplicate_detections']==1
    assert p['source']['observed_extent_not_camera_coverage'] is True


@pytest.mark.parametrize('limit',[{'max_bytes':10},{'max_tracks':0},{'max_points':1},{'max_seconds':-1}])
def test_resource_exhaustion_is_explicit_not_partial_preview(limit):
    with pytest.raises(ValueError,match='LIMIT'):prepared(**limit)


def test_bad_input_and_no_valid_coordinates():
    with pytest.raises(ValueError):prepare_preview(BytesIO(b'[broken'),'bad.json')
    with pytest.raises(ValueError,match='NO_COORDINATES'):prepared([{'id':1}])


def test_window_uses_global_clock_even_with_unsorted_tracks():
    early=record();late=record([{'millis':t,'centroid_x':t/1000,'centroid_y':1} for t in [5000,6000]])
    p,raw=prepared([late,early],start_seconds=4,duration_seconds=1)
    assert p['source']['timestamp_origin_ms']==1000
    assert p['source']['end_timestamp_ms']==6000
    assert p['preview_window_ms']==[4000,5000]
    assert [point[0] for point in p['tracks'][0]['points']]==[4000,5000]
    assert p['source']['sha256']==hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError,match='NO_WINDOW_OBSERVATIONS'):
        prepared([late,early],start_seconds=2,duration_seconds=1)


def test_review_round_trip_preserves_hypothesis_and_null_uncertainty():
    p=review();roundtrip=json.loads(json.dumps(p,ensure_ascii=False))
    assert validate_review(roundtrip)=={'valid':True,'annotation_count':1,'independent_truth_certified':False}
    assert roundtrip==p


def test_trajectory_cannot_be_promoted_to_lamp_truth():
    p=review();p['annotations'][0]['kind']='signal_observation'
    with pytest.raises(ValueError,match='Цвет лампы'):validate_review(p)
    p=review();p['annotations'][0]['independently_verified']=True
    with pytest.raises(ValueError,match='не подтверждает'):validate_review(p)


def test_external_review_sync_is_not_automatically_verified():
    p=review();m=p['annotations'][0];m.update(kind='signal_observation',interpretation='independent_source_review_claim')
    m['evidence_source']={'kind':'video_review','reference':'video.mp4','synchronization':{'status':'unverified'}}
    assert validate_review(p)['valid']
    m['evidence_source']['synchronization']['status']='operator_documented'
    with pytest.raises(ValueError,match='основание'):validate_review(p)


@pytest.mark.parametrize('mutation',['range','reverse','duplicate','nan'])
def test_invalid_annotations_rejected(mutation):
    p=review();m=p['annotations'][0]
    if mutation=='range':m['interval_end_ms']=5000
    elif mutation=='reverse':m['interval_start_ms']=1950
    elif mutation=='duplicate':p['annotations'].append(copy.deepcopy(m))
    else:m['interval_end_ms']=float('nan')
    with pytest.raises(ValueError):validate_review(p)


def test_api_upload_and_demo_no_discovery():
    file=UploadFile(file=BytesIO(json.dumps([record()]).encode()),filename='sample.json')
    assert preview(file,0,180)['stats']['display_tracks']==1
    file=UploadFile(file=BytesIO(b'zip'),filename='archive.zip')
    with pytest.raises(HTTPException):preview(file,0,180)
    assert demo()['inference_used'] is False
    assert '/annotation/workbench.js' in page()
