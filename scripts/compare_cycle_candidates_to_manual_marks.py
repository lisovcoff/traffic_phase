from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median


def _load_marks(path: Path) -> dict[str, list[float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_marks = payload.get("marks") if isinstance(payload, dict) else None
    if not isinstance(raw_marks, list):
        raise ValueError("marks JSON must contain a 'marks' list")

    result: dict[str, list[float]] = {"EW": [], "NS": []}
    for item in raw_marks:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        timestamp_ms = item.get("timestamp_ms")
        if kind not in result or not isinstance(timestamp_ms, (int, float)):
            continue
        result[kind].append(float(timestamp_ms) / 1000.0)

    for kind in result:
        result[kind].sort()
    return result


def _intervals(values: list[float]) -> list[float]:
    return [right - left for left, right in zip(values, values[1:])]


def _stats(intervals: list[float], candidate: float) -> dict[str, float | int | None]:
    if not intervals:
        return {
            "count": 0,
            "mean_abs_error_s": None,
            "median_abs_error_s": None,
            "mean_signed_error_s": None,
        }

    errors = [interval - candidate for interval in intervals]
    abs_errors = [abs(error) for error in errors]
    return {
        "count": len(intervals),
        "mean_abs_error_s": round(mean(abs_errors), 3),
        "median_abs_error_s": round(median(abs_errors), 3),
        "mean_signed_error_s": round(mean(errors), 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare candidate cycle periods from kinematic_cycle JSON "
            "against manually marked EW/NS phase-start intervals."
        )
    )
    parser.add_argument("cycle_result", type=Path)
    parser.add_argument("marks", type=Path)
    parser.add_argument(
        "--limit",
        type=int,
        default=15,
        help="Number of candidates to print.",
    )
    args = parser.parse_args()

    result = json.loads(args.cycle_result.read_text(encoding="utf-8"))
    marks = _load_marks(args.marks)
    candidates = result.get("candidate_cycles")
    if not isinstance(candidates, list):
        parser.error("cycle result must contain candidate_cycles")

    rows: list[dict[str, object]] = []
    for item in candidates[: max(1, args.limit)]:
        if not isinstance(item, dict):
            continue
        cycle = item.get("cycle_seconds")
        if not isinstance(cycle, (int, float)):
            continue
        candidate = float(cycle)

        ew = _stats(_intervals(marks["EW"]), candidate)
        ns = _stats(_intervals(marks["NS"]), candidate)
        errors = [
            abs(interval - candidate)
            for kind in ("EW", "NS")
            for interval in _intervals(marks[kind])
        ]

        rows.append({
            "cycle_s": int(candidate),
            "model_score": item.get("score", item.get("total_cost")),
            "manual_mean_abs_error_s": round(mean(errors), 3) if errors else None,
            "manual_median_abs_error_s": round(median(errors), 3) if errors else None,
            "EW_mean_abs_error_s": ew["mean_abs_error_s"],
            "NS_mean_abs_error_s": ns["mean_abs_error_s"],
        })

    rows.sort(
        key=lambda row: (
            float(row["manual_mean_abs_error_s"])
            if row["manual_mean_abs_error_s"] is not None
            else float("inf"),
            abs(int(row["cycle_s"]) - int(result.get("selected_cycle_seconds", row["cycle_s"]))),
        )
    )

    print("Candidate periods ranked by manual same-family interval error:")
    for row in rows:
        print(
            f"T={row['cycle_s']:>3}s  "
            f"manual_MAE={row['manual_mean_abs_error_s']}s  "
            f"manual_median={row['manual_median_abs_error_s']}s  "
            f"EW_MAE={row['EW_mean_abs_error_s']}s  "
            f"NS_MAE={row['NS_mean_abs_error_s']}s  "
            f"model_score={row['model_score']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
