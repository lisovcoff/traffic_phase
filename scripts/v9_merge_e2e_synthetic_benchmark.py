from __future__ import annotations

import argparse
import itertools
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.core.v9.fit import em_fit
from app.core.v9.primitives import fit_bernoulli_templates, _pointwise_loglik


COSINE_GRID = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)
LOSS_GRID = (4.0, 6.0, 8.0, 10.0, 12.0, 15.0)


@dataclass(frozen=True)
class BenchmarkConfig:
    cases_per_class: int = 500
    seed: int = 20261003


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator > 1e-12 else 0.0


def _phase_templates(
    rng: np.random.Generator,
    phases: int,
    streams: int,
    *,
    overlap: float = 0.0,
) -> np.ndarray:
    """Create sparse traffic-stream rates with configurable phase overlap."""
    probs = np.zeros((phases, streams), dtype=float)

    # Low base rates better resemble sparse traffic-event occupancy than a
    # near-saturated Bernoulli process.
    base = rng.uniform(0.006, 0.035, size=streams)
    active_rate = rng.uniform(0.08, 0.30, size=(phases, streams))

    owner_masks = np.zeros((phases, streams), dtype=bool)
    for stream in range(streams):
        owner = int(rng.integers(0, phases))
        owner_masks[owner, stream] = True
        for phase in range(phases):
            if phase != owner and rng.random() < overlap:
                owner_masks[phase, stream] = True

    probs[:] = base[None, :]
    probs = np.where(owner_masks, active_rate, probs)
    return np.clip(probs, 0.002, 0.45)


def _timeline(
    rng: np.random.Generator,
    period: float,
    cycles: int,
    phases: int,
) -> tuple[np.ndarray, np.ndarray]:
    durations = np.maximum(
        3.0,
        rng.dirichlet(np.full(phases, 4.0)) * period,
    )
    durations *= period / float(np.sum(durations))
    rounded = np.maximum(1, np.rint(durations).astype(int))
    rounded[-1] = max(1, int(round(period)) - int(rounded[:-1].sum()))

    labels = []
    local_fraction = []
    for _ in range(cycles + 1):
        for phase, duration in enumerate(rounded):
            count = int(max(1, duration))
            labels.extend([phase] * count)
            local_fraction.extend(
                np.linspace(0.0, 1.0, count, endpoint=False)
            )

    total_s = int(round(period * cycles))
    labels = np.asarray(labels[:total_s], dtype=np.int16)
    local_fraction = np.asarray(local_fraction[:total_s], dtype=float)
    return labels, local_fraction


def _sample_occupancy(
    rng: np.random.Generator,
    labels: np.ndarray,
    local_fraction: np.ndarray,
    templates: np.ndarray,
    *,
    temporal_drift_sigma: float,
    background_rate: float,
    visibility: np.ndarray,
) -> np.ndarray:
    phases, streams = templates.shape
    multipliers = np.exp(
        rng.normal(
            0.0,
            temporal_drift_sigma,
            size=(phases, 2, streams),
        )
    )

    x = np.zeros((len(labels), streams), dtype=np.float32)
    for t, phase_value in enumerate(labels):
        phase = int(phase_value)
        half = 0 if local_fraction[t] < 0.5 else 1
        probabilities = templates[phase] * multipliers[phase, half]
        probabilities = probabilities * visibility
        probabilities = probabilities + background_rate
        x[t] = rng.binomial(
            1,
            np.clip(probabilities, 0.001, 0.75),
        ).astype(np.float32)
    return x


