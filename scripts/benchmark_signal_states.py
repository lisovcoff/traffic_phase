from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.event_cycle_estimator import build_event_flow_signal, estimate_event_cycle
from app.core.event_phase_discovery import EventPhaseDiscovery
from app.core.preprocessing import load_trajectory_file
from app.core.signal_state_estimator import SignalStateEstimator
from app.core.trajectory_events import extract_trajectory_events
from app.core.trajectory_geometry import TrajectoryGeometry


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run event-based signal-state reconstruction on a real trajectory JSON."
    )
    parser.add_argument("path", type=Path)
    parser.add_argument("--samples", type=int, default=12)
    args = parser.parse_args()

    trajectories = load_trajectory_file(args.path)
    events = []
    for trajectory in trajectories:
        events.extend(
            extract_trajectory_events(
                trajectory,
                TrajectoryGeometry(trajectory.detections),
            )
        )

    signal = build_event_flow_signal(events, sampling_seconds=2.0)
    cycle = estimate_event_cycle(signal)
    phase_model = EventPhaseDiscovery().discover(
        events,
        cycle_seconds=cycle.cycle_seconds,
    )

    origin_ms = min((event.timestamp_ms for event in events), default=0)
    max_time_s = max(
        0.0,
        (max(event.timestamp_ms for event in events) - origin_ms) / 1000.0,
    )
    if args.samples <= 1:
        timestamps = [0.0]
    else:
        step = max_time_s / float(args.samples - 1)
        timestamps = [round(index * step, 3) for index in range(args.samples)]

    estimator = SignalStateEstimator(phase_model, event_origin_ms=origin_ms)

    print(f"file={args.path}")
    print(f"trajectories={len(trajectories)} events={len(events)}")
    print(
        f"cycle={cycle.cycle_seconds:.2f}s "
        f"cycle_confidence={cycle.confidence:.4f}"
    )
    print(
        f"phase_coverage={phase_model.cycle_coverage:.4f} "
        f"phase_overlap={phase_model.overlap:.4f}"
    )
    for phase in phase_model.phases:
        print("phase", json.dumps(phase.to_dict(), ensure_ascii=False))

    print("\nstates")
    for timestamp_s in timestamps:
        result = estimator.estimate(timestamp_s, events)
        state_map = {
            item.approach: item.state.value
            for item in result.approaches
        }
        print(
            f"t={timestamp_s:7.2f}s "
            f"phase={result.phase_id} "
            f"phase_conf={result.phase_confidence:.3f} "
            f"traffic_conf={result.traffic_evidence_confidence:.3f} "
            f"states={state_map}"
        )


if __name__ == "__main__":
    main()
