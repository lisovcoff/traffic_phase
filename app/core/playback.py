from __future__ import annotations

from pathlib import Path

import numpy as np

from app.core.cycle_estimator import CycleEstimator
from app.core.phase_discovery import PhaseDiscovery
from app.core.preprocessing import load_trajectory_file, trajectories_to_frame
from app.core.review_log import build_review_log
from app.core.signal_state_estimator import SignalStateEstimator

SIGNAL_BIN_SECONDS = 2.0
YELLOW_DURATION_SECONDS = 2.0


def build_playback_payload(path: Path) -> dict[str, object]:
    """Run the current reconstruction pipeline and prepare browser playback data."""
    trajectories = load_trajectory_file(path)
    frame = trajectories_to_frame(trajectories)

    max_time = float(frame["t_s"].max())
    n_bins = max(2, int(np.ceil(max_time / SIGNAL_BIN_SECONDS)) + 1)
    signal = np.zeros(n_bins, dtype=float)
    delayed = frame[frame["stopped"]]
    for row in delayed.itertuples(index=False):
        index = min(int(row.t_s // SIGNAL_BIN_SECONDS), n_bins - 1)
        signal[index] += float(row.release_weight)

    cycle = CycleEstimator().estimate(signal, sampling_seconds=SIGNAL_BIN_SECONDS)
    phase_model = PhaseDiscovery(bin_seconds=SIGNAL_BIN_SECONDS).discover(
        frame,
        cycle_seconds=cycle.cycle_seconds,
    )
    estimator = SignalStateEstimator(
        phase_model,
        yellow_duration_seconds=YELLOW_DURATION_SECONDS,
    )

    ordered = frame.sort_values("timestamp_ms")
    timestamps_ms = ordered["timestamp_ms"].drop_duplicates().astype(int).tolist()
    base_ms = min(timestamps_ms)
    timestamps_s = [(timestamp - base_ms) / 1000.0 for timestamp in timestamps_ms]
    results = estimator.estimate_playback(path, timestamps_s)

    timeline = []
    for timestamp_ms, result in zip(timestamps_ms, results):
        snapshot = result.to_dict()
        snapshot["timestamp_ms"] = timestamp_ms
        snapshot["approaches"] = {
            item["approach"]: item for item in snapshot["approaches"]
        }
        timeline.append(snapshot)

    diagnostics = []
    for result in timeline:
        diagnostics.append(
            {
                "timestamp_ms": result["timestamp_ms"],
                "timestamp_s": result["timestamp_s"],
                "phase_id": result["phase_id"],
                "cycle_phase_s": result["cycle_phase_s"],
                "phase_confidence": result["phase_confidence"],
                "transition": result["transition"],
                "states": {
                    approach: state["state"]
                    for approach, state in result["approaches"].items()
                },
            }
        )

    review_log = build_review_log(
        frame,
        phase_model,
        timeline,
        source_path=path,
        cycle_seconds=float(cycle.cycle_seconds),
        cycle_confidence=float(cycle.confidence),
    )

    return {
        "source": {
            "filename": path.name,
            "cars_used": int(len(frame)),
            "duration_s": round(max_time, 3),
            "start_timestamp_ms": base_ms,
            "end_timestamp_ms": max(timestamps_ms),
        },
        "cycle": {
            "estimated_seconds": round(float(cycle.cycle_seconds), 3),
            "confidence": round(float(cycle.confidence), 4),
            "candidates": [candidate.to_dict() for candidate in cycle.candidate_periods],
        },
        "phase_model": phase_model.to_dict(),
        "yellow_duration_seconds": YELLOW_DURATION_SECONDS,
        "timeline": timeline,
        "diagnostics": diagnostics,
        "review_log": review_log,
    }
