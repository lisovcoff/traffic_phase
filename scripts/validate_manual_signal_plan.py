from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


MARK_KINDS = ("NS", "EW", "N_ARROW")


def circular_distance(value: float, center: float, period: float) -> float:
    delta = abs(value - center) % period
    return min(delta, period - delta)


def best_phase(times: list[float], period: float, step: float = 0.1) -> tuple[float, float]:
    phases = [t % period for t in times]
    best_offset = 0.0
    best_mae = float("inf")
    steps = max(1, math.ceil(period / step))
    for index in range(steps):
        offset = min(index * step, period)
        mae = sum(
            circular_distance(phase, offset, period)
            for phase in phases
        ) / len(phases)
        if mae < best_mae:
            best_mae = mae
            best_offset = offset
    return best_offset, best_mae


def pairwise_periods(times: list[float]) -> list[float]:
    values: list[float] = []
    for i in range(len(times)):
        for j in range(i + 1, len(times)):
            cycles = j - i
            values.append((times[j] - times[i]) / cycles)
    return values


def median(values: list[float]) -> float:
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


def candidate_score(groups: dict[str, list[float]], period: float) -> dict[str, object]:
    rows: dict[str, object] = {}
    errors: list[float] = []
    for kind, times in groups.items():
        if not times:
            continue
        phase, mae = best_phase(times, period)
        rows[kind] = {"phase_s": round(phase, 2), "mae_s": round(mae, 3)}
        errors.append(mae)
    return {
        "period_s": period,
        "mean_boundary_mae_s": round(sum(errors) / len(errors), 3),
        "by_kind": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Independently validate manual signal-transition marks."
    )
    parser.add_argument("manual_json", type=Path)
    parser.add_argument(
        "--candidates",
        default="78,80,90,95,96,98,100,101,102",
    )
    args = parser.parse_args()

    data = json.loads(args.manual_json.read_text(encoding="utf-8"))
    groups: dict[str, list[float]] = {}
    for mark in data.get("marks", []):
        kind = str(mark.get("kind", ""))
        offset = mark.get("offset_s")
        if kind in MARK_KINDS and offset is not None:
            groups.setdefault(kind, []).append(float(offset))

    for times in groups.values():
        times.sort()

    print("Manual transition counts:")
    for kind in MARK_KINDS:
        print(f"  {kind}: {len(groups.get(kind, []))}")

    print("\nPairwise period diagnostics (robust descriptive statistic):")
    for kind in MARK_KINDS:
        times = groups.get(kind, [])
        estimates = pairwise_periods(times)
        if not estimates:
            continue
        print(
            f"  {kind}: median={median(estimates):.3f}s "
            f"range={min(estimates):.3f}..{max(estimates):.3f}s"
        )

    results = [
        candidate_score(groups, float(period))
        for period in args.candidates.split(",")
        if period
    ]
    results.sort(key=lambda item: float(item["mean_boundary_mae_s"]))

    print("\nPhase-folding diagnostics:")
    for result in results:
        print(
            f"  T={result['period_s']:.0f}s "
            f"mean_boundary_MAE={result['mean_boundary_mae_s']:.3f}s"
        )
        for kind, details in result["by_kind"].items():
            print(
                f"    {kind}: phase={details['phase_s']:.1f}s "
                f"MAE={details['mae_s']:.3f}s"
            )

    print(
        "\nThis is an independent diagnostic of manual marks. "
        "It does not treat them as perfect controller telemetry."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
