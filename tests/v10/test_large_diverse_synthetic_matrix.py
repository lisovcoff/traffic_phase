from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from collections import Counter

import numpy as np

from app.core.v10.automatic_physical import infer_physical_signal_plan


MOVEMENTS = tuple(
    f"{source}->{target}"
    for source in "NSEW"
    for target in "NSEW"
    if source != target
)

RIGHT_TURNS = {"N->W", "W->S", "S->E", "E->N"}
LEFT_TURNS = {"N->E", "E->S", "S->W", "W->N"}


def _profile(
    phases: list[tuple[str, float, dict[str, float]]],
    *,
    seed: int,
    noise: float,
    samples: int,
) -> tuple[dict[str, object], dict[str, set[str]]]:
    rng = np.random.default_rng(seed)
    names = [name for name, _duration, _values in phases]
    period = sum(duration for _name, duration, _values in phases)
    durations = {name: duration for name, duration, _values in phases}

    activity: dict[str, dict[str, float]] = {
        name: {} for name in names
    }
    union = sorted(
        {
            movement
            for _name, _duration, values in phases
            for movement in values
        }
    )
    truth: dict[str, set[str]] = {
        name: set(values)
        for name, _duration, values in phases
    }

    for phase_name, _duration, values in phases:
        for movement in union:
            target = float(values.get(movement, 0.01))
            # Binomial sampling models finite traffic counts; an additive term
            # models detector/probability noise without making red phases huge.
            n = max(30, int(samples * (0.8 + 0.4 * rng.random())))
            observed = float(rng.binomial(n, min(0.999, target)) / n)
            observed += float(rng.normal(0.0, noise))
            activity[phase_name][movement] = float(
                np.clip(max(0.01, observed), 0.01, 0.95)
            )

    # Keep the low background floor used by real V9 outputs. This prevents a
    # sampled zero from being interpreted as a new hard absence.
    rows = []
    for movement in union:
        rows.append(
            {
                "stream": movement,
                "event_probability_by_phase": {
                    name: round(activity[name].get(movement, 0.01), 6)
                    for name in names
                },
            }
        )

    cursor = 0.0
    segments = []
    for index, (name, duration, _values) in enumerate(phases):
        segments.append([cursor, cursor + duration, index])
        cursor += duration

    result = {
        "schedule": {
            "phase_names": names,
            "phase_count": len(names),
            "period_s": period,
            "baseline_duration_targets_s": durations,
            "baseline_segments": segments,
            "stream_activity_by_phase": rows,
        }
    }
    return result, truth


def _physical_signatures(plan: dict[str, object]) -> set[frozenset[str]]:
    return {
        frozenset(phase["green_movements"])
        for phase in plan["phases"]
    }


def _topology_arrows(plan: dict[str, object]) -> set[str]:
    return {
        movement
        for value in plan["topology"].values()
        for movement in value["arrows"]
    }


