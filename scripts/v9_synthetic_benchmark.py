from __future__ import annotations

import argparse
import json
from pathlib import Path
from random import Random
from statistics import mean

from app.core.v9.v9_discovery import discover_records


CASES = {
    "2phase_balanced": (
        (35.0, 65.0),
        (
            ("A->B", "C->D"),
            ("E->F", "G->H"),
        ),
    ),
    "3phase_uneven": (
        (18.0, 27.0, 55.0),
        (
            ("A->B", "C->D"),
            ("E->F",),
            ("G->H", "I->J"),
        ),
    ),
    "4phase_short": (
        (12.0, 24.0, 31.0, 33.0),
        (
            ("A->B",),
            ("C->D",),
            ("E->F",),
            ("G->H",),
        ),
    ),
    "3phase_shared_stream": (
        (25.0, 40.0, 35.0),
        (
            ("A->B", "C->D"),
            ("A->B", "E->F"),
            ("G->H", "I->J"),
        ),
    ),
    "3phase_missing": (
        (30.0, 35.0, 35.0),
        (
            ("A->B", "C->D"),
            ("E->F",),
            ("G->H", "I->J"),
        ),
    ),
    "3phase_noisy_25pct": (
        (30.0, 35.0, 35.0),
        (
            ("A->B", "C->D"),
            ("E->F", "G->H"),
            ("I->J", "K->L"),
        ),
    ),
    "5phase": (
        (14.0, 19.0, 23.0, 28.0, 36.0),
        (
            ("A->B",),
            ("C->D",),
            ("E->F",),
            ("G->H",),
            ("I->J",),
        ),
    ),
    "t_intersection_3phase": (
        (25.0, 30.0, 45.0),
        (
            ("N->S", "S->N"),
            ("N->E", "E->N"),
            ("E->S", "S->E"),
        ),
    ),
}


def generate(
    durations,
    streams_by_phase,
    *,
    cycles: int,
    seed: int,
    drop: float,
    timestamp_jitter_s: float,
    duplicate_fraction: float,
):
    rng = Random(seed)
    period = sum(durations)
    phase_starts = []
    cursor = 0.0
    for duration in durations:
        phase_starts.append(cursor)
        cursor += duration

    tracks = []
    identifier = 0
    base_ms = 1_700_000_000_000

    for cycle in range(cycles):
        for phase_index, duration in enumerate(durations):
            start = phase_starts[phase_index]
            for stream in streams_by_phase[phase_index]:
                samples = max(4, int(duration / 5.0))
                for sample in range(samples):
                    if rng.random() < drop:
                        continue
                    identifier += 1
                    t = (
                        cycle * period
                        + start
                        + 1.0
                        + sample * max(1.0, (duration - 2.0) / samples)
                        + rng.gauss(0.0, timestamp_jitter_s)
                    )
                    millis = base_ms + int(round(t * 1000.0))
                    source, target = stream.split("->", 1)
                    track = {
                        "category_name": "car",
                        "id": identifier,
                        "millis": millis,
                        "zone_in": source,
                        "zone_out": target,
                        "wait_s": 0.0,
                        "detections": [
                            {
                                "millis": millis,
                                "zone": source,
                                "speed": 10.0,
                            },
                            {
                                "millis": millis + 1000,
                                "zone": target,
                                "speed": 10.0,
                            },
                        ],
                    }
                    tracks.append(track)
                    if rng.random() < duplicate_fraction:
                        tracks.append(dict(track))

    return tracks, phase_starts, period


