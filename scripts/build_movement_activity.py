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
from app.core.cycle_estimator import CycleEstimator


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


def _circular_distance(
    left: float,
    right: float,
    cycle_seconds: float,
) -> float:
    distance = abs(left - right) % cycle_seconds
    return min(distance, cycle_seconds - distance)


def _circular_median(
    values: list[float],
    cycle_seconds: float,
) -> float:
    if not values:
        return 0.0
    return min(
        values,
        key=lambda candidate: sum(
            _circular_distance(
                candidate,
                value,
                cycle_seconds,
            )
            for value in values
        ),
    )


def _movement_event_signal(
    rows: list[dict[str, object]],
) -> tuple[int, list[float]]:
    seconds = [int(row["second"]) for row in rows]
    if not seconds:
        return 0, []
    start = min(seconds)
    end = max(seconds)
    signal = [0.0] * (end - start + 1)
    for row in rows:
        signal[int(row["second"]) - start] += (
            float(row["release_count"])
            + 0.5 * float(row["crossing_count"])
        )
    return start, signal


def _cycle_candidates(
    signal: list[float],
    *,
    min_cycle_seconds: int,
    max_cycle_seconds: int,
) -> list[dict[str, object]]:
    if len(signal) < max(60, min_cycle_seconds * 3):
        return []

    try:
        estimate = CycleEstimator(
            min_period_seconds=float(min_cycle_seconds),
            max_period_seconds=float(max_cycle_seconds),
            peak_distance_seconds=10.0,
            smoothing_sigma=1.2,
            max_candidates=6,
        ).estimate(
            signal,
            sampling_seconds=1.0,
        )
    except (RuntimeError, ValueError):
        return []

    return [
        {
            "cycle_seconds": candidate.period_seconds,
            "score": candidate.score,
            "strength": candidate.strength,
            "stability": candidate.stability,
            "repetitions": candidate.repetitions,
        }
        for candidate in estimate.candidate_periods
    ]


def _cluster_cycle_candidates(
    movement_candidates: dict[str, list[dict[str, object]]],
    *,
    tolerance_seconds: float = 3.0,
) -> list[dict[str, object]]:
    clusters: list[dict[str, object]] = []

    for movement, candidates in movement_candidates.items():
        for candidate in candidates:
            period = float(candidate["cycle_seconds"])
            weight = (
                float(candidate["score"])
                * min(
                    1.0,
                    float(candidate["repetitions"]) / 8.0,
                )
            )
            compatible = [
                cluster
                for cluster in clusters
                if abs(
                    float(cluster["period_seconds"])
                    - period
                ) <= tolerance_seconds
                and movement not in cluster["movements"]
            ]
            if compatible:
                cluster = min(
                    compatible,
                    key=lambda item: abs(
                        float(item["period_seconds"])
                        - period
                    ),
                )
            else:
                cluster = {
                    "period_seconds": period,
                    "movements": set(),
                    "entries": [],
                }
                clusters.append(cluster)

            cluster["movements"].add(movement)
            cluster["entries"].append(
                {
                    "movement": movement,
                    "period_seconds": period,
                    "score": float(candidate["score"]),
                    "weight": weight,
                    "repetitions": int(candidate["repetitions"]),
                }
            )

            periods = [
                float(entry["period_seconds"])
                for entry in cluster["entries"]
            ]
            cluster["period_seconds"] = sum(periods) / len(periods)

    normalized: list[dict[str, object]] = []
    for cluster in clusters:
        entries = cluster["entries"]
        if not entries:
            continue
        weighted_score = sum(
            float(entry["weight"])
            for entry in entries
        ) / len(entries)
        mean_score = sum(
            float(entry["score"])
            for entry in entries
        ) / len(entries)
        mean_repetitions = sum(
            int(entry["repetitions"])
            for entry in entries
        ) / len(entries)
        normalized.append(
            {
                "cycle_seconds": round(
                    float(cluster["period_seconds"]),
                    2,
                ),
                "movement_count": len(
                    cluster["movements"]
                ),
                "weighted_score": round(
                    weighted_score,
                    4,
                ),
                "mean_score": round(
                    mean_score,
                    4,
                ),
                "mean_repetitions": round(
                    mean_repetitions,
                    2,
                ),
                "movements": sorted(
                    cluster["movements"]
                ),
            }
        )

    normalized.sort(
        key=lambda item: (
            -int(item["movement_count"]),
            -float(item["weighted_score"]),
            -float(item["mean_repetitions"]),
            float(item["cycle_seconds"]),
        )
    )
    return normalized


