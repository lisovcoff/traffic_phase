"""Small independent counterexamples; no real annotations or fitted thresholds.

Split visitation and coherent scores (D1-D3) are fixed. Strict xfails retain
the other observed defects without silently treating them as regressions fixed.
"""
from unittest.mock import patch

import numpy as np
import pytest

from app.core.v9 import fit
from app.core.v9.decoder import _segments_from_labels
from app.core.v9.events import periodic_baseline_from_segments
from app.core.v9.primitives import fit_bernoulli_templates, _pointwise_loglik


@pytest.mark.parametrize("dt", [0.5, 1.0, 2.0])
def test_both_distinct_internal_splits_reach_template_fit_and_refinement(dt):
    # A 24-bin cycle with two possible half-cycle parents; no stream seed view.
    labels = np.tile(np.repeat([0, 1, 2], [6, 6, 12]), 2)
    x = np.eye(3)[labels]
    visited_seed, visited_refine = [], []
    original = fit._seed_labels_to_fit

    def seed(*args):
        visited_seed.append((args[6]["source"], args[6].get("split_parent_phase")))
        return original(*args)

    def refine(*args):
        visited_refine.append((args[7]["source"], args[7].get("split_parent_phase")))
        raise RuntimeError("refinement deliberately unavailable; seed must survive")

    with patch.object(fit, "_seed_labels_to_fit", seed), patch.object(fit, "_fit_from_initial_labels", refine):
        result = fit.em_fit(x, 24 * dt, 3, dt=dt)
    required = {( "two_phase_internal_split_seed", parent) for parent in (0, 1)}
    assert required <= set(visited_seed)
    assert required <= set(visited_refine)
    assert sum(c["source"] == "two_phase_internal_split_seed" for c in result["initialization_candidates"]) == 2


def test_duplicate_split_not_refitted_and_existing_k2_path_unchanged():
    # At K3 the first split of [0000 1111] equals [00 11 2222].
    x = np.eye(3)[np.tile([0, 0, 1, 1, 2, 2, 2, 2], 3)]
    duplicate = np.tile([0, 0, 1, 1, 2, 2, 2, 2], 3)
    visited = []

    def stream_seed(streams, period, k, n, dt):
        return duplicate, {"durations_s": [2., 2., 4.]}

    def refine(*args):
        visited.append(tuple(args[1]))
        raise RuntimeError("structural test")

    with patch.object(fit, "initial_seed_from_streams", stream_seed), patch.object(fit, "initial_offset_search", return_value=0.), patch.object(fit, "_fit_from_initial_labels", refine):
        fit.em_fit(x, 8., 3, by_stream_global={"a": [0.]})
    assert visited.count(tuple(duplicate)) == 1
    visited.clear()
    with patch.object(fit, "_fit_from_initial_labels", refine):
        result = fit.em_fit(x, 8., 2)
    assert len(visited) == 1
    assert [c["source"] for c in result["initialization_candidates"]] == ["equal_duration_offset_search"]


