from scripts.v9_merge_e2e_synthetic_benchmark import BenchmarkConfig, run_benchmark


def test_v9_e2e_synthetic_benchmark_is_deterministic():
    config = BenchmarkConfig(cases_per_class=4, seed=20261003)
    first = run_benchmark(config)
    second = run_benchmark(config)
    assert first == second


def test_v9_e2e_synthetic_benchmark_exposes_case_level_diagnostics():
    report = run_benchmark(
        BenchmarkConfig(cases_per_class=5, seed=20261003)
    )
    assert report["classes"]["true2_overfit"] == 5
    assert report["classes"]["true3_distinct"] == 5
    for group in ("true2", "true3"):
        diagnostics = report["diagnostics"][group]
        assert diagnostics["case_count"] == 5
        assert set(diagnostics["pairwise_cosine"]) >= {"p05", "p50", "p95"}
        assert set(diagnostics["pairwise_loss_per_cycle"]) >= {"p05", "p50", "p95"}
    assert report["redundancy_policy"]["method"] == "topological_temporal_redundancy_v5"


def _cyclic_labels(boundaries):
    import numpy as np

    segments = []
    labels = []
    for cycle, (b1, b2) in enumerate(boundaries):
        base = cycle * 100
        segments.extend([
            (float(base), float(base + b1), 0),
            (float(base + b1), float(base + b2), 1),
            (float(base + b2), float(base + 100), 2),
        ])
        labels.extend([0] * b1)
        labels.extend([1] * (b2 - b1))
        labels.extend([2] * (100 - b2))
    return np.asarray(labels, dtype=np.int16), segments


def test_v9_redundancy_detector_uses_circular_incoherence_and_contrast():
    import numpy as np
    from app.core.v9.fit import evaluate_phase_redundancy

    labels, segments = _cyclic_labels([
        (8, 60), (24, 60), (40, 60), (56, 60),
        (72, 60), (88, 60), (16, 60), (32, 60),
    ])
    rng = np.random.default_rng(123)
    phase_probs = np.asarray([
        [0.90, 0.75, 0.04, 0.03],
        [0.68, 0.58, 0.05, 0.03],
        [0.03, 0.04, 0.88, 0.76],
    ])
    x = (
        rng.random((len(labels), 4))
        < phase_probs[labels]
    ).astype(np.float32)
    assert x.shape[0] == labels.shape[0]
    result = evaluate_phase_redundancy(
        {
            "probs": phase_probs,
            "labels": labels,
            "segments": segments,
            "pointwise_loglik": -1000.0,
        },
        None,
        x,
        100.0,
        cycles=8,
    )
    candidate = next(
        row for row in result["pairs"]
        if row["pair"] == [0, 1]
    )
    assert candidate["directional_exclusivity"] > 0.80
    assert candidate["boundary_observations"] == 8
    assert candidate["boundary_raw_r"] < 0.70
    assert candidate["contrast_gap_ratio"] < 0.25
    assert candidate["child_to_parent_signal_mass_ratio"] <= 0.85
    assert result["candidate_pair"] == [0, 1]
    assert result["detected"] is True


def test_v9_redundancy_detector_rejects_stable_distinct_phases():
    import numpy as np
    from app.core.v9.fit import evaluate_phase_redundancy

    labels, segments = _cyclic_labels([
        (30, 60), (30, 60), (30, 60), (30, 60),
        (30, 60), (30, 60), (30, 60), (30, 60),
    ])
    rng = np.random.default_rng(456)
    phase_probs = np.asarray([
        [0.88, 0.78, 0.03, 0.03],
        [0.82, 0.72, 0.03, 0.03],
        [0.03, 0.03, 0.88, 0.76],
    ])
    x = (
        rng.random((len(labels), 4))
        < phase_probs[labels]
    ).astype(np.float32)
    assert x.shape[0] == labels.shape[0]
    result = evaluate_phase_redundancy(
        {
            "probs": phase_probs,
            "labels": labels,
            "segments": segments,
            "pointwise_loglik": -1000.0,
        },
        None,
        x=x,
        period=100.0,
        cycles=8,
    )
    assert result["detected"] is False
    candidate = next(
        row for row in result["pairs"]
        if row["pair"] == result["candidate_pair"]
    )
    assert candidate["child_to_parent_signal_mass_ratio"] > 0.85


def test_v9_redundancy_detector_wraps_correctly_at_zero_over_period():
    from app.core.v9.fit import _boundary_circular_stats

    fit = {
        "segments": [
            (0.0, 98.0, 0),
            (98.0, 150.0, 1),
            (150.0, 200.0, 2),
            (200.0, 202.0, 0),
            (202.0, 250.0, 1),
            (250.0, 300.0, 2),
            (300.0, 398.0, 0),
            (398.0, 450.0, 1),
            (450.0, 500.0, 2),
            (500.0, 502.0, 0),
            (502.0, 550.0, 1),
            (550.0, 600.0, 2),
            (600.0, 698.0, 0),
            (698.0, 750.0, 1),
            (750.0, 800.0, 2),
            (800.0, 802.0, 0),
            (802.0, 850.0, 1),
            (850.0, 900.0, 2),
        ]
    }
    stats = _boundary_circular_stats(fit, 100.0)
    assert stats[(0, 1)]["observations"] == 6
    assert stats[(0, 1)]["raw_r"] > 0.90
    assert stats[(0, 1)]["reliable"] is True


def test_v9_boundary_mrl_is_not_trusted_with_few_observations():
    import math

    from app.core.v9.fit import _boundary_circular_stats

    fit = {
        "segments": [
            (0.0, 25.0, 0),
            (25.0, 50.0, 1),
            (50.0, 100.0, 2),
            (100.0, 125.0, 0),
            (125.0, 150.0, 1),
            (150.0, 200.0, 2),
            (200.0, 225.0, 0),
            (225.0, 250.0, 1),
        ]
    }
    stats = _boundary_circular_stats(fit, 100.0)
    assert stats[(0, 1)]["observations"] == 3
    assert stats[(0, 1)]["reliable"] is False
    expected = (3.0 * 1.0 + 6.0 * 0.5) / 9.0
    assert math.isclose(
        stats[(0, 1)]["regularized_r"],
        expected,
        rel_tol=1e-9,
    )
