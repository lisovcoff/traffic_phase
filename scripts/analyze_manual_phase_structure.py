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

    for values in result.values():
        values.sort()
    return result


def _intervals(values: list[float]) -> list[float]:
    return [right - left for left, right in zip(values, values[1:])]


def _stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "mean_s": None,
            "median_s": None,
            "mad_s": None,
            "min_s": None,
            "max_s": None,
        }

    center = median(values)
    return {
        "count": len(values),
        "mean_s": round(mean(values), 3),
        "median_s": round(center, 3),
        "mad_s": round(median([abs(value - center) for value in values]), 3),
        "min_s": round(min(values), 3),
        "max_s": round(max(values), 3),
    }


def _cross_family_offsets(
    ew: list[float],
    ns: list[float],
) -> tuple[list[float], list[float]]:
    """Pair each EW start with the first NS start and following EW start."""
    to_ns: list[float] = []
    to_next_ew: list[float] = []

    for index, ew_start in enumerate(ew):
        next_ew = ew[index + 1] if index + 1 < len(ew) else None
        following_ns = next(
            value
            for value in ns
            if value > ew_start
            and (next_ew is None or value < next_ew)
        )
        if following_ns is None:
            continue

        to_ns.append(following_ns - ew_start)
        if next_ew is not None:
            to_next_ew.append(next_ew - following_ns)

    return to_ns, to_next_ew


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extract an empirical cycle and cross-family phase structure "
            "from manual EW/NS phase-start marks."
        )
    )
    parser.add_argument("marks", type=Path, help="trajectory_manual_marks.json")
    args = parser.parse_args()

    try:
        marks = _load_marks(args.marks)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    ew_intervals = _intervals(marks["EW"])
    ns_intervals = _intervals(marks["NS"])
    to_ns, to_next_ew = _cross_family_offsets(marks["EW"], marks["NS"])

    combined = ew_intervals + ns_intervals

    print("Manual phase structure:")
    print(f"EW→EW:       {_stats(ew_intervals)}")
    print(f"NS→NS:       {_stats(ns_intervals)}")
    print(f"EW→NS:       {_stats(to_ns)}")
    print(f"NS→next EW:  {_stats(to_next_ew)}")
    print(f"all same-family intervals: {_stats(combined)}")

    if to_ns and to_next_ew:
        print(
            "cycle reconstruction from paired transitions: "
            f"mean={mean(to_ns) + mean(to_next_ew):.3f}s, "
            f"median={median(to_ns) + median(to_next_ew):.3f}s"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