def _phase_support(
    seconds: list[int],
    *,
    start_second: int,
    cycle_seconds: int,
    total_cycles: int,
) -> list[float]:
    presence = [set() for _ in range(cycle_seconds)]
    cycle_ids = {
        (second - start_second) // cycle_seconds
        for second in seconds
        if 0 <= (second - start_second) // cycle_seconds < total_cycles
    }
    denominator = max(1, len(cycle_ids))

    for second in seconds:
        relative = second - start_second
        cycle_id, phase = divmod(
            relative,
            cycle_seconds,
        )
        if 0 <= cycle_id < total_cycles:
            presence[phase].add(cycle_id)

    return [
        len(cycle_presence) / denominator
        for cycle_presence in presence
    ]


def _phase_windows(
    phase_support: list[float],
    *,
    threshold: float,
    min_duration_seconds: int = 3,
) -> list[tuple[float, float, float]]:
    mask = [
        value >= threshold
        for value in phase_support
    ]
    size = len(mask)
    if size == 0 or not any(mask):
        return []

    windows: list[tuple[float, float, float]] = []
    doubled = mask + mask

    start = 0
    while start < size:
        if not doubled[start]:
            start += 1
            continue

        end = start
        while (
            end < start + size
            and doubled[end]
        ):
            end += 1

        duration = min(
            size,
            end - start,
        )
        if duration >= min_duration_seconds:
            phase_start = start % size
            phase_end = (
                start + duration
            ) % size
            support = sum(
                phase_support[
                    (start + offset) % size
                ]
                for offset in range(duration)
            ) / duration
            windows.append(
                (
                    float(phase_start),
                    float(phase_end),
                    float(support),
                )
            )

        start = end

    unique: list[tuple[float, float, float]] = []
    seen: set[tuple[float, float]] = set()
    for window in windows:
        key = (
            window[0],
            window[1],
        )
        if key not in seen:
            seen.add(key)
            unique.append(window)
    return unique


def _activity_windows(
    rows: list[dict[str, object]],
    *,
    start_second: int,
    cycle_seconds: int,
    total_cycles: int,
    minimum_support: float = 0.50,
) -> list[tuple[float, float, float]]:
    moving_seconds = [
        int(row["second"])
        for row in rows
        if int(row["moving_tracks"]) > 0
    ]
    return _phase_windows(
        _phase_support(
            moving_seconds,
            start_second=start_second,
            cycle_seconds=cycle_seconds,
            total_cycles=total_cycles,
        ),
        threshold=minimum_support,
        min_duration_seconds=4,
    )


