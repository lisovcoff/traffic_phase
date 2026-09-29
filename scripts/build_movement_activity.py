from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.models import EventType, Trajectory, TrajectoryEvent
from app.core.preprocessing import load_trajectory_file
from app.core.trajectory_geometry import haversine_distance_m
from app.core.reconstruction import extract_events_from_trajectories


def _second_range(trajectory: Trajectory) -> range:
    if not trajectory.detections:
        return range(0)
    start = trajectory.detections[0].millis // 1000
    end = trajectory.detections[-1].millis // 1000
    return range(start, end + 1)


def build_movement_activity(
    trajectories: list[Trajectory],
    events: list[TrajectoryEvent],
    *,
    timezone_offset_minutes: int | None = None,
) -> dict[str, object]:
    """Build a second-by-second movement evidence matrix.

    This is deliberately an evidence layer, not a traffic-light classifier.
    A row says which tracked vehicles were observed for a movement and which
    STOP/RELEASE/CROSSING events occurred in that second. It never equates
    vehicle presence or motion with GREEN.
    """
    active: dict[tuple[int, str], set[object]] = defaultdict(set)
    motion_status: dict[tuple[int, str, object], str] = {}
    event_counts: dict[tuple[int, str], dict[str, int]] = defaultdict(
        lambda: {event_type.value.lower(): 0 for event_type in EventType}
    )

    for trajectory in trajectories:
        movement = trajectory.movement
        if not movement or "->" not in movement:
            continue

        for second in _second_range(trajectory):
            active[(second, movement)].add(trajectory.vehicle_id)

        detections = trajectory.detections
        for first, second_detection in zip(detections, detections[1:]):
            dt_s = (second_detection.millis - first.millis) / 1000.0
            if dt_s <= 0.0 or dt_s > 2.0:
                continue

            speed_mps = (
                haversine_distance_m(first, second_detection) / dt_s
            )
            if speed_mps <= 0.8:
                status = "stopped"
            elif speed_mps >= 2.0:
                status = "moving"
            else:
                status = "unknown"

            start_second = first.millis // 1000
            end_second = (second_detection.millis - 1) // 1000
            for second in range(start_second, end_second + 1):
                key = (second, movement, trajectory.vehicle_id)
                previous = motion_status.get(key)
                motion_status[key] = (
                    status
                    if previous is None
                    else status
                    if previous == status
                    else "unknown"
                )

    for event in events:
        if not event.movement or "->" not in event.movement:
            continue
        second = event.timestamp_ms // 1000
        event_counts[(second, event.movement)][event.event_type.value.lower()] += 1

    keys = sorted(set(active) | set(event_counts) | {
        (second, movement)
        for second, movement, _vehicle_id in motion_status
    })
    rows: list[dict[str, object]] = []
    timeline_start_second = min(
        (second for second, _movement in keys),
        default=None,
    )
    for second, movement in keys:
        counts = event_counts[(second, movement)]
        active_tracks = active[(second, movement)]
        moving_tracks = {
            vehicle_id
            for (status_second, status_movement, vehicle_id), status
            in motion_status.items()
            if (
                status_second == second
                and status_movement == movement
                and status == "moving"
            )
        }
        stopped_tracks = {
            vehicle_id
            for (status_second, status_movement, vehicle_id), status
            in motion_status.items()
            if (
                status_second == second
                and status_movement == movement
                and status == "stopped"
            )
        }
        motion_unknown_tracks = {
            vehicle_id
            for (status_second, status_movement, vehicle_id), status
            in motion_status.items()
            if (
                status_second == second
                and status_movement == movement
                and status == "unknown"
            )
        }

        row = {
            "second": second,
            "movement": movement,
            "active_tracks": len(active_tracks),
            "moving_tracks": len(moving_tracks),
            "stopped_tracks": len(stopped_tracks),
            "motion_unknown_tracks": len(motion_unknown_tracks),
            "stop_count": counts["stop"],
            "release_count": counts["release"],
            "crossing_count": counts["crossing"],
            "approach_count": counts["approach"],
            "absolute_time_utc": (
                datetime.fromtimestamp(second, tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            ),
            "elapsed_s": (
                float(second - timeline_start_second)
                if timeline_start_second is not None
                else 0.0
            ),
            "evidence_score": (
                min(1.0, len(active_tracks) / 5.0)
                + min(1.0, counts["release"] / 2.0)
                + min(1.0, counts["crossing"] / 2.0)
            ),
        }
        if timezone_offset_minutes is not None:
            local_timezone = timezone(
                timedelta(minutes=timezone_offset_minutes)
            )
            local_time = datetime.fromtimestamp(
                second,
                tz=local_timezone,
            )
            row["absolute_time_local"] = local_time.isoformat()
        rows.append(row)

    movements = sorted({row["movement"] for row in rows})
    result = {
        "schema_version": 2,
        "meaning": (
            "Movement activity/evidence matrix. active_tracks means a "
            "trajectory has detections spanning that second; event counts "
            "are extracted from the production event pipeline. This is not "
            "a GREEN/RED classifier."
        ),
        "trajectory_count": len(trajectories),
        "event_count": len(events),
        "movements": movements,
        "motion_thresholds_mps": {
            "stopped_max": 0.8,
            "moving_min": 2.0,
        },
        "timezone_offset_minutes": timezone_offset_minutes,
        "timeline_start_second": timeline_start_second,
        "timeline_start_time_utc": (
            datetime.fromtimestamp(timeline_start_second, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
            if timeline_start_second is not None
            else None
        ),
        "rows": rows,
    }
    return result



def _circular_distance(left: float, right: float, cycle_seconds: float) -> float:
    distance = abs(left - right) % cycle_seconds
    return min(distance, cycle_seconds - distance)


def _circular_median(values: list[float], cycle_seconds: float) -> float:
    if not values:
        return 0.0
    return min(
        values,
        key=lambda candidate: sum(
            _circular_distance(candidate, value, cycle_seconds)
            for value in values
        ),
    )


def _movement_event_signal(rows: list[dict[str, object]]) -> dict[int, float]:
    signal: dict[int, float] = {}
    for row in rows:
        second = int(row["second"])
        signal[second] = (
            signal.get(second, 0.0)
            + float(row["release_count"])
            + 0.5 * float(row["crossing_count"])
        )
    return signal


def _lag_score(
    signal: dict[int, float],
    lag_seconds: int,
) -> tuple[float, int]:
    if not signal:
        return 0.0, 0

    start = min(signal)
    end = max(signal)
    left = [
        signal.get(second, 0.0)
        for second in range(start, end - lag_seconds + 1)
    ]
    right = [
        signal.get(second + lag_seconds, 0.0)
        for second in range(start, end - lag_seconds + 1)
    ]
    overlap = sum(1 for value in left if value > 0.0 or right[len([*[]])] > 0.0)
    # The expression above is intentionally not used for scoring; keep the
    # actual non-zero pair count explicit below to avoid treating silence as
    # recurrence evidence.
    paired = [
        (a, b)
        for a, b in zip(left, right)
        if a > 0.0 and b > 0.0
    ]
    if len(paired) < 3:
        return 0.0, len(paired)

    numerator = sum(a * b for a, b in paired)
    denominator = math.sqrt(
        sum(a * a for a, _ in paired)
        * sum(b * b for _, b in paired)
    )
    return (numerator / denominator if denominator else 0.0), len(paired)


def _run_intervals(mask: list[bool]) -> list[tuple[int, int]]:
    size = len(mask)
    if size == 0 or not any(mask):
        return []
    if all(mask):
        return [(0, size)]

    runs: list[tuple[int, int]] = []
    start = None
    for index, value in enumerate(mask):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, size))

    if len(runs) >= 2 and runs[0][0] == 0 and runs[-1][1] == size:
        first_start, first_end = runs[0]
        last_start, last_end = runs[-1]
        runs = [(last_start, first_end)] + runs[1:-1]
    return runs