def _make_case(rng: np.random.Generator, case_type: str):
    period = float(rng.uniform(85.0, 145.0))
    cycles = int(rng.integers(8, 31))
    streams = int(rng.integers(8, 21))

    if case_type == "true2":
        templates = _phase_templates(
            rng,
            2,
            streams,
            overlap=float(rng.uniform(0.05, 0.20)),
        )
        # Stronger intra-phase drift is the realistic source of a lower cosine:
        # the same physical phase can have different vehicle-arrival rates in
        # its first and second half, while the ground-truth topology remains 2.
        temporal_drift_sigma = float(
            rng.uniform(0.25, 0.75)
            if rng.random() < 0.25
            else rng.uniform(0.10, 0.35)
        )
        background_rate = float(rng.uniform(0.001, 0.012))
        true_k = 2
    else:
        templates = _phase_templates(
            rng,
            3,
            streams,
            overlap=float(rng.uniform(0.12, 0.42)),
        )
        # A hard-negative tail intentionally creates partially similar genuine
        # phases without making their stream ownership identical.
        if rng.random() < 0.35:
            pair = tuple(rng.choice(3, size=2, replace=False))
            mix = float(rng.uniform(0.25, 0.55))
            a, b = int(pair[0]), int(pair[1])
            templates[b] = (
                (1.0 - mix) * templates[b]
                + mix * templates[a]
            )
        temporal_drift_sigma = float(rng.uniform(0.12, 0.45))
        background_rate = float(rng.uniform(0.001, 0.012))
        true_k = 3

    visibility = rng.uniform(0.45, 1.0, size=streams)
    dropout = rng.random(streams) < rng.uniform(0.03, 0.12)
    visibility[dropout] *= rng.uniform(0.10, 0.45, size=int(dropout.sum()))

    labels, local_fraction = _timeline(
        rng,
        period,
        cycles,
        true_k,
    )
    x = _sample_occupancy(
        rng,
        labels,
        local_fraction,
        templates,
        temporal_drift_sigma=temporal_drift_sigma,
        background_rate=background_rate,
        visibility=visibility,
    )

    names = [f"stream_{i:02d}" for i in range(streams)]
    by_stream = {
        names[j]: np.flatnonzero(x[:, j] > 0.5).astype(float).tolist()
        for j in range(streams)
    }
    by_stream = {
        name: values
        for name, values in by_stream.items()
        if values
    }

    return {
        "x": x,
        "by_stream": by_stream,
        "period_s": period,
        "cycles": cycles,
        "true_k": true_k,
        "temporal_drift_sigma": temporal_drift_sigma,
        "background_rate": background_rate,
        "dropout_streams": int(dropout.sum()),
    }


def _merge_metrics(fit, x: np.ndarray, cycles: int):
    labels = np.asarray(fit["labels"], dtype=np.int16)
    probs = np.asarray(fit["probs"], dtype=float)
    ll3 = _pointwise_loglik(x, probs, labels)
    metrics = {}

    for pair_id, (a, b) in enumerate(itertools.combinations(range(3), 2)):
        merged_labels = np.where(
            (labels == a) | (labels == b),
            0,
            1,
        ).astype(np.int16)
        merged_probs = fit_bernoulli_templates(
            x,
            merged_labels,
            2,
        )
        ll2 = _pointwise_loglik(x, merged_probs, merged_labels)
        metrics[str(pair_id)] = {
            "pair": [a, b],
            "cosine": _cosine(probs[a], probs[b]),
            "maxdiff": float(
                np.max(np.abs(probs[a] - probs[b]))
            ),
            "loss_per_cycle": float(
                (ll3 - ll2) / max(1, cycles)
            ),
        }
    return metrics


def _passes(metrics, cosine_min: float, loss_max: float) -> bool:
    return any(
        item["cosine"] >= cosine_min
        and item["loss_per_cycle"] <= loss_max
        for item in metrics.values()
    )


def _run_case(seed: int, case_type: str):
    rng = np.random.default_rng(seed)
    case = _make_case(rng, case_type)
    fit = em_fit(
        case["x"],
        case["period_s"],
        3,
        by_stream_global=case["by_stream"],
        dt=1.0,
        iterations=2,
    )
    return {
        "true_k": case["true_k"],
        "streams": int(case["x"].shape[1]),
        "period_s": float(case["period_s"]),
        "cycles": int(case["cycles"]),
        "fit_k": int(fit["k"]),
        "temporal_drift_sigma": float(
            case["temporal_drift_sigma"]
        ),
        "dropout_streams": int(case["dropout_streams"]),
        "metrics": _merge_metrics(
            fit,
            case["x"],
            case["cycles"],
        ),
    }


def _percentiles(values):
    if not values:
        return {}
    array = np.asarray(values, dtype=float)
    return {
        "p01": float(np.percentile(array, 1)),
        "p05": float(np.percentile(array, 5)),
        "p25": float(np.percentile(array, 25)),
        "p50": float(np.percentile(array, 50)),
        "p75": float(np.percentile(array, 75)),
        "p95": float(np.percentile(array, 95)),
        "p99": float(np.percentile(array, 99)),
        "min": float(np.min(array)),
        "max": float(np.max(array)),
    }


def _diagnostics(rows):
    diagnostics = {}
    for group_name, group in rows.items():
        pairwise_cosines = []
        pairwise_losses = []
        best_cosine = []
        min_loss = []
        for row in group:
            values = list(row["metrics"].values())
            pairwise_cosines.extend(
                float(item["cosine"]) for item in values
            )
            pairwise_losses.extend(
                float(item["loss_per_cycle"]) for item in values
            )
            best_cosine.append(
                max(float(item["cosine"]) for item in values)
            )
            min_loss.append(
                min(float(item["loss_per_cycle"]) for item in values)
            )

        diagnostics[group_name] = {
            "case_count": len(group),
            "pairwise_cosine": _percentiles(pairwise_cosines),
            "pairwise_loss_per_cycle": _percentiles(pairwise_losses),
            "best_pair_cosine_by_case": _percentiles(best_cosine),
            "minimum_pair_loss_by_case": _percentiles(min_loss),
            "false_positive_cases": [],
            "false_negative_cases": [],
        }

    return diagnostics


