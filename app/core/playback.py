from __future__ import annotations

from pathlib import Path
from typing import Sequence

from app.core.reconstruction import reconstruct_file
from app.core.review_log import build_review_log, review_summary
from app.core.signal_state_estimator import SignalStateEstimator

PLAYBACK_STEP_SECONDS = 0.5
YELLOW_DURATION_SECONDS = 2.0


def _timeline_seconds(origin_ms: int, events: Sequence, step_seconds: float) -> list[float]:
    timestamps = [event.timestamp_ms for event in events]
    if not timestamps:
        return [0.0]
    duration = max(0.0, (max(timestamps) - origin_ms) / 1000.0)
    sample_count = max(1, int(duration / step_seconds))
    values = [round(index * step_seconds, 6) for index in range(sample_count + 1)]
    if values[-1] < duration:
        values.append(round(duration, 6))
    return values


def build_playback_payload(path: Path) -> dict[str, object]:
    """Run the same event-based reconstruction used by the production inference path."""
    reconstruction = reconstruct_file(path)
    trajectories = reconstruction.trajectories
    events = reconstruction.events
    cycle = reconstruction.cycle
    phase_model = reconstruction.phase_model
    origin = reconstruction.origin_timestamp_ms

    timestamps_s = _timeline_seconds(origin, events, PLAYBACK_STEP_SECONDS)
    estimator = SignalStateEstimator(
        phase_model,
        yellow_duration_seconds=YELLOW_DURATION_SECONDS,
        event_origin_ms=origin,
    )
    results = [estimator.estimate(timestamp_s, events) for timestamp_s in timestamps_s]

    timeline = []
    for result in results:
        snapshot = result.to_dict()
        snapshot["timestamp_ms"] = origin + int(round(result.timestamp_s * 1000.0))
        snapshot["approaches"] = {item["approach"]: item for item in snapshot["approaches"]}
        timeline.append(snapshot)

    review = review_summary(events, phase_model, timeline, cycle_confidence=float(cycle.estimate.confidence))
    review_log = build_review_log(
        events, phase_model, timeline, source_path=path,
        cycle_seconds=float(cycle.estimate.cycle_seconds),
        cycle_confidence=float(cycle.estimate.confidence),
    )

    return {
        "source": {
            "filename": path.name,
            "cars_used": len(trajectories),
            "events_used": len(events),
            "duration_s": timestamps_s[-1],
            "start_timestamp_ms": origin,
            "end_timestamp_ms": origin + int(round(timestamps_s[-1] * 1000.0)),
        },
        "ground_truth": "UNAVAILABLE",
        "model": "event_based_inference",
        "cycle": {
            "estimated_seconds": round(float(cycle.estimate.cycle_seconds), 3),
            "confidence": round(float(cycle.estimate.confidence), 4),
            "candidates": [candidate.to_dict() for candidate in cycle.estimate.candidate_periods],
        },
        "phase_model": phase_model.to_dict(),
        "yellow_duration_seconds": YELLOW_DURATION_SECONDS,
        "timeline": timeline,
        "diagnostics": [
            {
                "timestamp_ms": item["timestamp_ms"],
                "timestamp_s": item["timestamp_s"],
                "phase_id": item["phase_id"],
                "cycle_phase_s": item["cycle_phase_s"],
                "phase_confidence": item["phase_confidence"],
                "transition": item["transition"],
                "states": {approach: item["approaches"][approach]["state"] for approach in ("N", "S", "E", "W")},
            }
            for item in timeline
        ],
        "review": review,
        "review_log": review_log,
    }