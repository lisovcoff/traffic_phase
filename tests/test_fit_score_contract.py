"""Independent score sums, snapshot consistency and source-independent criteria."""
from unittest.mock import patch

import numpy as np
import pytest

from app.core.v9 import fit
from app.core.v9.decoder import _segments_from_labels


def data_sum(x, probs, labels):
    p = probs[labels]
    return float(np.sum(x*np.log(p)+(1-x)*np.log(1-p)))


def objective_sum(x, payload):
    value = data_sum(x, payload['probs'], payload['labels'])
    for a, b, z in payload['segments'][1:]:
        target = max(2., payload['decoder_info']['duration_targets_s'][z])
        value -= 2*((b-a-target)/max(4., .25*target))**2+.25
    return value


@pytest.mark.parametrize('dt', [.5, 1., 2.])
@pytest.mark.parametrize('k', [2, 3])
def test_refined_snapshot_equals_independent_sum_without_extra_decode(dt, k):
    truth = np.tile(np.repeat(np.arange(k), [6]+[14]*(k-1)), 3)
    x = np.eye(k)[truth]
    period = (6+14*(k-1))*dt
    initial = fit.phase_labels_for_time(len(x), dt, period, k, 0.)
    x0, initial0 = x.copy(), initial.copy()
    with patch.object(fit, 'decode_cyclic_hsmm', wraps=fit.decode_cyclic_hsmm) as decoder:
        payload, history = fit._fit_from_initial_labels(
            x, initial, k, period, None, dt, 2,
            {'durations_s':[period/k]*k}, None, None)
    assert decoder.call_count == len(history) <= 2
    assert payload['score'] == pytest.approx(objective_sum(x, payload), abs=1e-9)
    assert payload['data_loglik'] == payload['pointwise_loglik'] == data_sum(x, payload['probs'], payload['labels'])
    assert payload['penalized_objective'] == payload['score']
    assert payload['score'] == max(h['loglik_with_duration_penalty'] for h in history)
    assert payload['segments'] == _segments_from_labels(payload['labels'], dt)
    assert np.array_equal(x, x0) and np.array_equal(initial, initial0)


def test_best_iteration_uses_returned_parameters_not_stale_decoder_ranking():
    labels = np.tile(np.repeat([0, 1], 10), 2).astype(np.int16)
    x = np.eye(2)[labels]
    templates = [np.array([[p,1-p],[1-p,p]]) for p in (.99,.6,.9)]
    # Controlled M-step snapshots reverse the stale decoder ranking. The fake
    # decoder still returns the exact objective for its input parameters/path.
    def decode(x, probs, period, k, **kwargs):
        return labels.copy(), data_sum(x, probs, labels)-.75, _segments_from_labels(labels), {
            'duration_targets_s':[10.,10.]}
    with patch.object(fit,'fit_bernoulli_templates',side_effect=templates), patch.object(fit,'decode_cyclic_hsmm',side_effect=decode):
        payload, history = fit._fit_from_initial_labels(
            x, labels, 2, 20., None, 1., 2, {'durations_s':[10.,10.]}, None, None)
    assert history[0]['decoder_input_objective'] > history[1]['decoder_input_objective']
    assert history[0]['loglik_with_duration_penalty'] < history[1]['loglik_with_duration_penalty']
    assert np.array_equal(payload['probs'],templates[2])
    assert payload['score'] == pytest.approx(objective_sum(x,payload))


@pytest.mark.parametrize('refine', [False, True])
def test_public_score_is_data_likelihood_with_penalty_separate(refine):
    x = np.eye(2)[np.tile(np.repeat([0,1],10),3)]
    context = (patch.object(fit,'_fit_quality',side_effect=lambda f,*a: 1. if 'score' in f else 0.)
               if refine else patch.object(fit,'_fit_from_initial_labels',side_effect=RuntimeError('seed only')))
    with context:
        result = fit.em_fit(x,20.,2,iterations=1)
    assert result['score_semantics'] == 'data_loglik'
    assert result['score'] == result['data_loglik'] == result['pointwise_loglik'] == data_sum(x,result['probs'],result['labels'])
    assert (result['penalized_objective'] is not None) == refine
    assert (result['decoder_input_objective'] is not None) == refine


def test_candidate_does_not_guess_a_score_only_models_likelihood():
    with pytest.raises(KeyError, match='pointwise_loglik'):
        fit.candidate_metrics({'k':2,'score':-3.},(20,2))


def test_candidate_criterion_ignores_decoder_penalty_and_keeps_complexity_formula():
    model = dict(k=2, data_loglik=-12., pointwise_loglik=-12.,score=-999.,
                 probs=np.eye(2)*.8+.1,segments=[(0.,10.,0),(10.,20.,1)])
    first = fit.candidate_metrics(model,(20,2))
    second = fit.candidate_metrics({**model,'score':-1234.,'penalized_objective':-555.},(20,2))
    assert first['objective'] == second['objective'] == -12.
    assert first['approx_bic'] == second['approx_bic'] == pytest.approx(24+4*np.log(40))
    assert first['objective_semantics'] == 'returned_model_data_loglik'
    legacy = {k:v for k,v in model.items() if k!='data_loglik'}
    assert fit.candidate_metrics(legacy,(20,2))['approx_bic'] == first['approx_bic']