def run_benchmark(config: BenchmarkConfig):
    rows = {"true2": [], "true3": []}

    for case_type, offset in (
        ("true2", 100_003),
        ("true3", 200_003),
    ):
        for index in range(config.cases_per_class):
            rows[case_type].append(
                _run_case(
                    config.seed + offset + index,
                    case_type,
                )
            )

    threshold_rows = []
    for cosine_min in COSINE_GRID:
        for loss_max in LOSS_GRID:
            n2 = len(rows["true2"])
            n3 = len(rows["true3"])
            true2_hits = sum(
                _passes(
                    row["metrics"],
                    cosine_min,
                    loss_max,
                )
                for row in rows["true2"]
            )
            true3_false = sum(
                _passes(
                    row["metrics"],
                    cosine_min,
                    loss_max,
                )
                for row in rows["true3"]
            )
            recall = true2_hits / max(1, n2)
            false_merge = true3_false / max(1, n3)
            threshold_rows.append(
                {
                    "cosine_min": cosine_min,
                    "loss_max": loss_max,
                    "true2_merge_recall": float(recall),
                    "true3_false_merge_rate": float(false_merge),
                    "balanced_accuracy": float(
                        0.5 * (recall + 1.0 - false_merge)
                    ),
                }
            )

    policy = next(
        row
        for row in threshold_rows
        if row["cosine_min"] == 0.50
        and row["loss_max"] == 10.0
    )

    diagnostics = _diagnostics(rows)
    for group_name, group in rows.items():
        errors = diagnostics[group_name]
        for row_index, row in enumerate(group):
            passed = _passes(row["metrics"], 0.50, 10.0)
            if group_name == "true2" and not passed and len(
                errors["false_negative_cases"]
            ) < 25:
                errors["false_negative_cases"].append(
                    {
                        "index": row_index,
                        "seed": int(
                            config.seed
                            + (100_003 if group_name == "true2" else 200_003)
                            + row_index
                        ),
                        "metrics": row["metrics"],
                        "temporal_drift_sigma": row[
                            "temporal_drift_sigma"
                        ],
                        "dropout_streams": row["dropout_streams"],
                    }
                )
            if group_name == "true3" and passed and len(
                errors["false_positive_cases"]
            ) < 25:
                errors["false_positive_cases"].append(
                    {
                        "index": row_index,
                        "seed": int(
                            config.seed
                            + (100_003 if group_name == "true2" else 200_003)
                            + row_index
                        ),
                        "metrics": row["metrics"],
                        "temporal_drift_sigma": row[
                            "temporal_drift_sigma"
                        ],
                        "dropout_streams": row["dropout_streams"],
                    }
                )

    return {
        "config": {
            "cases_per_class": config.cases_per_class,
            "seed": config.seed,
        },
        "classes": {
            "true2_overfit": len(rows["true2"]),
            "true3_distinct": len(rows["true3"]),
        },
        "policy_A": policy,
        "threshold_grid": threshold_rows,
        "diagnostics": diagnostics,
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "E2E V9 synthetic merge benchmark with sparse traffic occupancy, "
            "intra-phase drift, dropout, and hard-negative 3-phase cases."
        )
    )
    parser.add_argument(
        "--cases-per-class",
        type=int,
        default=500,
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20261003,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "v9_merge_e2e_synthetic_benchmark.json"
        ),
    )
    args = parser.parse_args()

    report = run_benchmark(
        BenchmarkConfig(
            cases_per_class=max(1, args.cases_per_class),
            seed=args.seed,
        )
    )
    args.output.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    policy = report["policy_A"]
    print("V9 end-to-end synthetic merge benchmark")
    print("cases per class:", args.cases_per_class)
    print(
        "Policy A (cosine >= 0.50 and loss/cycle <= 10): "
        f"true2 recall={policy['true2_merge_recall']:.4f}, "
        f"true3 false-merge={policy['true3_false_merge_rate']:.4f}, "
        f"balanced={policy['balanced_accuracy']:.4f}"
    )

    for group_name in ("true2", "true3"):
        group_diag = report["diagnostics"][group_name]
        cosine = group_diag["pairwise_cosine"]
        loss = group_diag["pairwise_loss_per_cycle"]
        print(
            f"{group_name}: "
            f"pairwise cosine p05/p50/p95="
            f"{cosine.get('p05', 0.0):.3f}/"
            f"{cosine.get('p50', 0.0):.3f}/"
            f"{cosine.get('p95', 0.0):.3f}, "
            f"loss/cycle p05/p50/p95="
            f"{loss.get('p05', 0.0):.3f}/"
            f"{loss.get('p50', 0.0):.3f}/"
            f"{loss.get('p95', 0.0):.3f}"
        )


if __name__ == "__main__":
    main()
