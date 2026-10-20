import pytest
import json
from pathlib import Path
import numpy as np
from app.core.v9.primitives import build_occupancy_matrix
from scripts.sparse_event_suite_2d1 import generate
from scripts.sparse_observation_review_2d1 import conditional_mark_emissions,occupancy


def test_sparse_generator_returns_events_and_uses_real_builder():
    case=generate('stable_K2',2,0,11)
    assert len(case['events'])<case['extent_s']//2
    x,templates,coverage,names=occupancy(case)
    streams={m:[e['timestamp_ms']/1000 for e in case['events'] if e['movement']==m] for m in case['model_movements']}
    expected,order=build_occupancy_matrix(streams,case['extent_s'])
    assert names==order and np.array_equal(x,expected)
    assert coverage[-1]==False and all(coverage[:-1])


def test_absence_of_events_is_neutral_not_negative_permission_evidence():
    templates=np.array([[.9,.1],[.1,.9]])
    x=np.array([[0,0],[1,0],[0,1]])
    emissions=conditional_mark_emissions(x,templates)
    assert np.array_equal(emissions[0],[0,0])
    assert np.allclose(emissions[1],np.log([.9,.1]))
    assert np.allclose(emissions[2],np.log([.1,.9]))
    # Neither zero movement contributes log(1-p) or a RED observation.


def test_conditional_marks_remove_common_intensity_but_assume_relative_demand():
    templates=np.array([[.8,.1],[.1,.8]])
    x=np.array([[1,0],[0,1]])
    scaled=templates*np.array([[.5],[.25]])
    assert np.allclose(conditional_mark_emissions(x,templates),conditional_mark_emissions(x,scaled))


def test_unknown_movement_specific_demand_makes_different_boundaries_observationally_equivalent():
    rates=np.array([[1.,.2],[.2,1.]])
    z1=np.repeat([0,1],[30,30]);z2=np.repeat([0,1],[40,20])
    intensity1=rates[z1]
    demand2=intensity1/rates[z2]
    intensity2=demand2*rates[z2]
    assert not np.array_equal(z1,z2)
    assert np.allclose(intensity1,intensity2)
    # Identical marked-Poisson intensity => same observation law, different histories.


def test_no_demand_and_blockage_are_indistinguishable_but_missing_input_is_explicit():
    a=generate('no_demand_K2',2,0,11);b=generate('blockage_K2',2,0,11)
    assert a['events']==b['events']==[]
    assert a['provided_input_intervals_s']==b['provided_input_intervals_s']
    missing=generate('observation_gap_K3',3,0,11)
    x,p,coverage,names=occupancy(missing)
    assert not np.any(coverage[90:180]) and np.all(coverage[180:-1])


@pytest.mark.local_evidence
def test_suite_truth_preexists_decoder_and_config_seeds_are_frozen():
    root=Path(__file__).resolve().parents[1]/'evidence/stage2d1_sparse_review'
    suite=json.loads((root/'sparse_suite.json').read_text())
    manifest=json.loads((root/'predeclared_manifest.json').read_text())
    assert manifest['seeds']==[11,29]
    for case in suite:
        assert case==generate(case['case'],case['K'],
            30 if case['case'].startswith('hold30') else 10 if case['case'].startswith('hold10') else
            -10 if case['case'].startswith('shorten') else 0,case['seed'])
