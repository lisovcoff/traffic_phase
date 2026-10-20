import pytest

from scripts.check_incident_counterfactual import GreenStretch
from scripts.realistic_traffic_benchmark import signal_plan, generate


def test_stretch_is_monotone_preserves_prefix_and_shifts_tail():
    warp=GreenStretch(10000,30000,12000)
    times=list(range(0,50001,13))
    warped=[warp.timestamp(t) for t in times]
    assert all(a<b for a,b in zip(warped,warped[1:]))
    assert all(warp.timestamp(t)==t for t in times if t<=10000)
    assert all(warp.timestamp(t)==t+12000 for t in times if t>=30000)
    assert warp.derivative(10000)==warp.derivative(30000)==1
    # Positions are unchanged; speed scales inversely to elapsed time.
    t=20000
    numeric=(warp.timestamp(t+100)-warp.timestamp(t-100))/200
    assert numeric==pytest.approx(warp.derivative(t),abs=.01)


def test_extension_changes_one_green_and_keeps_clearance_durations():
    config=dict(seed=512,k=3,duration_s=600,period_s=90)
    normal=signal_plan(config)
    changed=signal_plan({**config,'single_extension':dict(phase=0,after_s=200,seconds=12)})
    selected=next(i for i,r in enumerate(normal) if r['phase']==0 and r['start_s']>=200)
    assert normal[:selected]==changed[:selected]
    for i,(a,b) in enumerate(zip(normal,changed)):
        if i<selected:continue
        assert b['start_s']==pytest.approx(a['start_s']+(0 if i==selected else 12))
        for field in ('end_s','green_end_s','yellow_end_s'):
            assert b[field]==pytest.approx(a[field]+12)
        assert b['yellow_end_s']-b['green_end_s']==pytest.approx(3)


def test_approach_obstruction_keeps_lamp_truth_and_reduces_n_discharge():
    config=dict(seed=729,k=2,duration_s=300,period_s=90,arrival_rate_s=.16,
                cycle_jitter=0,realistic_turns=True,independent_lane_rng=True)
    env=dict(vehicle_classes={'car':1},positive_raw_speed_quantiles=[36],detection_step_quantiles_s=[.2])
    _,normal=generate(config,env)
    _,blocked=generate({**config,'blocking':.4,'block_approaches':['N']},env)
    assert normal['signal_plan']==blocked['signal_plan']
    # Incident metadata must describe the input generation, never signal labels
    # in the per-car detections exported to the inference path.
    start,end=126,246
    def crossings(truth,origin):
        return sum(start<car['crossing_s']<end for car in truth['vehicle_crossings']
                   if car['movement'].startswith(origin+'->') and car['crossing_s'] is not None)
    assert crossings(blocked,'N')<crossings(normal,'N')
    assert crossings(blocked,'S')==crossings(normal,'S')
