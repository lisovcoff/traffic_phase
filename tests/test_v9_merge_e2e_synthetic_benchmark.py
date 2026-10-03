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
        assert set(diagnostics["pairwise_cosine"]) >= {
            "p05",
            "p50",
            "p95",
        }
        assert set(diagnostics["pairwise_loss_per_cycle"]) >= {
            "p05",
            "p50",
            "p95",
        }
        assert set(diagnostics["fit_label_accuracy"]) >= {
            "p05",
            "p50",
            "p95",
        }
        assert set(diagnostics["oracle_pairwise_cosine"]) >= {
            "p05",
            "p50",
            "p95",
        }
        assert set(diagnostics["oracle_pairwise_loss_per_cycle"]) >= {
            "p05",
            "p50",
            "p95",
        }
        assert len(diagnostics["false_positive_cases"]) <= 25
        assert len(diagnostics["false_negative_cases"]) <= 25

    assert "oracle_policy_A" in report
    assert "oracle_threshold_grid" in report


def test_v9_redundancy_detector_handcrafted_internal_split() -> None:
    import numpy as np
    from app.core.v9.fit import evaluate_phase_redundancy

    labels = np.concatenate([
        np.zeros(20, dtype=np.int16),
        np.ones(20, dtype=np.int16),
        np.full(60, 2, dtype=np.int16),
    ])
    x = np.zeros((100, 4), dtype=np.float32)
    x[:20, 0] = 1.0
    x[20:40, 0] = 0.7
    x[:40, 1] = 0.8
    x[40:, 2] = 1.0
    x[40:, 3] = 0.7
    fit3 = {
        "probs": np.asarray([
            [0.80, 0.65, 0.02, 0.02],
            [0.60, 0.55, 0.02, 0.02],
            [0.02, 0.02, 0.70, 0.55],
        ]),
        "labels": labels,
        "segments": [
            (0.0, 20.0, 0),
            (20.0, 40.0, 1),
            (40.0, 100.0, 2),
        ],
        "pointwise_loglik": -50.0,
        "boundary_coherence": 0.40,
    }
    fit2 = {
        "probs": np.asarray([
            [0.70, 0.60, 0.02, 0.02],
            [0.02, 0.02, 0.70, 0.55],
        ]),
        "labels": np.where(labels == 2, 1, 0).astype(np.int16),
        "segments": [
            (0.0, 40.0, 0),
            (40.0, 100.0, 1),
        ],
        "pointwise_loglik": -51.0,
        "boundary_coherence": 0.80,
    }
    result = evaluate_phase_redundancy(
        fit3,
        fit2,
        x,
        100.0,
        {"a": [1.0], "b": [20.0], "c": [40.0]},
        cycles=1,
    )
    assert result["candidate_pair"] in ([0, 1], [1, 0])
    assert result["detected"] is True


def test_v9_redundancy_detector_preserves_distinct_templates() -> None:
    import numpy as np
    from app.core.v9.fit import evaluate_phase_redundancy

    labels = np.concatenate([
        np.zeros(30, dtype=np.int16),
        np.ones(30, dtype=np.int16),
        np.full(40, 2, dtype=np.int16),
    ])
    x = np.zeros((100, 6), dtype=np.float32)
    x[:30, 0] = 1.0
    x[30:60, 1] = 1.0
    x[60:, 2] = 1.0
    fit3 = {
        "probs": np.asarray([
            [0.85, 0.02, 0.02, 0.02, 0.02, 0.02],
            [0.02, 0.85, 0.02, 0.02, 0.02, 0.02],
            [0.02, 0.02, 0.85, 0.02, 0.02, 0.02],
        ]),
        "labels": labels,
        "segments": [
            (0.0, 30.0, 0),
            (30.0, 60.0, 1),
            (60.0, 100.0, 2),
        ],
        "pointwise_loglik": -40.0,
        "boundary_coherence": 0.90,
    }
    fit2 = {
        "probs": np.asarray([
            [0.70, 0.45, 0.45, 0.02, 0.02, 0.02],
            [0.02, 0.02, 0.02, 0.60, 0.02, 0.02],
        ]),
        "labels": np.where(labels == 2, 1, 0).astype(np.int16),
        "segments": [
            (0.0, 60.0, 0),
            (60.0, 100.0, 1),
        ],
        "pointwise_loglik": -52.0,
        "boundary_coherence": 0.85,
    }
    result = evaluate_phase_redundancy(
        fit3,
        fit2,
        x,
        100.0,
        {"a": [1.0], "b": [31.0], "c": [61.0]},
        cycles=1,
    )
    assert result["detected"] is False
