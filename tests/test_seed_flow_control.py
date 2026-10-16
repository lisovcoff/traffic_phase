import pytest

from scripts.seed_flow_review import numerically_equal


def test_numerical_control_accepts_only_predeclared_roundoff():
    before = {'boundaries': [10., 30.], 'count': 2, 'valid': True}
    roundoff = {'boundaries': [10., 30.+7.105427357601002e-15], 'count': 2, 'valid': True}
    different = {'boundaries': [10., 30.+1e-8], 'count': 2, 'valid': True}
    assert numerically_equal(before, roundoff)
    assert not numerically_equal(before, different)
    assert not numerically_equal(before, {**before, 'count': 3})
    assert not numerically_equal(before, {**before, 'valid': 1})


@pytest.mark.parametrize('invalid', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_diagnostics_cannot_pass_control(invalid):
    assert not numerically_equal({'value': invalid}, {'value': invalid})
