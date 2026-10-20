import numpy as np
import pytest
from app.core.intersection_duration_learning import duration_law,duration_arrays
from app.experimental.intersection_learned_duration import LearnedDurationFilter
from tests.test_intersection_local_emissions import profiled_model


def test_regular_offline_phase_durations_are_not_inflated_to_twelve_percent_noise():
    law=duration_law([39.5,40,40.25,39.75]*20)
    assert law['log_sigma']<.04 and law['tail_probability']==.02
    hazard,survival=duration_arrays(law,400)
    assert np.isfinite(hazard).all() and np.all(np.diff(survival)<=0)
    assert hazard.max()>.5 and survival[100]>0


def test_observed_long_phases_increase_the_extension_component():
    ordinary=duration_law([40]*80)
    extended=duration_law([40]*80+[65]*8)
    assert extended['tail_count']==8 and extended['tail_probability']>ordinary['tail_probability']
    assert duration_law([40]*7) is None


def test_learned_duration_and_clearance_probability_remain_normalized():
    model=profiled_model();model['regimes'][0]['causal_duration_laws']=[duration_law([40]*30)]*2
    engine=LearnedDurationFilter(model)
    for second in range(100):
        result=engine.tick(second*1000,[('N','S',1.)] if second%11==0 else [])
        assert sum(float(g.sum()+e.sum()) for g,e in zip(engine.green,engine.edge))==pytest.approx(1,abs=1e-9)
        assert 0<=result['clearance_probability']<=1
