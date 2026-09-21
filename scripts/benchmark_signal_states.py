from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.reconstruction import reconstruct_file
from app.core.signal_state_estimator import SignalStateEstimator


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run production event-based signal-state reconstruction "
            "on one trajectory JSON."
        )
    )
    parser.add_argument("path", type=Path)
    parser.add_argument("--samples", type=int, default=12)
    args = parser.parse_args()

    reconstruction = reconstruct_file(args.path)
    trajectories = reconstruction.trajectories
    events = reconstruction.events
    cycle = reconstruction.cycle.estimate
    phase_model = reconstruction.phase_model
    origin_ms = reconstruction.origin_timestamp_ms

    max_time_s = max(
        0.0,
        (
            max(event.timestamp_ms for event in events)
            - origin_ms
        )
        / 1000.0,
    )
    if args.samples <= 1:
        timestamps = [0.0]
    else:
        step = max_time_s / float(args.samples - 1)
        timestamps = [
            round(index * step, 3)
            for index in range(args.samples)
        ]

    estimator = SignalStateEstimator(
        phase_model,
        event_origin_ms=origin_ms,
    )

    print(f"file={args.path}")
    print(
        f"trajectories={len(trajectories)} "
        f"events={len(events)}"
    )
    print(
        f"cycle={cycle.cycle_seconds:.2f}s "
        f"cycle_confidence={cycle.confidence:.4f}"
    )
    print(
        f"phase_coverage={phase_model.cycle_coverage:.4f} "
        f"phase_overlap={phase_model.overlap:.4f}"
    )
    for phase in phase_model.phases:
        print(
            "phase",
            json.dumps(
                phase.to_dict(),
                ensure_ascii=False,
            ),
        )

    print("\nstates")
    for timestamp_s in timestamps:
        result = estimator.estimate(
            timestamp_s,
            events,
        )
        state_map = {
            item.approach: item.state.value
            for item in result.approaches
        }
        print(
            f"t={timestamp_s:7.2f}s "
            f"phase={result.phase_id} "
            f"phase_conf={result.phase_confidence:.3f} "
            f"traffic_conf="
            f"{result.traffic_evidence_confidence:.3f} "
            f"states={state_map}"
        )


if __name__ == "__main__":
    main()
