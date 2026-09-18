from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from app.core.event_cycle_estimator import EventCycleEstimate, estimate_event_cycle
from app.core.event_phase_discovery import EventPhaseDiscovery, EventPhaseDiscoveryResult
from app.core.models import Trajectory, TrajectoryEvent
from app.core.preprocessing import load_trajectory_file
from app.core.trajectory_events import extract_trajectory_events
from app.core.trajectory_geometry import build_trajectory_geometry


@dataclass(frozen=True)
class BatchReconstruction:
    """Authoritative batch reconstruction shared by API, playback and validation."""

    trajectories: tuple[Trajectory, ...]
    events: tuple[TrajectoryEvent, ...]
    cycle: EventCycleEstimate
    phase_model: EventPhaseDiscoveryResult
    origin_timestamp_ms: int

    def to_dict(self) -> dict[str, object]:
        return {
            "origin_timestamp_ms": self.origin_timestamp_ms,
            "cycle": self.cycle.to_dict(),
            "phase_model": self.phase_model.to_dict(),
            "trajectory_count": len(self.trajectories),
            "event_count": len(self.events),
        }


def extract_events_from_trajectories(trajectories: Iterable[Trajectory]) -> list[TrajectoryEvent]:
    events: list[TrajectoryEvent] = []
    for trajectory in trajectories:
        events.extend(
            extract_trajectory_events(
                trajectory,
                build_trajectory_geometry(trajectory.to_record()),
            )
        )
    return events


def reconstruct_trajectories(
    trajectories: Sequence[Trajectory],
    *,
    sampling_seconds: float = 2.0,
    bin_seconds: float = 2.0,
) -> BatchReconstruction:
    normalized = tuple(trajectories)
    if not normalized:
        raise ValueError("no usable car trajectories found")

    events = tuple(extract_events_from_trajectories(normalized))
    cycle = estimate_event_cycle(events, sampling_seconds=sampling_seconds)
    phase_model = EventPhaseDiscovery(bin_seconds=bin_seconds).discover(
        events,
        cycle_seconds=cycle.estimate.cycle_seconds,
    )
    origin = int(phase_model.origin_timestamp_ms)
    return BatchReconstruction(
        trajectories=normalized,
        events=events,
        cycle=cycle,
        phase_model=phase_model,
        origin_timestamp_ms=origin,
    )


def reconstruct_file(path: Path, **kwargs: object) -> BatchReconstruction:
    return reconstruct_trajectories(load_trajectory_file(path), **kwargs)
