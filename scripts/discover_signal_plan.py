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
    args = parser.parse_args()

    trajectories = load_trajectory_file(args.path)
    events = extract_events_from_trajectories(trajectories)
    plan = SignalPlanDiscovery().discover(
        events,
        cycle_seconds=args.cycle_seconds,
    )

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