def _scenario_catalog() -> list[tuple[str, list[tuple[str, float, dict[str, float]]], dict[str, set[str]]]]:
    return [
        (
            "two_phase_balanced",
            [
                ("A", 50.0, {"E->W": 0.35, "W->E": 0.34}),
                ("B", 50.0, {"N->S": 0.34, "S->N": 0.33}),
            ],
            {"A": {"E->W", "W->E"}, "B": {"N->S", "S->N"}},
        ),
        (
            "two_phase_permissive_turn_noise",
            [
                (
                    "A",
                    50.0,
                    {
                        "E->W": 0.38,
                        "W->E": 0.34,
                        "N->E": 0.08,
                        "E->N": 0.06,
                        "W->N": 0.04,
                    },
                ),
                (
                    "B",
                    50.0,
                    {
                        "N->S": 0.36,
                        "S->N": 0.34,
                        "N->E": 0.07,
                        "E->N": 0.05,
                        "S->E": 0.04,
                    },
                ),
            ],
            {"A": {"E->W", "W->E"}, "B": {"N->S", "S->N"}},
        ),
        (
            "three_phase_ns_turn_asymmetric",
            [
                (
                    "A",
                    30.0,
                    {"N->S": 0.46, "N->E": 0.13, "E->N": 0.05},
                ),
                ("B", 45.0, {"N->S": 0.28, "S->N": 0.39}),
                ("C", 25.0, {"E->W": 0.34, "W->E": 0.31}),
            ],
            {
                "A": {"N->S", "N->E", "E->N"},
                "B": {"N->S", "S->N"},
                "C": {"E->W", "W->E"},
            },
        ),
        (
            "three_phase_ns_turn_symmetric",
            [
                (
                    "A",
                    24.0,
                    {"N->S": 0.44, "N->E": 0.10, "E->N": 0.10},
                ),
                ("B", 48.0, {"N->S": 0.25, "S->N": 0.43}),
                ("C", 28.0, {"E->W": 0.36, "W->E": 0.35}),
            ],
            {
                "A": {"N->S", "N->E", "E->N"},
                "B": {"N->S", "S->N"},
                "C": {"E->W", "W->E"},
            },
        ),
        (
            "three_phase_ew_turn",
            [
                (
                    "A",
                    26.0,
                    {"E->W": 0.44, "E->S": 0.12, "W->N": 0.08},
                ),
                ("B", 46.0, {"E->W": 0.24, "W->E": 0.42}),
                ("C", 28.0, {"N->S": 0.34, "S->N": 0.31}),
            ],
            {
                "A": {"E->W", "E->S", "W->N"},
                "B": {"E->W", "W->E"},
                "C": {"N->S", "S->N"},
            },
        ),
        (
            "four_phase_opposed_left_turns",
            [
                ("A", 18.0, {"N->E": 0.42, "S->W": 0.39}),
                ("B", 32.0, {"N->S": 0.37, "S->N": 0.35}),
                ("C", 18.0, {"E->S": 0.40, "W->N": 0.36}),
                ("D", 32.0, {"E->W": 0.34, "W->E": 0.33}),
            ],
            {
                "A": {"N->E", "S->W"},
                "B": {"N->S", "S->N"},
                "C": {"E->S", "W->N"},
                "D": {"E->W", "W->E"},
            },
        ),
        (
            "three_phase_single_protected_turn",
            [
                ("A", 22.0, {"N->S": 0.45, "N->E": 0.13}),
                ("B", 48.0, {"N->S": 0.28, "S->N": 0.42}),
                ("C", 30.0, {"E->W": 0.35, "W->E": 0.33}),
            ],
            {
                "A": {"N->S", "N->E"},
                "B": {"N->S", "S->N"},
                "C": {"E->W", "W->E"},
            },
        ),
        (
            "four_phase_right_turns",
            [
                ("A", 18.0, {"N->W": 0.38, "S->E": 0.36}),
                ("B", 32.0, {"N->S": 0.35, "S->N": 0.34}),
                ("C", 18.0, {"E->N": 0.37, "W->S": 0.35}),
                ("D", 32.0, {"E->W": 0.34, "W->E": 0.33}),
            ],
            {
                "A": {"N->W", "S->E"},
                "B": {"N->S", "S->N"},
                "C": {"E->N", "W->S"},
                "D": {"E->W", "W->E"},
            },
        ),
        (
            "split_shared_ns_straight",
            [
                (
                    "A",
                    25.0,
                    {"N->S": 0.43, "N->E": 0.11, "E->N": 0.09},
                ),
                ("B", 35.0, {"N->S": 0.24, "S->N": 0.39}),
                (
                    "C",
                    15.0,
                    {"S->N": 0.22, "N->E": 0.02, "E->N": 0.02},
                ),
                ("D", 25.0, {"E->W": 0.35, "W->E": 0.34}),
            ],
            {
                "A": {"N->S", "N->E", "E->N"},
                "B": {"N->S", "S->N"},
                "C": {"N->S", "S->N"},
                "D": {"E->W", "W->E"},
            },
        ),
        (
            "five_phase_mixed_cycle",
            [
                ("A", 18.0, {"N->E": 0.42, "S->W": 0.39}),
                ("B", 30.0, {"N->S": 0.38, "S->N": 0.35}),
                ("C", 14.0, {"N->S": 0.42, "N->E": 0.10, "E->N": 0.08}),
                ("D", 18.0, {"E->S": 0.40, "W->N": 0.37}),
                ("E", 20.0, {"E->W": 0.36, "W->E": 0.34}),
            ],
            {
                "A": {"N->E", "S->W"},
                "B": {"N->S", "S->N"},
                "C": {"N->S", "N->E", "E->N"},
                "D": {"E->S", "W->N"},
                "E": {"E->W", "W->E"},
            },
        ),
    ]


