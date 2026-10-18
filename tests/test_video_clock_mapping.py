import pytest
from app.experimental.video_clock_mapping import map_bracket, source_bias


def test_positive_detection_offset_and_independent_uncertainty_envelope():
    r=map_bracket([10,10.1],origin_ms=100000,delta_s=1.25,delta_bounds_s=[1.1,1.4])
    assert r['json_bracket_fixed_clock_ms']==pytest.approx([111250,111350])
    assert r['json_bracket_conditional_envelope_ms']==pytest.approx([111100,111500])


def test_clock_offset_removed_once_from_model_delay():
    # Prediction at JSON-relative14.0; video switch at10.0; clock offset1.25.
    bias=source_bias(4,1.25)
    assert bias==2.75
    assert 14-bias==10+1.25
    assert 14-1.25-bias==10


@pytest.mark.parametrize('bracket,delta,bounds',[
    ([2,1],1,[0,2]),([1,2],3,[0,2]),([1,2],float('nan'),[0,2]),
    ([1,float('inf')],1,[0,2]),([1,2],1,[2,0]),
])
def test_reject_inconsistent_or_nonfinite_mapping(bracket,delta,bounds):
    with pytest.raises(ValueError):
        map_bracket(bracket,origin_ms=0,delta_s=delta,delta_bounds_s=bounds)
