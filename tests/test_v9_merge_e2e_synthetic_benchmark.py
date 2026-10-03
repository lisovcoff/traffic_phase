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


def test_v9_redundancy_probe_report(capsys):
    report = run_benchmark(BenchmarkConfig(cases_per_class=40, seed=20261003))
    print(report["redundancy_policy"])
    assert 0.0 <= report["redundancy_policy"]["balanced_accuracy"] <= 1.0