def test_v10_large_diverse_synthetic_matrix() -> None:
    noise_levels = (0.0, 0.0025, 0.005, 0.01, 0.015, 0.02)
    samples = (300, 600, 1200, 2400)
    seeds = range(20)

    total = 0
    failures: list[dict[str, object]] = []
    topology_failures = 0

    for scenario_name, phases, expected in _scenario_catalog():
        for noise in noise_levels:
            for sample_count in samples:
                for seed in seeds:
                    total += 1
                    result, _truth = _profile(
                        phases,
                        seed=seed + 1000 * int(noise * 10000) + sample_count,
                        noise=noise,
                        samples=sample_count,
                    )
                    try:
                        plan = infer_physical_signal_plan(result)
                        actual = _phase_sets(plan)
                        arrows = _topology_arrows(plan)
                        expected_arrows = {
                            movement
                            for values in expected.values()
                            for movement in values
                            if "->" in movement and movement.split("->", 1)[0] in "NSEW"
                            and movement not in {"N->S", "S->N", "E->W", "W->E"}
                        }
                        expected_signatures = {
                            frozenset(values)
                            for values in expected.values()
                        }
                        if actual != expected_signatures or arrows != expected_arrows:
                            topology_failures += int(arrows != expected_arrows)
                            failures.append(
                                {
                                    "scenario": scenario_name,
                                    "noise": noise,
                                    "samples": sample_count,
                                    "seed": seed,
                                    "actual_signatures": [sorted(v) for v in sorted(actual, key=lambda item: tuple(sorted(item)))],
                                    "expected_signatures": [sorted(v) for v in sorted(expected_signatures, key=lambda item: tuple(sorted(item)))],
                                    "arrows": sorted(arrows),
                                    "expected_arrows": sorted(expected_arrows),
                                }
                            )
                    except Exception as exc:
                        failures.append(
                            {
                                "scenario": scenario_name,
                                "noise": noise,
                                "samples": sample_count,
                                "seed": seed,
                                "exception": repr(exc),
                            }
                        )

    by_scenario = Counter(item["scenario"] for item in failures if "scenario" in item)
    by_noise = Counter(str(item["noise"]) for item in failures if "noise" in item)
    report = {
        "total_cases": total,
        "passed_cases": total - len(failures),
        "failed_cases": len(failures),
        "accuracy_percent": 100.0 * (total - len(failures)) / total,
        "topology_failures": topology_failures,
        "noise_levels": noise_levels,
        "samples": samples,
        "scenario_count": len(_scenario_catalog()),
        "scenario_names": [name for name, _phases, _truth in _scenario_catalog()],
        "failure_examples": failures[:20],
        "failures_by_scenario": dict(by_scenario),
        "failures_by_noise": dict(by_noise),
    }
    report_path = Path("synthetic_v10_benchmark_report.json")
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("V10_SYNTHETIC_REPORT", json.dumps(report, ensure_ascii=False))
    assert not failures, (
        f"synthetic benchmark failed: {len(failures)}/{total}; "
        f"see {report_path}"
    )
