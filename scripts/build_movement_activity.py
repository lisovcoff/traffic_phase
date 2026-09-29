from __future__ import annotations

import argparse
import json
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
            local_time = (
                datetime.fromtimestamp(second, tz=timezone.utc)
                + timedelta(minutes=timezone_offset_minutes)
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
