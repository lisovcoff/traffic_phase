import numpy as np

from app.core.v9.fit import _fit_from_initial_labels


def test_refinement_preserves_strongly_observed_20_80_two_phase_cycle():
    # A fully observed unequal cycle must remain feasible even with equal
    # initial duration targets. Three cycles exercise internal duration limits;
    # the initial censored segment alone would not expose the former defect.
    time=np.arange(300)
    expected=(time%100>=20).astype(int)
    x=np.eye(2)[expected]
    fitted,_=_fit_from_initial_labels(x,expected,2,100.,{},1.,1,
        {'durations_s':[50.,50.]},None,None)
    assert np.array_equal(fitted['labels'],expected)
    assert fitted['segments']==[(0.,20.,0),(20.,100.,1),(100.,120.,0),
                                (120.,200.,1),(200.,220.,0),(220.,300.,1)]
