from copy import deepcopy
import pytest
from app.core.v10.signal_timing import apply_signal_timing


def estimate(rows=None):
    states=[]
    for i,(n,e,arrow) in enumerate([('RED','GREEN','OFF'),('GREEN','RED','GREEN'),('GREEN','RED','OFF')]):
        states.append(dict(id=i,name=str(i),heads={'N':dict(main=dict(state=n),arrows=[dict(movement='N->E',state=arrow)]),
            'E':dict(main=dict(state=e),arrows=[])},green_movements=[]))
    return dict(available=True,topology={'N':{},'E':{}},states=states,
        segments=rows or [[0,10,0],[10,20,1],[20,30,2],[30,40,0]],operating_phase_count=3,
        observed_physical_state='UNKNOWN')


def at(value,t,head='N'):
    r=next((r for r in value['segments'] if r[0]<=t<r[1]),None)
    return value['states'][r[2]]['heads'][head] if r else None


def test_yellow_precedes_red_and_red_yellow_precedes_green_no_delayed_green():
    r=apply_signal_timing(estimate())
    assert at(r,7.999)['main']['state']=='RED'
    assert at(r,8)['main']['state']=='RED_YELLOW'
    assert at(r,9.999)['main']['state']=='RED_YELLOW'
    assert at(r,10)['main']['state']=='GREEN'
    assert at(r,26.999)['main']['state']=='GREEN'
    assert at(r,27)['main']['state']=='YELLOW'
    assert at(r,30)['main']['state']=='RED'


def test_continuing_green_has_no_false_yellow_at_arrow_switch():
    r=apply_signal_timing(estimate())
    assert all(at(r,t)['main']['state']=='GREEN' for t in [17,18,19.9,20,20.1,21])
    assert at(r,19)['arrows'][0]['state']=='GREEN'
    assert at(r,20)['arrows'][0]['state']=='OFF'
    assert all(h['arrows'][0]['state'] in {'GREEN','OFF'} for s in r['states'] for k,h in s['heads'].items() if k=='N')


def test_gap_and_recording_edges_never_gain_imaginary_neighbors():
    r=apply_signal_timing(estimate([[0,10,1],[12,20,0]]))
    assert at(r,9)['main']['state']=='GREEN'
    assert at(r,11) is None
    assert at(r,12)['main']['state']=='RED'
    assert at(r,19)['main']['state']=='RED'


def test_short_contradictory_run_abstains_instead_of_compressing_yellow():
    r=apply_signal_timing(estimate([[0,1,1],[1,10,0]]))
    assert at(r,.5)['main']['state']=='UNKNOWN'
    assert r['transition_timing']['issues'][0]['reason']=='RUN_TOO_SHORT_FOR_TRANSITION'


def test_joint_calibration_keeps_exclusive_greens_exclusive():
    original=estimate();r=apply_signal_timing(original,boundary_calibration={'approach':'N','onset_bias_s':{'GREEN':2,'RED':4}})
    assert original==estimate()
    assert at(r,8)['main']['state']=='GREEN'
    assert at(r,8,'E')['main']['state']=='RED'
    assert at(r,26)['main']['state']=='RED'
    for state in r['states']:
        assert not all(state['heads'][head]['main']['state']=='GREEN' for head in ['N','E'])
    assert r['operating_phase_count']==3 and r['observed_physical_state']=='UNKNOWN'


def test_no_red_yellow_is_supported_without_moving_green():
    r=apply_signal_timing(estimate(),red_yellow_s=0)
    assert at(r,9.9)['main']['state']=='RED'
    assert at(r,10)['main']['state']=='GREEN'


@pytest.mark.parametrize('yellow,red_yellow',[(float('nan'),2),(3,float('inf')),(-1,2),(3,2.1)])
def test_invalid_transition_durations_rejected(yellow,red_yellow):
    with pytest.raises(ValueError):apply_signal_timing(estimate(),yellow_s=yellow,red_yellow_s=red_yellow)


def test_repeated_application_and_invalid_calibration_order_rejected():
    with pytest.raises(ValueError):apply_signal_timing(apply_signal_timing(estimate()))
    with pytest.raises(ValueError):apply_signal_timing(estimate(),boundary_calibration={'approach':'N','onset_bias_s':{'GREEN':100}})
