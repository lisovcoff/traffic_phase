from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from app.core.analyzer import load_trajectories
from app.core.event_cycle_estimator import estimate_event_cycle
from app.core.event_phase_discovery import EventPhaseDiscovery
from app.core.models import EventType, TrajectoryEvent
from app.core.phase_discovery import PhaseDiscovery
from app.core.preprocessing import load_trajectory_file, trajectories_to_frame
from app.core.trajectory_events import extract_trajectory_events
from app.core.trajectory_geometry import TrajectoryGeometry


@dataclass(frozen=True)
class PhaseMethodResult:
    method: str
    cycle_seconds: float
    phases: tuple[dict[str, object], ...]
    cycle_coverage: float
    overlap: float
    supporting_event_count: int
    contradictory_event_count: int

    @property
    def contradictory_ratio(self) -> float:
        total = self.supporting_event_count + self.contradictory_event_count
        return (
            self.contradictory_event_count / total
            if total
            else 0.0
        )

    @property
    def supporting_ratio(self) -> float:
        total = self.supporting_event_count + self.contradictory_event_count
        return self.supporting_event_count / total if total else 0.0

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["supporting_ratio"] = round(self.supporting_ratio, 4)
        result["contradictory_ratio"] = round(self.contradictory_ratio, 4)
        return result


@dataclass(frozen=True)
class PhaseComparison:
    old: PhaseMethodResult
    event_based: PhaseMethodResult

    def to_dict(self) -> dict[str, object]:
        return {
            "old": self.old.to_dict(),
            "event_based": self.event_based.to_dict(),
        }


def _events(path: Path) -> list[TrajectoryEvent]:
    trajectories = load_trajectory_file(path)
    result: list[TrajectoryEvent] = []
    for trajectory in trajectories:
        geometry = TrajectoryGeometry(trajectory.detections)
        result.extend(extract_trajectory_events(trajectory, geometry))
    return result


def _event_counts_for_phases(
    phases,
    events: list[TrajectoryEvent],
    cycle: float,
) -> tuple[int, int]:
    relevant = [
        event
        for event in events
        if event.event_type in {EventType.RELEASE, EventType.CROSSING}
    ]
    supporting = 0
    contradictory = 0

    for event in relevant:
        position = ((event.timestamp_ms - min(e.timestamp_ms for e in relevant)) / 1000.0) % cycle
        for phase in phases:
            start = phase.phase_start
            end = phase.phase_end
            inside = (
                start <= position < end
                if start <= end
                else position >= start or position < end
            )
            if not inside:
                continue
            active = set(phase.active_approaches)
            if event.approach in active:
                supporting += 1
            else:
                contradictory += 1
            break
    return supporting, contradictory


def compare_phase_discovery(path: Path) -> PhaseComparison:
    frame = load_trajectories(path)
    trajectories = load_trajectory_file(path)
    events = _events(path)

    event_cycle = estimate_event_cycle(events).estimate.cycle_seconds
    old_frame = trajectories_to_frame(trajectories)
    old = PhaseDiscovery().discover(
        old_frame,
        cycle_seconds=event_cycle,
    )
    new = EventPhaseDiscovery().discover(
        events,
        cycle_seconds=event_cycle,
    )

    old_support, old_contradictory = _event_counts_for_phases(
        old.phases,
        events,
        event_cycle,
    )
    old_result = PhaseMethodResult(
        method="trajectory_based_phase_discovery",
        cycle_seconds=old.cycle_seconds,
        phases=tuple(phase.to_dict() for phase in old.phases),
        cycle_coverage=_phase_coverage(old.phases, event_cycle),
        overlap=_phase_overlap(old.phases, event_cycle, bin_seconds=2.0),
        supporting_event_count=old_support,
        contradictory_event_count=old_contradictory,
    )
    new_result = PhaseMethodResult(
        method="event_based_phase_discovery",
        cycle_seconds=new.cycle_seconds,
        phases=tuple(phase.to_dict() for phase in new.phases),
        cycle_coverage=new.cycle_coverage,
        overlap=new.overlap,
        supporting_event_count=new.supporting_event_count,
        contradictory_event_count=new.contradictory_event_count,
    )
    return PhaseComparison(old=old_result, event_based=new_result)


def _phase_coverage(phases, cycle: float) -> float:
    covered = 0.0
    for phase in phases:
        start = phase.phase_start
        end = phase.phase_end
        covered += end - start if start <= end else cycle - start + end
    return min(1.0, max(0.0, covered / cycle))


def _phase_overlap(phases, cycle: float, *, bin_seconds: float) -> float:
    bins = max(1, int(round(cycle / bin_seconds)))
    occupied = set()
    overlap = 0
    for phase in phases:
        start = int(round(phase.phase_start / bin_seconds))
        end = int(round(phase.phase_end / bin_seconds))
        indices = (
            range(start, end)
            if start < end
            else list(range(start, bins)) + list(range(0, end))
        )
        for index in indices:
            if index in occupied:
                overlap += 1
            occupied.add(index)
    return round(overlap / bins, 4)


def compare_phase_models(path: Path) -> PhaseComparison:
    return compare_phase_discovery(path)
