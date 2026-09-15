from __future__ import annotations

import numpy as np

from app.core.cycle_estimator import CycleEstimator


def _traffic_signal(period_s: float, *, duration_s: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(0.0, duration_s, 2.0)
    signal = (
        2.0
        + 1.2 * np.sin(2.0 * np.pi * t / period_s)
        + 0.35 * np.sin(4.0 * np.pi * t / period_s)
        + rng.normal(0.0, 0.15, size=len(t))
    )
    return np.clip(signal, 0.0, None)


def test_chicherina_regression_cycle_is_discovered_from_flow_signal():
    signal = _traffic_signal(120.0, duration_s=900.0, seed=42)

    estimate = CycleEstimator().estimate(signal, sampling_seconds=2.0)

    assert 112.0 <= estimate.cycle_seconds <= 128.0
    assert estimate.confidence > 0.20
    assert len(estimate.candidate_periods) >= 2
    assert all(candidate.strength > 0 for candidate in estimate.candidate_periods)
    assert all(candidate.repetitions >= 4 for candidate in estimate.candidate_periods[:2])


def test_lenina_sverdlovsky_regression_cycle_is_discovered_from_flow_signal():
    signal = _traffic_signal(100.0, duration_s=900.0, seed=7)

    estimate = CycleEstimator().estimate(signal, sampling_seconds=2.0)

    assert 92.0 <= estimate.cycle_seconds <= 108.0
    assert estimate.confidence > 0.20
    assert estimate.candidate_periods[0].score >= estimate.candidate_periods[-1].score


def test_estimator_does_not_accept_a_cycle_as_an_input_argument():
    estimator = CycleEstimator(min_period_seconds=20.0, max_period_seconds=180.0)

    signal = _traffic_signal(120.0, duration_s=720.0, seed=13)
    estimate = estimator.estimate(signal, sampling_seconds=2.0)

    assert 20.0 <= estimate.cycle_seconds <= 180.0
