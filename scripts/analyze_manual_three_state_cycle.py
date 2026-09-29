from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median


KINDS = ("EW", "N_ARROW", "NS")


def _load_marks(path: Path) -> dict[str, list[float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_marks = payload.get("marks") if isinstance(payload, dict) else None
    if not isinstance(raw_marks, list):
        raise ValueError("marks JSON must contain a 'marks' list")

    result = {kind: [] for kind in KINDS}
    for item in raw_marks:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        timestamp_ms = item.get("timestamp_ms")
        if kind in result and isinstance(timestamp_ms, (int, float)):
            result[kind].append(float(timestamp_ms) / 1000.0)

    for values in result.values():
        values.sort()
    return result


def _merge_mark_files(paths: list[Path]) -> dict[str, list[float]]:
    merged = {kind: [] for kind in KINDS}
    for path in paths:
        marks = _load_marks(path)
        for kind in KINDS:
            merged[kind].extend(marks[kind])

    for values in merged.values():
        values[:] = sorted(set(values))
    return merged


def _stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "mean_s": None,
            "median_s": None,
            "min_s": None,
            "max_s": None,
        }
    return {
        "count": len(values),
        "mean_s": round(mean(values), 3),
        "median_s": round(median(values), 3),
        "min_s": round(min(values), 3),
        "max_s": round(max(values), 3),
    }


def _cycle_rows(
    marks: dict[str, list[float]],
) -> list[dict[str, float | int]]:
    ew = marks["EW"]
    arrow = marks["N_ARROW"]
    ns = marks["NS"]

    rows: list[dict[str, float | int]] = []
    for index in range(len(ew) - 1):
        ew_start = ew[index]
        ew_next = ew[index + 1]

        arrow_start = next(
            (value for value in arrow if ew_start < value < ew_next),
            None,
        )
        ns_start = next(
            (value for value in ns if ew_start < value < ew_next),
            None,
        )

        if arrow_start is None or ns_start is None or not arrow_start < ns_start:
            continue

        rows.append({
            "cycle_index": index + 1,
            "ew_start_s": round(ew_start, 3),
            "arrow_start_s": round(arrow_start, 3),
            "ns_start_s": round(ns_start, 3),
            "next_ew_start_s": round(ew_next, 3),
            "EW_duration_s": round(arrow_start - ew_start, 3),
            "N_ARROW_duration_s": round(ns_start - arrow_start, 3),
            "NS_duration_s": round(ew_next - ns_start, 3),
            "cycle_s": round(ew_next - ew_start, 3),
        })

    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze the three manually marked standard traffic-signal "
            "states: EW, N+arrow, NS."
        )
    )
    parser.add_argument(
        "marks",
        nargs="+",
        type=Path,
        help="One or more trajectory_manual_marks JSON files.",
    )
    args = parser.parse_args()

    try:
        marks = _merge_mark_files(args.marks)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    cycles = _cycle_rows(marks)

    ew_durations = [row["EW_duration_s"] for row in cycles]
    arrow_durations = [row["N_ARROW_duration_s"] for row in cycles]
    ns_durations = [row["NS_duration_s"] for row in cycles]
    cycle_durations = [row["cycle_s"] for row in cycles]

    print("Manual three-state cycle:")
    print(f"EW:       {_stats(ew_durations)}")
    print(f"N+arrow:  {_stats(arrow_durations)}")
    print(f"NS:       {_stats(ns_durations)}")
    print(f"Cycle:    {_stats(cycle_durations)}")

    print("\nPer-cycle:")
    for row in cycles:
        print(
            f"#{row['cycle_index']:>2}  "
            f"EW={row['EW_duration_s']:>5.1f}s  "
            f"N+arrow={row['N_ARROW_duration_s']:>5.1f}s  "
            f"NS={row['NS_duration_s']:>5.1f}s  "
            f"T={row['cycle_s']:>5.1f}s"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
