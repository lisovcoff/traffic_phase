from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median


def _load_marks(path: Path) -> dict[str, list[float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    marks = payload.get("marks") if isinstance(payload, dict) else None
    if not isinstance(marks, list):
        raise ValueError("marks JSON must contain a 'marks' list")

    result: dict[str, list[float]] = {"EW": [], "NS": []}
    for item in marks:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        timestamp_ms = item.get("timestamp_ms")
        if kind in result and isinstance(timestamp_ms, (int, float)):
            result[kind].append(float(timestamp_ms))

    for values in result.values():
        values.sort()
    return result


def _circular_distance(
    phase_s: float,
    boundary_s: float,
    period_s: float,
) -> float:
    delta = abs(phase_s - boundary_s)
    return min(delta, period_s - delta)


def _phase_distance(
    timestamp_ms: float,
    *,
    origin_ms: float,
    period_s: float,
    boundary_s: float,
) -> tuple[float, float]:
    phase_s = ((timestamp_ms - origin_ms) / 1000.0) % period_s
    return phase_s, _circular_distance(phase_s, boundary_s, period_s)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare manually marked EW/NS phase starts with the shared "
            "phase boundaries produced by discover_kinematic_cycle."
        )
    )
    parser.add_argument("cycle_result", type=Path)
    parser.add_argument("marks", type=Path)
    parser.add_argument(
        "--boundary-tolerance",
        type=float,
        default=10.0,
        help="Flag marks farther than this many seconds from their model boundary.",
    )
    args = parser.parse_args()

    result = json.loads(args.cycle_result.read_text(encoding="utf-8"))
    model = result.get("model")
    if not isinstance(model, dict):
        parser.error("cycle result must contain model (schema_version=2)")

    period = result.get("selected_cycle_seconds")
    origin_ms = result.get("origin_timestamp_ms")
    if not isinstance(period, (int, float)) or not isinstance(origin_ms, (int, float)):
        parser.error("cycle result is missing numeric period/origin")

    stage1 = model.get("stage_1")
    stage3 = model.get("stage_3")
    if not isinstance(stage1, dict) or not isinstance(stage3, dict):
        parser.error("model must contain stage_1 and stage_3")

    stage1_end = stage1.get("end_s")
    stage3_start = stage3.get("start_s")
    if not isinstance(stage1_end, (int, float)) or not isinstance(
        stage3_start, (int, float)
    ):
        parser.error("model must contain numeric stage boundaries")

    boundary_by_kind = {
        "EW": 0.0,
        "NS": float(stage3_start),
    }

    marks = _load_marks(args.marks)
    rows: list[dict[str, object]] = []
    all_distances: list[float] = []

    for kind in ("EW", "NS"):
        for timestamp_ms in marks[kind]:
            phase_s, distance_s = _phase_distance(
                timestamp_ms,
                origin_ms=float(origin_ms),
                period_s=float(period),
                boundary_s=boundary_by_kind[kind],
            )
            all_distances.append(distance_s)
            rows.append({
                "kind": kind,
                "timestamp_ms": int(timestamp_ms),
                "phase_s": round(phase_s, 3),
                "nearest_boundary_s": round(distance_s, 3),
                "within_tolerance": distance_s <= args.boundary_tolerance,
            })

    print(
        f"Model: T={period}s, EW_start=0s, "
        f"NS_start={boundary_by_kind['NS']:g}s, "
        f"mixed_boundary={float(stage1_end):g}s"
    )
    if all_distances:
        print(
            f"Manual marks: {len(all_distances)}, "
            f"mean distance={mean(all_distances):.3f}s, "
            f"median distance={median(all_distances):.3f}s, "
            f"within {args.boundary_tolerance:g}s="
            f"{sum(distance <= args.boundary_tolerance for distance in all_distances)}/"
            f"{len(all_distances)}"
        )

    for row in rows:
        print(
            f"{row['kind']} {row['timestamp_ms']}: "
            f"phase={row['phase_s']}s, "
            f"nearest_boundary={row['nearest_boundary_s']}s, "
            f"within={row['within_tolerance']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