def boundary_accuracy(result, expected_starts, tolerance_s=4.0):
    predicted = [
        float(value)
        for value in result["schedule"]["baseline_phase_centers_s"].values()
    ]
    if len(predicted) != len(expected_starts):
        return 0.0, None
    period = float(result["schedule"]["period_s"])
    predicted = sorted(value % period for value in predicted)
    expected = sorted(value % period for value in expected_starts)

    # Circular sequences may start at different anonymous phases.
    best_fraction = 0.0
    best_mae = None
    n = len(predicted)
    for shift in range(n):
        rotated = predicted[shift:] + predicted[:shift]
        errors = []
        for left, right in zip(expected, rotated):
            delta = abs(left - right)
            errors.append(min(delta, period - delta))
        fraction = sum(error <= tolerance_s for error in errors) / n
        mae = mean(errors)
        if fraction > best_fraction or (
            fraction == best_fraction
            and (best_mae is None or mae < best_mae)
        ):
            best_fraction = fraction
            best_mae = mae
    return best_fraction, best_mae


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diverse synthetic benchmark for repository V9"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("v9_synthetic_benchmark.json"),
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=10,
    )
    args = parser.parse_args()

    tolerances_s = (1.0, 2.0, 3.0, 4.0)
    rows = []
    for index, (name, (durations, streams)) in enumerate(CASES.items()):
        drop = 0.25 if "noisy" in name else 0.10 if "missing" in name else 0.0
        jitter = 0.30 if "noisy" in name else 0.0
        duplicates = 0.05 if "noisy" in name else 0.0
        tracks, starts, expected_period = generate(
            durations,
            streams,
            cycles=args.cycles,
            seed=index + 100,
            drop=drop,
            timestamp_jitter_s=jitter,
            duplicate_fraction=duplicates,
        )
        result = discover_records(
            tracks,
            input_name=name,
            dt=1.0,
        )
        boundary_metrics = {}
        for tolerance_s in tolerances_s:
            fraction, _ = boundary_accuracy(
                result,
                starts,
                tolerance_s=tolerance_s,
            )
            boundary_metrics[
                f"boundary_accuracy_within_{int(tolerance_s)}s_percent"
            ] = 100.0 * fraction
        boundary_fraction_4s, boundary_mae = boundary_accuracy(
            result,
            starts,
            tolerance_s=4.0,
        )
        predicted_period = float(
            result["period_inference"]["period_s"]
        )
        rows.append(
            {
                "case": name,
                "expected_phase_count": len(durations),
                "predicted_phase_count": int(
                    result["phase_model_selection"]["selected_phase_count"]
                ),
                "phase_count_ok": (
                    int(
                        result["phase_model_selection"]["selected_phase_count"]
                    )
                    == len(durations)
                ),
                "expected_period_s": expected_period,
                "predicted_period_s": predicted_period,
                "period_error_s": abs(
                    predicted_period - expected_period
                ),
                "boundary_accuracy_percent": 100.0 * boundary_fraction_4s,
                "boundary_mae_s": boundary_mae,
                **boundary_metrics,
                "events": result["event_count"],
                "streams": result["movement_stream_count"],
            }
        )

    phase_count_accuracy = 100.0 * mean(
        float(row["phase_count_ok"])
        for row in rows
    )
    boundary_accuracy_mean = mean(
        row["boundary_accuracy_percent"]
        for row in rows
    )
    boundary_mae_mean = mean(
        float(row["boundary_mae_s"])
        for row in rows
        if row["boundary_mae_s"] is not None
    )

    strict_rows = {
        tolerance: mean(
            float(
                row[
                    f"boundary_accuracy_within_{int(tolerance)}s_percent"
                ]
            )
            for row in rows
        )
        for tolerance in tolerances_s
    }

    report = {
        "algorithm": "direction-agnostic-v9",
        "manual_labels_used": False,
        "boundary_metric_tolerances_s": list(tolerances_s),
        "cases": rows,
        "phase_count_accuracy_percent": phase_count_accuracy,
        "mean_boundary_accuracy_percent": boundary_accuracy_mean,
        "mean_boundary_mae_s": boundary_mae_mean,
        "mean_boundary_accuracy_by_tolerance_percent": {
            f"within_{int(tolerance)}s": value
            for tolerance, value in strict_rows.items()
        },
        "interpretation": {
            "boundary_accuracy_percent": "fraction of phase centers within the selected tolerance; default headline remains ±4 s",
            "boundary_mae_s": "mean circular absolute error between matched phase centers",
        },
    }
    args.output.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
