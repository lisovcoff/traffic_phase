from scripts.v9_merge_e2e_synthetic_benchmark import BenchmarkConfig, run_benchmark


def test_v9_e2e_synthetic_benchmark_is_deterministic():
    config = BenchmarkConfig(cases_per_class=8, seed=20261003)
    first = run_benchmark(config)
    second = run_benchmark(config)
    assert first == second


def test_v9_e2e_synthetic_benchmark_has_valid_rates():
    report = run_benchmark(BenchmarkConfig(cases_per_class=4, seed=20261003))
    policy = report["policy_A"]
    assert 0.0 <= policy["true2_merge_recall"] <= 1.0
    assert 0.0 <= policy["true3_false_merge_rate"] <= 1.0
    assert 0.0 <= policy["balanced_accuracy"] <= 1.0
