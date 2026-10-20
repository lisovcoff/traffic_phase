from copy import deepcopy
import numpy as np
from app.experimental.intersection_conditioned_local import ConditionedLocalFilter
from app.core.intersection_signal_filter import JointSignalFilter
from tests.test_intersection_local_emissions import profiled_model


def test_approach_volume_rescaling_does_not_change_conditional_timing_likelihoods():
    a=profiled_model();b=deepcopy(a);profile=b['regimes'][0]['causal_local_emissions']
    p=np.array(profile['probabilities']);ix=[i for i,n in enumerate(profile['alphabet']) if n.endswith(':N')]
    p[:,:,ix]*=50;p/=p.sum(axis=2,keepdims=True);profile['probabilities']=p.tolist()
    x=ConditionedLocalFilter(a);y=ConditionedLocalFilter(b)
    np.testing.assert_allclose(x.learned[0],y.learned[0],atol=1e-12)
    np.testing.assert_allclose(x.learned_edge[0],y.learned_edge[0],atol=1e-12)


def test_untrained_legacy_channel_falls_back_to_the_existing_causal_emission():
    model=profiled_model();a=ConditionedLocalFilter(model);b=JointSignalFilter(model)
    for s in range(15):
        event=[('N','S',1.)] if s in (1,5,10) else []
        assert a.tick(s*1000,event)==b.tick(s*1000,event)