def _phase_windows(
    phase_support: list[float],
    *,
    threshold: float,
    min_duration_seconds: int = 3,
) -> list[tuple[float, float, float]]:
    mask = [value >= threshold for value in phase_support]
    intervals = _run_intervals(mask)
    size = len(mask)
    result: list[tuple[float, float, float]] = []
    for start, end in intervals:
        duration = (end - start) % size
        if duration == 0:
            duration = size
        if duration < min_duration_seconds:
            continue
        values = [
            phase_support[index % size]
            for index in range(start, start + duration)
        ]
        result.append(
            (
                float(start),
                float((start + duration) % size),
                float(sum(values) / len(values)),
            )
        )
    return result


def discover_movement_profiles(
    activity: dict[str, object],
    *,
    cycle_seconds: float | None = None,
    min_cycle_seconds: int = 20,
    max_cycle_seconds: int = 180,
    min_event_cycles: int = 3,
) -> dict[str, object]:
    """Discover recurring movement timing from RELEASE/CROSSING pulses.

    This is a timing-profile layer only. It does not assign GREEN/RED and
    does not convert vehicle motion into a lamp state.
    """
    raw_rows = activity.get("rows", [])
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for raw_row in raw_rows:
        movement = str(raw_row.get("movement", "")).strip()
        if "->" in movement:
            grouped[movement].append(raw_row)

    movement_candidates: dict[str, list[dict[str, object]]] = {}
    for movement, rows in grouped.items():
        signal = _movement_event_signal(rows)
        if len(signal) < min_event_cycles:
            movement_candidates[movement] = []
            continue

        max_lag = min(max_cycle_seconds, max(0, (max(signal) - min(signal)) // 2))
        candidates: list[dict[str, object]] = []
        for lag in range(min_cycle_seconds, max_lag + 1):
            score, paired = _lag_score(signal, lag)
            if paired >= 3 and score > 0.0:
                candidates.append(
                    {
                        "cycle_seconds": lag,
                        "score": round(score, 4),
                        "paired_event_seconds": paired,
                    }
                )
        candidates.sort(
            key=lambda item: (
                -float(item["score"]),
                -int(item["paired_event_seconds"]),
                int(item["cycle_seconds"]),
            )
        )
        movement_candidates[movement] = candidates[:5]

    all_scores: dict[int, list[float]] = defaultdict(list)
    for candidates in movement_candidates.values():
        for candidate in candidates:
            all_scores[int(candidate["cycle_seconds"])].append(
                float(candidate["score"])
            )
    global_candidates = [
        {
            "cycle_seconds": cycle,
            "movement_count": len(scores),
            "mean_score": round(sum(scores) / len(scores), 4),
        }
        for cycle, scores in all_scores.items()
    ]
    global_candidates.sort(
        key=lambda item: (
            -int(item["movement_count"]),
            -float(item["mean_score"]),
            int(item["cycle_seconds"]),
        )
    )

    selected_cycle = (
        float(cycle_seconds)
        if cycle_seconds is not None
        else (
            float(global_candidates[0]["cycle_seconds"])
            if global_candidates
            else None
        )
    )

    profiles: list[dict[str, object]] = []
    if selected_cycle is not None:
        selected_cycle_int = int(round(selected_cycle))
        start_second = min(
            int(row["second"])
            for raw_rows in grouped.values()
            for row in raw_rows
        )
        end_second = max(
            int(row["second"])
            for raw_rows in grouped.values()
            for row in raw_rows
        )
        total_cycles = max(
            1,
            int(math.floor((end_second - start_second + 1) / selected_cycle_int)),
        )

        for movement, rows in sorted(grouped.items()):
            signal = _movement_event_signal(rows)
            release_by_cycle: list[float] = []
            crossing_by_cycle: list[float] = []
            event_cycles: set[int] = set()

            for second, value in sorted(signal.items()):
                cycle_id = int((second - start_second) // selected_cycle_int)
                if 0 <= cycle_id < total_cycles and value > 0.0:
                    event_cycles.add(cycle_id)

            for row in rows:
                second = int(row["second"])
                cycle_id = int((second - start_second) // selected_cycle_int)
                if not 0 <= cycle_id < total_cycles:
                    continue
                phase = float((second - start_second) % selected_cycle_int)
                if int(row["release_count"]) > 0:
                    release_by_cycle.append(phase)
                if int(row["crossing_count"]) > 0:
                    crossing_by_cycle.append(phase)

            observed_cycles = len(event_cycles)
            phase_support = [0.0] * selected_cycle_int
            cycle_presence = [set() for _ in range(selected_cycle_int)]
            for second, value in signal.items():
                if value <= 0.0:
                    continue
                phase = int((second - start_second) % selected_cycle_int)
                cycle_id = int((second - start_second) // selected_cycle_int)
                if 0 <= cycle_id < total_cycles:
                    cycle_presence[phase].add(cycle_id)
            if observed_cycles:
                phase_support = [
                    len(cycle_ids) / observed_cycles
                    for cycle_ids in cycle_presence
                ]

            windows = _phase_windows(
                phase_support,
                threshold=0.35,
            )

            approach = movement.split("->", 1)[0]
            approach_mask = [False] * selected_cycle_int
            approach_cycles: list[int] = []
            for other_movement, other_rows in grouped.items():
                if other_movement.split("->", 1)[0] != approach:
                    continue
                other_signal = _movement_event_signal(other_rows)
                for second, value in other_signal.items():
                    if value <= 0.0:
                        continue
                    phase = int((second - start_second) % selected_cycle_int)
                    approach_mask[phase] = True
                    approach_cycles.append(
                        int((second - start_second) // selected_cycle_int)
                    )

            movement_mask = [
                value >= 0.35
                for value in phase_support
            ]
            approach_support = [
                0.0 for _ in range(selected_cycle_int)
            ]
            approach_cycle_ids = set(approach_cycles)
            if approach_cycle_ids:
                for phase in range(selected_cycle_int):
                    phase_cycles = {
                        int((second - start_second) // selected_cycle_int)
                        for other_movement, other_rows in grouped.items()
                        if other_movement.split("->", 1)[0] == approach
                        for second, value in _movement_event_signal(other_rows).items()
                        if value > 0.0
                        and int((second - start_second) % selected_cycle_int) == phase
                    }
                    approach_support[phase] = (
                        len(phase_cycles) / max(1, len(approach_cycle_ids))
                    )
            approach_mask = [
                value >= 0.35
                for value in approach_support
            ]
            intersection = sum(
                movement_value and approach_value
                for movement_value, approach_value
                in zip(movement_mask, approach_mask)
            )
            union = sum(
                movement_value or approach_value
                for movement_value, approach_value
                in zip(movement_mask, approach_mask)
            )
            jaccard = intersection / union if union else 0.0

            release_median = _circular_median(
                release_by_cycle,
                selected_cycle_int,
            )
            crossing_median = _circular_median(
                crossing_by_cycle,
                selected_cycle_int,
            )
            release_repeatability = (
                sum(
                    _circular_distance(
                        value,
                        release_median,
                        selected_cycle_int,
                    ) <= 4.0
                    for value in release_by_cycle
                )
                / len(release_by_cycle)
                if release_by_cycle
                else 0.0
            )
            crossing_repeatability = (
                sum(
                    _circular_distance(
                        value,
                        crossing_median,
                        selected_cycle_int,
                    ) <= 4.0
                    for value in crossing_by_cycle
                )
                / len(crossing_by_cycle)
                if crossing_by_cycle
                else 0.0
            )

            profiles.append(
                {
                    "movement": movement,
                    "approach": approach,
                    "observed_event_cycles": observed_cycles,
                    "release_event_count": len(release_by_cycle),
                    "crossing_event_count": len(crossing_by_cycle),
                    "release_phase_median_s": round(release_median, 2),
                    "crossing_phase_median_s": round(crossing_median, 2),
                    "release_repeatability": round(release_repeatability, 4),
                    "crossing_repeatability": round(crossing_repeatability, 4),
                    "recurring_windows": [
                        {
                            "phase_start_s": round(start, 2),
                            "phase_end_s": round(end, 2),
                            "mean_cycle_support": round(support, 4),
                        }
                        for start, end, support in windows
                    ],
                    "movement_vs_approach_jaccard": round(jaccard, 4),
                    "distinct_from_approach": bool(
                        observed_cycles >= min_event_cycles
                        and len(windows) > 0
                        and jaccard < 0.60
                    ),
                    "top_cycle_candidates": movement_candidates.get(movement, []),
                }
            )

    profiles.sort(
        key=lambda item: (
            -int(item["observed_event_cycles"]),
            -float(item["release_repeatability"]),
            str(item["movement"]),
        )
    )
    return {
        "schema_version": 1,
        "meaning": (
            "Recurring movement timing profiles derived from RELEASE/CROSSING "
            "evidence. These are hypotheses about recurring flow windows, not "
            "GREEN/RED lamp classifications."
        ),
        "selected_cycle_seconds": selected_cycle,
        "global_cycle_candidates": global_candidates[:10],
        "movement_profiles": profiles,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a second-by-second movement activity/evidence matrix."
    )
    parser.add_argument("path", type=Path, help="Trajectory JSON file")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("movement_activity.json"),
        help="Output JSON path",
    )
    parser.add_argument(
        "--start-seconds",
        type=float,
        default=None,
        help="Optional window start relative to the first trajectory detection",
    )
    parser.add_argument(
        "--window-seconds",
        type=float,
        default=None,
        help="Optional analysis-window length",
    )
    parser.add_argument(
        "--timezone-offset-minutes",
        type=int,
        default=None,
        help=(
            "Optional wall-clock offset from UTC for human-readable timestamps; "
            "for Chelyabinsk use 300"
        ),
    )
    parser.add_argument(
        "--discover-profiles",
        action="store_true",
        help="Add recurring movement timing profiles to the output",
    )
    parser.add_argument(
        "--cycle-seconds",
        type=float,
        default=None,
        help="Optional cycle length to use for movement profile folding",
    )
    args = parser.parse_args()

    if (args.start_seconds is None) != (args.window_seconds is None):
        parser.error("--start-seconds and --window-seconds must be supplied together")
    if args.start_seconds is not None and args.start_seconds < 0:
        parser.error("--start-seconds must be non-negative")
    if args.window_seconds is not None and args.window_seconds <= 0:
        parser.error("--window-seconds must be positive")

    trajectories = load_trajectory_file(args.path)
    if not trajectories:
        parser.error("source contains no usable car trajectories")

    if args.start_seconds is not None:
        first_detection_ms = min(
            detection.millis
            for trajectory in trajectories
            for detection in trajectory.detections
        )
        start_ms = first_detection_ms + int(args.start_seconds * 1000)
        end_ms = start_ms + int(args.window_seconds * 1000)

        trajectories = [
            trajectory
            for trajectory in trajectories
            if any(
                start_ms <= detection.millis < end_ms
                for detection in trajectory.detections
            )
        ]

    events = extract_events_from_trajectories(trajectories)
    result = build_movement_activity(
        trajectories,
        events,
        timezone_offset_minutes=args.timezone_offset_minutes,
    )
    if args.discover_profiles:
        result["movement_profile_discovery"] = discover_movement_profiles(
            result,
            cycle_seconds=args.cycle_seconds,
        )
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        f"Movement activity: {len(result['rows'])} rows, "
        f"{len(result['movements'])} movements, "
        f"{result['trajectory_count']} trajectories, "
        f"{result['event_count']} events"
    )
    print(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
