import copy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from app.core.v9.events import _kinematic_release_candidate
from app.core.v9.vehicle_evidence import extract_vehicle_evidence
from app.experimental.restart_localization import localize_restart
from tests.restart_localization_cases import generate_case


PLAN=json.loads((Path(__file__).resolve().parent/'fixtures/restart_localization_plan.json').read_text())


def legacy_event(track):
    events,_=extract_vehicle_evidence(track)
    return next((e for e in events if e.event_type=='RELEASE'),None)


@pytest.mark.parametrize('spec',PLAN['cases'],ids=lambda s:s['name'])
def test_declared_sparse_vehicle_cases(spec):
    track,truth=generate_case(spec,PLAN['generator'])
    before=copy.deepcopy(track)
    event=legacy_event(track)
    result=localize_restart(track,event)
    assert track==before
    assert result['physical']['estimated_state']=='UNKNOWN'
    assert result['estimate']['calibrated_lamp_probability'] is None
    assert result['estimate']['level']=='activity'
    kind=spec['kind']
    recover=kind in ['abrupt_dt01','abrupt_dt02','acceleration','identical_duplicates','sine_witness']
    if not recover:
        assert result['status']=='unavailable'
        assert result['estimate']['abstention_reason']
        return
    assert result['status']=='available_proxy'
    localized=result['localized_event']
    point=localized['timestamp_ms']
    onset=truth['independent_world_onset_ms']
    assert point>=onset-1
    assert point-onset<= (1000 if kind=='acceleration' else truth['dt_ms']+1)
    if kind!='acceleration':
        a,b=localized['uncertainty']['vehicle_event']['sampling_interval_ms']
        assert a<=onset<=b
    assert localized['uncertainty']['event_to_signal_switch']['status']=='UNKNOWN'
    assert localized['confidence']==event.confidence
    assert localized['temporal_uncertainty_ms']==event.temporal_uncertainty_ms


def test_legacy_candidate_values_identical_with_diagnostics():
    track,_=generate_case(PLAN['cases'][0],PLAN['generator'])
    ds=track['detections'];diag={}
    old=_kinematic_release_candidate(ds,0,40000)
    new=_kinematic_release_candidate(ds,0,40000,diagnostics=diag)
    assert old==new
    assert diag['selected_seed_index']>=0
    _kinematic_release_candidate([],0,40000,diagnostics=diag)
    assert diag=={}


def test_renaming_movements_and_unobserved_cause_does_not_change_timing():
    track,_=generate_case(PLAN['cases'][0],PLAN['generator'])
    event=legacy_event(track)
    original=localize_restart(track,event)
    for cause in ['green_queue','permissive_turn','blockage_cleared_without_switch']:
        track['unobserved_cause']=cause
        renamed=localize_restart(track,replace(event,movement='arbitrary-shared-movement'))
        assert renamed['localized_event']['timestamp_ms']==original['localized_event']['timestamp_ms']
        assert renamed['physical']['estimated_state']=='UNKNOWN'


def test_inputs_do_not_accept_signal_labels_argument():
    with pytest.raises(TypeError):
        localize_restart({},None,annotations={'phase':'green'})


def test_resource_limit_is_abstention():
    result=localize_restart({'detections':[{}]*20001},None)
    assert result['estimate']['abstention_reason']=='DETECTION_RESOURCE_LIMIT'


def test_multiple_supported_raw_transitions_are_not_silently_ranked():
    import numpy as np

    track,_=generate_case(PLAN['cases'][0],PLAN['generator'])
    for d in track['detections']:
        t=d['millis']/1000
        d['centroid_x']=.3+.01*(max(0,t-20)-np.clip(t-21.2,0,.3))+1e-5*np.sin(3*t)
    result=localize_restart(track,legacy_event(track))
    assert result['status']=='unavailable'
    assert result['estimate']['abstention_reason']=='MULTIPLE_RAW_TRANSITIONS'
    assert len(result['alternatives'])>=2


def test_seed_from_another_track_is_rejected():
    track,_=generate_case(PLAN['cases'][0],PLAN['generator'])
    event=replace(legacy_event(track),source_track_id=999)
    assert localize_restart(track,event)['estimate']['abstention_reason']=='SOURCE_EVENT_TRACK_MISMATCH'
