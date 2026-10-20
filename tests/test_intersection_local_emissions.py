from copy import deepcopy
import numpy as np
import pytest
from app.core.intersection_local_emissions import LocalAgeCounts,duration_age_weights
from app.experimental.intersection_local_filter import LocalEmissionFilter,LocalObservationSource,LocalProfileIntersection
from app.core.intersection_signal_filter import CoherentIntersection
from tests.test_intersection_online import model,packet


def profiled_model():
    m=model();counts=LocalAgeCounts(m['approaches'],2)
    for phase,origin in ((0,'N'),(1,'E')):
        for _ in range(30):counts.add('NEAR_RESTART',origin,phase,.15)
        for _ in range(30):counts.add('PASSAGE',origin,phase,.5)
    m['regimes'][0]['causal_local_emissions']=counts.finish()
    return m


def test_availability_age_is_learnt_from_the_confirmed_channel_not_release_age():
    c=LocalAgeCounts(['N','E'],2)
    for _ in range(80):
        c.add('NEAR_RESTART','N',0,.15)
        c.add('PASSAGE','N',0,.6)
        c.add('NEAR_RESTART','E',1,.15)
    p=c.finish();v=np.array(p['probabilities']);key=p['alphabet'].index('NEAR_RESTART:N')
    assert v[0,4,key]>v[0,0,key] and v[0,4,key]>v[1,4,key]
    assert np.allclose(v.sum(axis=2),1)
    assert p['physical_reaction_or_lamp_delay_calibrated'] is False


def test_empty_observation_training_is_uniform_not_a_red_label():
    p=LocalAgeCounts(['N','E'],2).finish()
    assert np.allclose(p['probabilities'],1/12)


def test_surviving_duration_mixture_does_not_clip_an_extension_to_the_end_bin():
    weights=duration_age_weights(np.full(121,.02),30,4,32)
    assert weights.shape==(121,32) and np.allclose(weights.sum(axis=1),1)
    assert weights[0,0]==pytest.approx(1)
    assert weights[90,-1]<.2 and weights[90,:-1].sum()>.8


def test_profile_validation_and_offline_model_immutability():
    m=profiled_model();old=deepcopy(m);LocalEmissionFilter(m)
    assert m==old
    bad=deepcopy(m);bad['regimes'][0]['causal_local_emissions']['probabilities'][0][0][0]=float('nan')
    with pytest.raises(ValueError,match='probabilities'):LocalEmissionFilter(bad)
    bad=deepcopy(m);bad['regimes'].append(deepcopy(bad['regimes'][0]));bad['regimes'][1].pop('causal_local_emissions')
    with pytest.raises(ValueError,match='all saved regimes'):LocalEmissionFilter(bad)


def test_optimised_source_preserves_original_causal_observations():
    m=model();old=CoherentIntersection(m);source=LocalObservationSource(m)
    for s in range(12):
        p=packet(s);old.ingest(p);base,local,legacy,marks,lags=source.ingest(p)
        assert legacy==old.events
        assert source.motion.tracks==old.motion.tracks
        assert source.motion.last_ms==old.motion.last_ms
    assert all(lag>=0 for a,lag in lags)


def test_future_packet_is_atomic_in_the_learned_filter_and_no_observations_are_unknown():
    a=LocalProfileIntersection(profiled_model());b=LocalProfileIntersection(profiled_model())
    for s in range(8):assert a.ingest(packet(s))==b.ingest(packet(s))
    bad=packet(8);bad['vehicles'][0]['detections'][0]['millis']=9000
    with pytest.raises(ValueError,match='future'):a.ingest(bad)
    assert a.ingest(packet(8))==b.ingest(packet(8))
    empty=LocalProfileIntersection(profiled_model())
    for s in range(15):
        r=empty.ingest(dict(sequence=s,timestamp_ms=s*1000,vehicles=[]))
        assert all(h['main']['state']=='UNKNOWN' for h in r['heads'].values())
