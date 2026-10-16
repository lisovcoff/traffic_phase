"""Independent exhaustive oracle for the existing finite HSMM objective.

Not a new observation model: Bernoulli templates and all duration bounds fixed.
First observed segment: 2..max bins, no duration penalty (existing left censoring).
Later segments: their OWN duration range/penalty, positive predecessor length.
Last segment remains uncensored here, as in the current production model.
"""
import math

import numpy as np
import pytest

from app.core.v9.decoder import decode_cyclic_hsmm, _duration_penalty


def oracle(x, probs, *, dt, targets, minimum, maximum, min_factor, max_factor,
           initial, penalty_strength=2., transition=.25):
    n, k = len(x), len(probs)
    targets = np.maximum(2., np.asarray(targets))
    lower_s = np.maximum(minimum, min_factor*targets)
    upper_s = np.maximum(np.minimum(maximum, max_factor*targets), lower_s+1.)
    lower = np.maximum(2, np.round(lower_s/dt).astype(int))
    upper = np.maximum(lower+1, np.round(upper_s/dt).astype(int))
    emission = x@np.log(probs).T+(1-x)@np.log1p(-probs).T
    best_score, best_segments = -math.inf, None

    def walk(start, z, score, segments):
        nonlocal best_score, best_segments
        allowed = range(2 if not segments else lower[z], min(upper[z], n-start)+1)
        for duration in allowed:
            end = start+duration
            new_score = score+float(emission[start:end, z].sum())
            if segments:
                sigma = max(4., .25*targets[z])
                new_score -= penalty_strength*((duration*dt-targets[z])/sigma)**2+transition
            path = [*segments, (start*dt, end*dt, z)]
            if end == n:
                if new_score > best_score:
                    best_score, best_segments = new_score, path
            else:
                walk(end, (z+1)%k, new_score, path)
    for z in range(k) if initial is None else [initial]:
        walk(0, z, 0., [])
    return best_score, best_segments


@pytest.mark.parametrize('lengths', [(2, 8), (2, 8, 3), (3, 7, 2)])
def test_short_predecessor_does_not_inherit_next_phase_minimum(lengths):
    k = len(lengths)
    labels = np.repeat(np.arange(k), lengths)
    x = np.eye(k)[labels]
    probs = np.eye(k)*.96+.02
    actual, score, segments, _ = decode_cyclic_hsmm(x, probs, sum(lengths), k,
        duration_targets=lengths, initial_phase=0, min_duration_s=2,
        max_duration_s=20, duration_min_factor=1., duration_max_factor=1.)
    np.testing.assert_array_equal(actual, labels)
    expected, path = oracle(x, probs, dt=1., targets=lengths, minimum=2., maximum=20.,
                            min_factor=1., max_factor=1., initial=0)
    assert score == pytest.approx(expected)
    assert segments == path


@pytest.mark.parametrize('dt', [.5, 1., 2.])
@pytest.mark.parametrize('k,initial', [(2, 0), (2, None), (3, 0), (3, None)])
def test_matches_independent_exhaustive_objective(dt, k, initial):
    rng = np.random.default_rng(20261016+k)
    x = rng.integers(0, 2, size=(16, k)).astype(float)
    probs = rng.uniform(.08, .92, size=(k, k))
    targets = [3., 6., 4.][:k]
    options = dict(dt=dt, duration_targets=targets, min_duration_s=2., max_duration_s=12.,
                   duration_min_factor=.5, duration_max_factor=1.4, initial_phase=initial)
    expected, _ = oracle(x, probs, dt=dt, targets=targets, minimum=2., maximum=12.,
                          min_factor=.5, max_factor=1.4, initial=initial)
    if not math.isfinite(expected):
        with pytest.raises(RuntimeError, match='valid cyclic segmentation'):
            decode_cyclic_hsmm(x, probs, sum(targets), k, **options)
        return
    _, score, _, _ = decode_cyclic_hsmm(x, probs, sum(targets), k, **options)
    assert score == pytest.approx(expected, abs=1e-9)


def test_duration_penalty_uses_seconds_instead_of_bin_numbers():
    # Six seconds is the same target at every sampling resolution.
    for dt in (.5, 1., 2.):
        labels = np.repeat([0, 1], [int(2/dt), int(6/dt)])
        if int(2/dt) < 2:
            continue  # unchanged minimum two bins for the first observed segment
        x = np.eye(2)[labels]
        probs = np.array([[.98, .02], [.02, .98]])
        _, score, _, _ = decode_cyclic_hsmm(x, probs, 12, 2, dt=dt,
            duration_targets=[6, 6], initial_phase=0, min_duration_s=2,
            max_duration_s=12, duration_min_factor=.5, duration_max_factor=1.5)
        emission = float((x*np.log(probs[labels])+(1-x)*np.log1p(-probs[labels])).sum())
        assert score == pytest.approx(emission-.25)


def test_deadline_still_abstains_without_a_result():
    with pytest.raises(TimeoutError):
        decode_cyclic_hsmm(np.ones((16, 2)), np.full((2, 2), .5), 12, 2, deadline_monotonic=0.)