def test_split_candidates_complete_real_refinement():
    labels = np.tile(np.repeat([0, 1, 2], [6, 6, 12]), 2)
    x = np.eye(3)[labels]
    completed = []
    original = fit._fit_from_initial_labels

    def refine(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[7]['source'] == 'two_phase_internal_split_seed':
            completed.append(args[7]['split_parent_phase'])
        return result

    with patch.object(fit, '_fit_from_initial_labels', refine):
        result = fit.em_fit(x, 24., 3, iterations=2)
    assert completed == [0, 1]
    assert result['segments'] == _segments_from_labels(result['labels'])


def objective_for_returned_model(x, payload):
    # Independent sum of the documented objective; no decoder utility calls.
    total = float(np.sum(x * np.log(payload["probs"][payload["labels"]]) +
                         (1 - x) * np.log(1 - payload["probs"][payload["labels"]])))
    targets = payload["decoder_info"]["duration_targets_s"]
    for a, b, z in payload["segments"][1:]:
        target = max(2., targets[z])
        total -= 2 * ((b - a - target) / max(4., .25 * target)) ** 2 + .25
    return total


def test_refinement_score_describes_returned_model():
    truth = np.tile(np.repeat([0, 1], [6, 14]), 3)
    x = np.eye(2)[truth]
    initial = np.tile(np.repeat([0, 1], 10), 3)
    payload, _ = fit._fit_from_initial_labels(x, initial, 2, 20., None, 1., 1,
                                              {"durations_s": [10., 10.]}, None, None)
    assert payload["score"] == pytest.approx(objective_for_returned_model(x, payload))


def test_same_path_and_templates_have_same_k_selection_objective():
    labels = np.tile(np.repeat([0, 1], 10), 2)
    x = np.eye(2)[labels]
    info = {"durations_s": [10., 10.]}
    seed = fit._seed_labels_to_fit(labels, x, 2, 20., None, 1., info, None, None)
    refined, _ = fit._fit_from_initial_labels(x, labels, 2, 20., None, 1., 1, info, None, None)
    assert np.array_equal(seed["labels"], refined["labels"])
    assert np.array_equal(seed["probs"], refined["probs"])
    seed.update(k=2, score=seed["pointwise_loglik"])
    refined["k"] = 2
    assert fit.candidate_metrics(seed, x.shape)["approx_bic"] == pytest.approx(
        fit.candidate_metrics(refined, x.shape)["approx_bic"])


def captured_ensemble(shift):
    captured = []
    n, period = 200, 100.
    original = fit._seed_labels_to_fit
    onsets = [[(a + shift) % period for a in values] for values in ([1., 51.], [49., 99.])]

    def make_seed(values):
        a, b = sorted(values)
        labels = (((np.arange(n) - a) % period) >= b - a).astype(int)
        return labels, {"group_onsets_s": [a, b], "durations_s": [b-a, period-b+a]}

    def capture(*args):
        if args[6]["source"] == "release_entry_seed_ensemble":
            captured.extend(args[6]["group_onsets_s"])
        return original(*args)

    with patch.object(fit, "initial_seed_from_streams", side_effect=[make_seed(v) for v in onsets]), patch.object(fit, "_seed_labels_to_fit", capture), patch.object(fit, "_fit_from_initial_labels", side_effect=RuntimeError("isolate seeds")):
        fit.em_fit(np.zeros((n, 2)), period, 2, by_stream_global={}, entry_streams={})
    return sorted((v-shift) % period for v in captured)


@pytest.mark.xfail(strict=True, reason="sorted zip and linear mean are not circular-origin equivariant")
def test_ensemble_invariant_to_common_time_origin():
    assert captured_ensemble(0.) == pytest.approx(captured_ensemble(10.))


@pytest.mark.xfail(strict=True, reason="ensemble unconditionally suppresses unrefined release and entry")
def test_ensemble_cannot_discard_arbitrarily_better_release_fit():
    labels = np.tile(np.repeat([0, 1], 5), 2)
    seeds = [(labels, {"group_onsets_s": [0., 5.], "durations_s": [5., 5.]}),
             (1-labels, {"group_onsets_s": [2., 7.], "durations_s": [5., 5.]})]

    def quality_fixture(labels, x, k, period, streams, dt, info, grid, values):
        ll = {"robust_release_seed": -2., "entry_seed": -4.,
              "release_entry_seed_ensemble": -8., "equal_duration_offset_search": -9.}[info["source"]]
        return dict(labels=labels, probs=np.full((2, 2), .5), segments=_segments_from_labels(labels),
                    pointwise_loglik=ll, coherence=0., seed_info=info)

    with patch.object(fit, "initial_seed_from_streams", side_effect=seeds), patch.object(fit, "_seed_labels_to_fit", quality_fixture), patch.object(fit, "_fit_from_initial_labels", side_effect=RuntimeError("isolate selection")):
        result = fit.em_fit(np.zeros((20, 2)), 10., 2, by_stream_global={}, entry_streams={})
    assert result["initialization"]["source"] == "robust_release_seed"


@pytest.mark.xfail(strict=True, reason="distinct shared-movement combinations need not have exclusive streams")
def test_distinct_shared_signatures_are_not_multiple_unsupported_phases():
    labels = np.tile(np.repeat(np.arange(3), 10), 3)
    # Three pairwise-distinct, perfectly observable signatures AB, AC, BC.
    x = np.array([[1, 1, 0], [1, 0, 1], [0, 1, 1]])[labels]
    probs = fit_bernoulli_templates(x, labels, 3)
    result = fit._phase_support_metrics({"k": 3, "probs": probs})
    assert result["supported_phase_count"] == 3


@pytest.mark.xfail(strict=True, reason="argsort(argsort) gives unequal ranks to ties")
def test_redundancy_rank_feature_invariant_to_stream_permutation():
    a, b = np.array([1., 1., 0.]), np.array([1., 0., 1.])
    permutation = [1, 0, 2]
    assert fit._rank_correlation(a, b) == pytest.approx(fit._rank_correlation(a[permutation], b[permutation]))


@pytest.mark.xfail(strict=True, reason="tied ranks change redundancy decision after mere column permutation")
def test_redundancy_decision_invariant_on_binary_shared_occupancy():
    labels = np.tile(np.repeat(np.arange(3), [40, 40, 80]), 3)
    counts = np.array([[1, 1, 2, 2, 0], [1, 2, 1, 2, 0], [0, 0, 0, 0, 4]])
    x = ((np.arange(len(labels)) % 5)[:, None] < counts[labels]).astype(float)

    def model(z, k):
        p = fit_bernoulli_templates(x, z, k)
        return dict(k=k, labels=z, probs=p, segments=_segments_from_labels(z),
                    pointwise_loglik=_pointwise_loglik(x, p, z))

    f3, f2 = model(labels, 3), model((labels == 2).astype(int), 2)
    results = []
    for permutation in ([1, 3, 0, 2, 4], [0, 2, 1, 3, 4]):
        results.append(fit.evaluate_phase_redundancy(
            {**f3, 'probs': f3['probs'][:, permutation]},
            {**f2, 'probs': f2['probs'][:, permutation]}, x[:, permutation], 160.))
    assert all(r['supported_phase_count'] == 3 for r in results)
    assert results[0]['detected'] == results[1]['detected']


@pytest.mark.xfail(strict=True, reason="left-censored segment start is counted as a phase onset")
def test_periodic_baseline_ignores_censored_start():
    # Exact periodic path, window begins halfway through phase 0.
    segments = [(0., 10., 0), (10., 30., 1), (30., 50., 0), (50., 70., 1), (70., 80., 0)]
    _, centers = periodic_baseline_from_segments(segments, 40., 80.)
    assert centers[0] == pytest.approx(30.)
    assert centers[1] == pytest.approx(10.)
