import pytest
from app.core.v10.timing_calibration import fit_onset_delays


def material():
    # Head W, distinct green/red delays and a harmless outlier. No site names.
    states=[{'id':0,'heads':{'W':{'main':{'state':'RED'}}}},
            {'id':1,'heads':{'W':{'main':{'state':'GREEN'}}}}]
    rows=[];truth=[];last=0
    for i in range(3):
        g=10+100*i;r=50+100*i;rows.extend([[last,g,0],[g,r,1]]);last=r
        for color,t,bias in [('GREEN',g,2),('RED',r,4)]:
            error=.4 if i==2 else 0
            truth.append(dict(color=color,bracket_s=[t-bias-error,t-bias-error]))
    rows.append([last,300,0])
    return dict(states=states,segments=rows),truth


def test_head_independent_rule_separates_startup_and_end_delay():
    estimate,truth=material()
    result=fit_onset_delays(estimate,truth,approach='W',training_range_s=[0,300],clock_provenance={'independent_vehicle_link_supported':True})
    assert result['onset_bias_s']=={'GREEN':2,'RED':4}


def test_validation_annotation_never_silently_enters_training():
    estimate,truth=material();truth.append(dict(color='GREEN',bracket_s=[308,308]))
    with pytest.raises(ValueError,match='training'):
        fit_onset_delays(estimate,truth,approach='W',training_range_s=[0,300],clock_provenance={'independent_vehicle_link_supported':True})


def test_light_cycle_matching_cannot_substitute_for_independent_clock():
    estimate,truth=material()
    with pytest.raises(ValueError,match='independent'):
        fit_onset_delays(estimate,truth,approach='W',training_range_s=[0,300],clock_provenance={'independent_vehicle_link_supported':False})