def discover_movement_profiles(
    activity: dict[str, object],
    *,
    cycle_seconds: float | None = None,
    min_cycle_seconds: int = 20,
    max_cycle_seconds: int = 180,
    min_event_cycles: int = 3,
) -> dict[str, object]:
    """Discover recurring movement timing from full, dense signals.

    Cycle candidates are estimated from full per-second RELEASE/CROSSING
    signals rather than correlating only non-zero event pairs. Movement
    consensus is used to suppress short-period aliases and harmonics.
    This remains a timing/evidence layer, never a GREEN/RED classifier.
    """
    raw_rows = activity.get("rows", [])
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for raw_row in raw_rows:
        movement = str(
            raw_row.get("movement", "")
        ).strip()
        if "->" in movement:
            grouped[movement].append(raw_row)

    movement_candidates: dict[
        str,
        list[dict[str, object]],
    ] = {}
    for movement, rows in grouped.items():
        _start, signal = _movement_event_signal(rows)
        movement_candidates[movement] = (
            _cycle_candidates(
                signal,
                min_cycle_seconds=min_cycle_seconds,
                max_cycle_seconds=max_cycle_seconds,
            )
            if signal
            else []
        )

    global_candidates = _cluster_cycle_candidates(
        movement_candidates,
    )

    if not global_candidates:
        _start, global_signal = _movement_event_signal(
            [
                row
                for rows in grouped.values()
                for row in rows
            ]
        )
        fallback_candidates = _cycle_candidates(
            global_signal,
            min_cycle_seconds=min_cycle_seconds,
            max_cycle_seconds=max_cycle_seconds,
        )
        global_candidates = [
            {
                "cycle_seconds": candidate["cycle_seconds"],
                "movement_count": 1,
                "weighted_score": candidate["score"],
                "mean_score": candidate["score"],
                "mean_repetitions": candidate["repetitions"],
                "movements": ["__aggregate__"],
            }
            for candidate in fallback_candidates
        ]

    selected_cycle = (
        float(cycle_seconds)
        if cycle_seconds is not None
        else (
            float(
                global_candidates[0]["cycle_seconds"]
            )
            if global_candidates
            else None
        )
    )

    if selected_cycle is None:
        return {
            "schema_version": 2,
            "meaning": (
                "Recurring movement timing profiles derived from full-signal "
                "autocorrelation. These are hypotheses about recurring flow "
                "windows, not GREEN/RED lamp classifications."
            ),
            "selected_cycle_seconds": None,
            "global_cycle_candidates": [],
            "movement_profiles": [],
        }

    selected_cycle_int = max(
        min_cycle_seconds,
        min(
            max_cycle_seconds,
            int(round(selected_cycle)),
        ),
    )

    all_event_seconds = [
        int(row["second"])
        for rows in grouped.values()
        for row in rows
        if (
            int(row["release_count"]) > 0
            or int(row["crossing_count"]) > 0
        )
    ]
    if not all_event_seconds:
        return {
            "schema_version": 2,
            "meaning": (
                "Recurring movement timing profiles derived from full-signal "
                "autocorrelation. These are hypotheses about recurring flow "
                "windows, not GREEN/RED lamp classifications."
            ),
            "selected_cycle_seconds": float(
                selected_cycle_int
            ),
            "global_cycle_candidates": global_candidates[:10],
            "movement_profiles": [],
        }

    start_second = min(all_event_seconds)
    end_second = max(all_event_seconds)
    total_cycles = max(
        1,
        int(
            (end_second - start_second)
            // selected_cycle_int
        )
        + 1,
    )

    profiles: list[dict[str, object]] = []
    for movement, rows in sorted(grouped.items()):
        release_seconds = [
            int(row["second"])
            for row in rows
            if int(row["release_count"]) > 0
        ]
        crossing_seconds = [
            int(row["second"])
            for row in rows
            if int(row["crossing_count"]) > 0
        ]
        event_seconds = sorted(
            set(release_seconds)
            | set(crossing_seconds)
        )

        observed_cycles = len({
            (second - start_second) // selected_cycle_int
            for second in event_seconds
            if (
                0
                <= (second - start_second)
                // selected_cycle_int
                < total_cycles
            )
        })

        phase_support = _phase_support(
            event_seconds,
            start_second=start_second,
            cycle_seconds=selected_cycle_int,
            total_cycles=total_cycles,
        )
        event_windows = _phase_windows(
            phase_support,
            threshold=0.35,
        )
        activity_windows = _activity_windows(
            rows,
            start_second=start_second,
            cycle_seconds=selected_cycle_int,
            total_cycles=total_cycles,
        )

        approach = movement.split("->", 1)[0]
        approach_rows = [
            row
            for other_movement, other_rows in grouped.items()
            if other_movement.split("->", 1)[0] == approach
            for row in other_rows
        ]
        approach_event_seconds = sorted({
            int(row["second"])
            for row in approach_rows
            if (
                int(row["release_count"]) > 0
                or int(row["crossing_count"]) > 0
            )
        })
        approach_support = _phase_support(
            approach_event_seconds,
            start_second=start_second,
            cycle_seconds=selected_cycle_int,
            total_cycles=total_cycles,
        )
        movement_mask = [value >= 0.35 for value in phase_support]
        approach_mask = [value >= 0.35 for value in approach_support]
        intersection = sum(
            movement_value and approach_value
            for movement_value, approach_value in zip(
                movement_mask,
                approach_mask,
            )
        )
        union = sum(
            movement_value or approach_value
            for movement_value, approach_value in zip(
                movement_mask,
                approach_mask,
            )
        )
        jaccard = intersection / union if union else 0.0

        release_phases = [
            float((second - start_second) % selected_cycle_int)
            for second in release_seconds
        ]
        crossing_phases = [
            float((second - start_second) % selected_cycle_int)
            for second in crossing_seconds
        ]
        release_median = _circular_median(
            release_phases,
            selected_cycle_int,
        )
        crossing_median = _circular_median(
            crossing_phases,
            selected_cycle_int,
        )
        release_repeatability = (
            sum(
                _circular_distance(
                    value,
                    release_median,
                    selected_cycle_int,
                ) <= 4.0
                for value in release_phases
            )
            / len(release_phases)
            if release_phases
            else 0.0
        )
        crossing_repeatability = (
            sum(
                _circular_distance(
                    value,
                    crossing_median,
                    selected_cycle_int,
                ) <= 4.0
                for value in crossing_phases
            )
            / len(crossing_phases)
            if crossing_phases
            else 0.0
        )

        nearby_candidates = [
            candidate
            for candidate in movement_candidates.get(movement, [])
            if abs(
                float(candidate["cycle_seconds"])
                - selected_cycle_int
            ) <= 3.0
        ]

        profiles.append({
            "movement": movement,
            "approach": approach,
            "observed_event_cycles": observed_cycles,
            "release_event_count": len(release_seconds),
            "crossing_event_count": len(crossing_seconds),
            "release_phase_median_s": round(release_median, 2),
            "crossing_phase_median_s": round(crossing_median, 2),
            "release_repeatability": round(release_repeatability, 4),
            "crossing_repeatability": round(crossing_repeatability, 4),
            "event_windows": [
                {
                    "phase_start_s": round(window_start, 2),
                    "phase_end_s": round(window_end, 2),
                    "mean_cycle_support": round(support, 4),
                }
                for window_start, window_end, support in event_windows
            ],
            "activity_windows": [
                {
                    "phase_start_s": round(window_start, 2),
                    "phase_end_s": round(window_end, 2),
                    "mean_cycle_support": round(support, 4),
                }
                for window_start, window_end, support in activity_windows
            ],
            "movement_vs_approach_jaccard": round(jaccard, 4),
            "distinct_from_approach": bool(
                observed_cycles >= min_event_cycles
                and bool(activity_windows)
                and jaccard < 0.60
            ),
            "movement_cycle_candidate_seconds": (
                nearby_candidates[0]["cycle_seconds"]
                if nearby_candidates
                else None
            ),
            "top_cycle_candidates": nearby_candidates[:5],
        })

    profiles.sort(
        key=lambda item: (
            -int(item["observed_event_cycles"]),
            -float(item["release_repeatability"]),
            str(item["movement"]),
        )
    )
    return {
        "schema_version": 2,
        "meaning": (
            "Recurring movement timing profiles derived from full-signal "
            "autocorrelation. These are hypotheses about recurring flow "
            "windows, not GREEN/RED lamp classifications."
        ),
        "selected_cycle_seconds": float(selected_cycle_int),
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
