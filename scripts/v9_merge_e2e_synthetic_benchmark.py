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
    cases_per_class: int = 2_000
    seed: int = 20261003


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    den = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / den) if den > 1e-12 else 0.0


def _phase_templates(
    rng: np.random.Generator,
    phases: int,
    streams: int,
) -> np.ndarray:
    probs = np.zeros((phases, streams), dtype=float)
    order = rng.permutation(streams)
    chunks = np.array_split(order, phases)
    for phase, owned in enumerate(chunks):
        owned = set(int(v) for v in owned)
        for stream in range(streams):
            probs[phase, stream] = (
                rng.uniform(0.35, 0.80)
                if stream in owned
                else rng.uniform(0.01, 0.08)
            )
    return probs


def _timeline(
    rng: np.random.Generator,
    total_s: int,
    period: float,
    phases: int,
) -> np.ndarray:
    fractions = rng.dirichlet(np.full(phases, 4.0))
    durations = np.maximum(3.0, fractions * period)
    durations *= period / float(np.sum(durations))
    cycle = np.maximum(1, np.rint(durations).astype(int))

    # Keep the rounded cycle close to the requested period.
    drift = int(round(period)) - int(cycle.sum())
    cycle[-1] = max(1, int(cycle[-1] + drift))

    one_cycle = np.concatenate(
        [
            np.full(int(duration), phase, dtype=np.int16)
            for phase, duration in enumerate(cycle)
        ]
    )
    repeats = int(np.ceil(total_s / max(1, len(one_cycle))))
    return np.tile(one_cycle, repeats)[:total_s]


def _make_case(rng: np.random.Generator, case_type: str):
    period = float(rng.uniform(85.0, 145.0))
    cycles = int(rng.integers(8, 31))
    streams = int(rng.integers(8, 21))
    total_s = int(round(period * cycles))

    if case_type == "true2":
        base_templates = _phase_templates(rng, 2, streams)
        # Build observations from a genuine 2-phase latent process, then fit k=3.
        true_templates = base_templates
        phases = 2
    else:
        true_templates = _phase_templates(rng, 3, streams)
        phases = 3

    labels = _timeline(rng, total_s, period, phases)
    x = np.zeros((total_s, streams), dtype=np.float32)
    for t, phase in enumerate(labels):
        x[t] = rng.binomial(1, true_templates[int(phase)]).astype(np.float32)

    names = [f"stream_{i:02d}" for i in range(streams)]
    by_stream = {
        names[j]: np.flatnonzero(x[:, j] > 0.5).astype(float).tolist()
        for j in range(streams)
    }
    by_stream = {name: values for name, values in by_stream.items() if values}

    return x, by_stream, period, cycles, phases


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
        merged_probs = fit_bernoulli_templates(x, merged_labels, 2)
        ll2 = _pointwise_loglik(x, merged_probs, merged_labels)
        metrics[str(pair_id)] = {
            "pair": [a, b],
            "cosine": _cosine(probs[a], probs[b]),
            "maxdiff": float(np.max(np.abs(probs[a] - probs[b]))),
            "loss_per_cycle": float((ll3 - ll2) / max(1, cycles)),
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
    x, by_stream, period, cycles, true_k = _make_case(rng, case_type)
    fit = em_fit(
        x,
        period,
        3,
        by_stream_global=by_stream,
        dt=1.0,
        iterations=2,
    )
    return {
        "true_k": true_k,
        "streams": int(x.shape[1]),
        "period_s": float(period),
        "cycles": int(cycles),
        "fit_k": int(fit["k"]),
        "metrics": _merge_metrics(fit, x, cycles),
    }


def run_benchmark(config: BenchmarkConfig):
    rows = {"true2": [], "true3": []}
    for case_type, offset in (("true2", 100_003), ("true3", 200_003)):
        for i in range(config.cases_per_class):
            rows[case_type].append(
                _run_case(config.seed + offset + i, case_type)
            )

    threshold_rows = []
    for cosine_min in COSINE_GRID:
        for loss_max in LOSS_GRID:
            n2 = len(rows["true2"])
            n3 = len(rows["true3"])
            true2_hits = sum(
                _passes(row["metrics"], cosine_min, loss_max)
                for row in rows["true2"]
            )
            true3_false = sum(
                _passes(row["metrics"], cosine_min, loss_max)
                for row in rows["true3"]
            )
            recall = true2_hits / max(1, n2)
            fpr = true3_false / max(1, n3)
            threshold_rows.append(
                {
                    "cosine_min": cosine_min,
                    "loss_max": loss_max,
                    "true2_merge_recall": float(recall),
                    "true3_false_merge_rate": float(fpr),
                    "balanced_accuracy": float(
                        0.5 * (recall + 1.0 - fpr)
                    ),
                }
            )

    policy = next(
        row
        for row in threshold_rows
        if row["cosine_min"] == 0.50 and row["loss_max"] == 10.0
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
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "End-to-end V9 synthetic benchmark. Generates occupancy data, "
            "runs the real em_fit(k=3), and evaluates the k=3 -> k=2 merge."
        )
    )
    parser.add_argument("--cases-per-class", type=int, default=2_000)
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("v9_merge_e2e_synthetic_benchmark.json"),
    )
    args = parser.parse_args()

    report = run_benchmark(
        BenchmarkConfig(
            cases_per_class=max(1, args.cases_per_class),
            seed=args.seed,
        )
    )
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
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


if __name__ == "__main__":
    main()
