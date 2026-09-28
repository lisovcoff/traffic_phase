from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from app.core.models import EventType, Trajectory, TrajectoryEvent
from app.core.preprocessing import load_trajectory_file
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
) -> dict[str, object]:
    """Build a second-by-second movement evidence matrix.

    This is deliberately an evidence layer, not a traffic-light classifier.
    A row says which tracked vehicles were observed for a movement and which
    STOP/RELEASE/CROSSING events occurred in that second. It never equates
    vehicle presence or motion with GREEN.
    """
    active: dict[tuple[int, str], set[object]] = defaultdict(set)
    event_counts: dict[tuple[int, str], dict[str, int]] = defaultdict(
        lambda: {event_type.value.lower(): 0 for event_type in EventType}
    )

    for trajectory in trajectories:
        movement = trajectory.movement
        if not movement or "->" not in movement:
            continue
        for second in _second_range(trajectory):
            active[(second, movement)].add(trajectory.vehicle_id)

    for event in events:
        if not event.movement or "->" not in event.movement:
            continue
        second = event.timestamp_ms // 1000
        event_counts[(second, event.movement)][event.event_type.value.lower()] += 1

    keys = sorted(set(active) | set(event_counts))
    rows: list[dict[str, object]] = []
    for second, movement in keys:
        counts = event_counts[(second, movement)]
        rows.append(
            {
                "second": second,
                "movement": movement,
                "active_tracks": len(active[(second, movement)]),
                "stop_count": counts["stop"],
                "release_count": counts["release"],
                "crossing_count": counts["crossing"],
                "approach_count": counts["approach"],
                "evidence_score": (
                    min(1.0, len(active[(second, movement)]) / 5.0)
                    + min(1.0, counts["release"] / 2.0)
                    + min(1.0, counts["crossing"] / 2.0)
                ),
            }
        )

    movements = sorted({row["movement"] for row in rows})
    return {
        "schema_version": 1,
        "meaning": (
            "Movement activity/evidence matrix. active_tracks means a "
            "trajectory has detections spanning that second; event counts "
            "are extracted from the production event pipeline. This is not "
            "a GREEN/RED classifier."
        ),
        "trajectory_count": len(trajectories),
        "event_count": len(events),
        "movements": movements,
        "rows": rows,
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
    result = build_movement_activity(trajectories, events)
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
