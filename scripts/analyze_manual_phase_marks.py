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
        if kind not in result:
            continue
        if not isinstance(timestamp_ms, (int, float)):
            raise ValueError("mark timestamp_ms must be numeric")
        result[kind].append(float(timestamp_ms) / 1000.0)

    for kind in result:
        result[kind].sort()

    return result


def _mad(values: list[float], center: float) -> float:
    if not values:
        return 0.0
    return median([abs(value - center) for value in values])


def _series_stats(timestamps: list[float]) -> dict[str, object]:
    intervals = [
        round(right - left, 3)
        for left, right in zip(timestamps, timestamps[1:])
    ]
    if not intervals:
        return {
            "count": len(timestamps),
            "interval_count": 0,
            "intervals_s": [],
            "mean_s": None,
            "median_s": None,
            "mad_s": None,
            "min_s": None,
            "max_s": None,
        }

    avg = mean(intervals)
    med = median(intervals)
    return {
        "count": len(timestamps),
        "interval_count": len(intervals),
        "intervals_s": intervals,
        "mean_s": round(avg, 3),
        "median_s": round(med, 3),
        "mad_s": round(_mad(intervals, med), 3),
        "min_s": round(min(intervals), 3),
        "max_s": round(max(intervals), 3),
    }


def analyze(path: Path) -> dict[str, object]:
    marks = _load_marks(path)
    ew = _series_stats(marks["EW"])
    ns = _series_stats(marks["NS"])

    combined_intervals = (
        list(ew["intervals_s"]) +
        list(ns["intervals_s"])
    )
    combined_mean = mean(combined_intervals) if combined_intervals else None
    combined_median = median(combined_intervals) if combined_intervals else None

    return {
        "source": str(path),
        "series": {
            "EW": ew,
            "NS": ns,
        },
        "combined_interval_stats": {
            "count": len(combined_intervals),
            "mean_s": (
                round(combined_mean, 3)
                if combined_mean is not None
                else None
            ),
            "median_s": (
                round(combined_median, 3)
                if combined_median is not None
                else None
            ),
            "mad_s": (
                round(_mad(combined_intervals, combined_median), 3)
                if combined_median is not None
                else None
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze manually marked EW/NS phase-start intervals."
    )
    parser.add_argument("path", type=Path, help="trajectory_manual_marks.json")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON report path.",
    )
    args = parser.parse_args()

    try:
        result = analyze(args.path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.output is not None:
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Output: {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
