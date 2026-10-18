"""Anchor scoring must depend on phase identities, not segment row numbers."""
import numpy as np
import pytest

from app.core.v9.model import _calibrate_phase_anchor


def calibration(baseline, probabilities):
    return _calibrate_phase_anchor(
        {"a": np.arange(5., 600., 60.), "b": np.arange(35., 600., 60.)},
        ["a", "b"], probabilities, baseline, 60., 0.,
    )


@pytest.mark.parametrize("cycles", [1, 2, 5])
def test_renaming_phase_ids_cannot_shift_an_already_aligned_archive(cycles):
    baseline = [(60.*c, 60.*c+30., 0) for c in range(cycles)]
    baseline += [(60.*c+30., 60.*c+60., 1) for c in range(cycles)]
    baseline.sort()
    probabilities = np.array([[.99, .01], [.01, .99]])
    original = calibration(baseline, probabilities)
    renamed = calibration([(a, b, 1-z) for a, b, z in baseline], probabilities[::-1])
    assert not original["applied"]
    assert not renamed["applied"]
    assert renamed["initial_score"] == pytest.approx(original["initial_score"])
    assert renamed["best_score"] == pytest.approx(original["best_score"])


def test_censored_first_phase_and_repeated_phase_rows_keep_their_own_templates():
    baseline = [(0., 10., 1), (10., 40., 0), (40., 70., 1),
                (70., 100., 0), (100., 120., 1)]
    evidence = {"a": np.arange(15., 600., 60.), "b": np.arange(45., 600., 60.)}
    result = _calibrate_phase_anchor(evidence, ["a", "b"],
        [[.99, .01], [.01, .99]], baseline, 60., 0.)
    assert not result["applied"]
    assert result["initial_score"] == pytest.approx(20*np.log(.99))
