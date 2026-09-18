from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.analyzer import estimate_cycle, load_trajectories
from app.core.cycle_estimator import CycleEstimator
from app.core.event_cycle_estimator import estimate_event_cycle
from app.core.models import TrajectoryEvent
from app.core.preprocessing import load_trajectory_file
from app.core.trajectory_events import extract_trajectory_events
from app.core.trajectory_geometry import TrajectoryGeometry


@dataclass(frozen=True)
class CycleMethodResult:
    method: str
    estimated_cycle: float
    candidate_periods: tuple[dict[str, float | int], ...]
    autocorrelation_strength: float
    confidence: float
    used_events: int
    used_trajectories: int

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "estimated_cycle": self.estimated_cycle,
            "candidate_periods": list(self.candidate_periods),
            "autocorrelation_strength": self.autocorrelation_strength,
            "confidence": self.confidence,
            "used_events": self.used_events,
            "used_trajectories": self.used_trajectories,
        }


@dataclass(frozen=True)
class CycleComparison:
    trajectory_based: CycleMethodResult
    event_based: CycleMethodResult

    def to_dict(self) -> dict[str, object]:
        return {
            "trajectory_based": self.trajectory_based.to_dict(),
            "event_based": self.event_based.to_dict(),
        }


def _event_list(path: Path) -> list[TrajectoryEvent]:
    trajectories = load_trajectory_file(path)
    events: list[TrajectoryEvent] = []
    for trajectory in trajectories:
        geometry = TrajectoryGeometry(trajectory.detections)
        events.extend(extract_trajectory_events(trajectory, geometry))
    return events


def compare_cycle_estimators(
    path: Path,
    *,
    estimator: CycleEstimator | None = None,
) -> CycleComparison:
    frame = load_trajectories(path)
    old_cycle, old_strength, old_candidates = estimate_cycle(frame)

    events = _event_list(path)
    event_estimate = estimate_event_cycle(
        events,
        estimator=estimator,
        min_events=8,
    )

    candidate_scores = [float(candidate["score"]) for candidate in old_candidates]
    score_sum = sum(candidate_scores)
    old_confidence = (
        candidate_scores[0] / score_sum
        if candidate_scores and score_sum > 0
        else 0.0
    )

    trajectory_result = CycleMethodResult(
        method="trajectory_based",
        estimated_cycle=float(old_cycle),
        candidate_periods=tuple(old_candidates),
        autocorrelation_strength=float(old_strength),
        confidence=round(max(0.0, min(1.0, old_confidence)), 4),
        used_events=0,
        used_trajectories=int(len(frame)),
    )
    event_result = CycleMethodResult(
        method="event_based",
        estimated_cycle=event_estimate.estimate.cycle_seconds,
        candidate_periods=tuple(
            candidate.to_dict()
            for candidate in event_estimate.estimate.candidate_periods
        ),
        autocorrelation_strength=(
            event_estimate.estimate.candidate_periods[0].strength
            if event_estimate.estimate.candidate_periods
            else 0.0
        ),
        confidence=event_estimate.estimate.confidence,
        used_events=event_estimate.flow.used_events,
        used_trajectories=int(len(frame)),
    )
    return CycleComparison(
        trajectory_based=trajectory_result,
        event_based=event_result,
    )
