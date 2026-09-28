from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.preprocessing import load_trajectory_file
from app.core.reconstruction import extract_events_from_trajectories
from app.core.signal_plan_discovery import SignalPlanDiscovery


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Discover a movement-level signal plan from trajectory JSON."
    )
    parser.add_argument("path", type=Path, help="Trajectory JSON file")
    parser.add_argument(
        "--cycle-seconds",
        type=float,
        default=None,
        help="Optional known cycle length; otherwise infer it from movement events.",
    )
    parser.add_argument(
        "--start-seconds",
        type=float,
        default=None,
        help="Optional analysis-window start, relative to the first usable event.",
    )
    parser.add_argument(
        "--window-seconds",
        type=float,
        default=None,
        help="Optional local analysis-window length.",
    )
    args = parser.parse_args()

    trajectories = load_trajectory_file(args.path)
    events = extract_events_from_trajectories(trajectories)

    if (args.start_seconds is None) != (args.window_seconds is None):
        parser.error("--start-seconds and --window-seconds must be supplied together")
    if args.start_seconds is not None and args.start_seconds < 0:
        parser.error("--start-seconds must be non-negative")
    if args.window_seconds is not None and args.window_seconds <= 0:
        parser.error("--window-seconds must be positive")

    analysis_events = events
    if args.start_seconds is not None and args.window_seconds is not None:
        if not events:
            parser.error("source contains no usable events")
        event_origin_ms = min(event.timestamp_ms for event in events)
        window_start_ms = event_origin_ms + int(args.start_seconds * 1000.0)
        window_end_ms = window_start_ms + int(args.window_seconds * 1000.0)
        analysis_events = [
            event
            for event in events
            if window_start_ms <= event.timestamp_ms < window_end_ms
        ]
        # The discovery period requires repeated evidence; a narrow local
        # window may contain too few RELEASEs to build a recurring profile.
        # Keep the CLI useful by reporting a clear, non-traceback error.
        if not analysis_events:
            parser.error("analysis window contains no usable events")

    try:
        plan = SignalPlanDiscovery().discover(
            analysis_events,
            cycle_seconds=args.cycle_seconds,
        )
    except ValueError as exc:
        parser.error(str(exc))

    print(
        json.dumps(
            plan.to_dict(),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
