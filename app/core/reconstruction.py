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


DEFAULT_SESSION_GAP_SECONDS = 30.0 * 60.0


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


@dataclass(frozen=True)
class SessionReconstruction:
    """Independent reconstruction result for one continuous traffic session."""

    start_timestamp_ms: int
    end_timestamp_ms: int
    duration_s: float
    trajectory_count: int
    event_count: int
    cycle: EventCycleEstimate | None
    phase_model: EventPhaseDiscoveryResult | None
    status: str
    confidence: float
    error_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "start_timestamp_ms": self.start_timestamp_ms,
            "end_timestamp_ms": self.end_timestamp_ms,
            "duration_s": self.duration_s,
            "trajectory_count": self.trajectory_count,
            "event_count": self.event_count,
            "status": self.status,
            "confidence": self.confidence,
            "error_reason": self.error_reason,
            "cycle": self.cycle.to_dict() if self.cycle is not None else None,
            "phase_model": (
                self.phase_model.to_dict()
                if self.phase_model is not None
                else None
            ),
        }


def extract_events_from_trajectories(
    trajectories: Iterable[Trajectory],
) -> list[TrajectoryEvent]:
    events: list[TrajectoryEvent] = []
    for trajectory in trajectories:
        events.extend(
            extract_trajectory_events(
                trajectory,
                build_trajectory_geometry(trajectory.to_record()),
            )
        )
    return events


def _estimate_models(
    events: Sequence[TrajectoryEvent],
    *,
    sampling_seconds: float,
    bin_seconds: float,
) -> tuple[EventCycleEstimate, EventPhaseDiscoveryResult]:
    cycle = estimate_event_cycle(
        events,
        sampling_seconds=sampling_seconds,
    )
    phase_model = EventPhaseDiscovery(bin_seconds=bin_seconds).discover(
        events,
        cycle_seconds=cycle.estimate.cycle_seconds,
    )
    return cycle, phase_model


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
    cycle, phase_model = _estimate_models(
        events,
        sampling_seconds=sampling_seconds,
        bin_seconds=bin_seconds,
    )
    origin = int(phase_model.origin_timestamp_ms)
    return BatchReconstruction(
        trajectories=normalized,
        events=events,
        cycle=cycle,
        phase_model=phase_model,
        origin_timestamp_ms=origin,
    )


def _trajectory_interval_ms(trajectory: Trajectory) -> tuple[int, int]:
    if trajectory.detections:
        timestamps = [detection.millis for detection in trajectory.detections]
        return min(timestamps), max(timestamps)
    timestamp = int(trajectory.timestamp_ms)
    return timestamp, timestamp


def _validate_session_gap(session_gap_seconds: float) -> int:
    if session_gap_seconds <= 0:
        raise ValueError("session_gap_seconds must be positive")
    return int(round(session_gap_seconds * 1000.0))


def split_trajectories_into_sessions(
    trajectories: Sequence[Trajectory],
    *,
    session_gap_seconds: float = DEFAULT_SESSION_GAP_SECONDS,
) -> list[tuple[Trajectory, ...]]:
    """Split trajectories at large unobserved time gaps.

    The input may be unordered.  A session remains open while trajectories
    overlap or begin within the configured gap of the latest observed end.
    """
    gap_ms = _validate_session_gap(session_gap_seconds)
    ordered = sorted(
        trajectories,
        key=lambda trajectory: (
            _trajectory_interval_ms(trajectory)[0],
            _trajectory_interval_ms(trajectory)[1],
        ),
    )
    if not ordered:
        return []

    sessions: list[list[Trajectory]] = []
    current = [ordered[0]]
    _, current_end_ms = _trajectory_interval_ms(ordered[0])

    for trajectory in ordered[1:]:
        start_ms, end_ms = _trajectory_interval_ms(trajectory)
        if start_ms - current_end_ms > gap_ms:
            sessions.append(current)
            current = [trajectory]
            current_end_ms = end_ms
            continue

        current.append(trajectory)
        current_end_ms = max(current_end_ms, end_ms)

    sessions.append(current)
    return [tuple(session) for session in sessions]


def split_events_into_sessions(
    events: Sequence[TrajectoryEvent],
    *,
    session_gap_seconds: float = DEFAULT_SESSION_GAP_SECONDS,
) -> list[tuple[TrajectoryEvent, ...]]:
    """Split unordered events whenever consecutive evidence is too far apart."""
    gap_ms = _validate_session_gap(session_gap_seconds)
    ordered = sorted(
        events,
        key=lambda event: (
            event.timestamp_ms,
            event.event_type.value,
            event.approach,
            event.movement,
        ),
    )
    if not ordered:
        return []

    sessions: list[list[TrajectoryEvent]] = [[ordered[0]]]
    previous_timestamp_ms = ordered[0].timestamp_ms

    for event in ordered[1:]:
        if event.timestamp_ms - previous_timestamp_ms > gap_ms:
            sessions.append([])
        sessions[-1].append(event)
        previous_timestamp_ms = event.timestamp_ms

    return [tuple(session) for session in sessions]


def _phase_confidence(phase_model: EventPhaseDiscoveryResult) -> float:
    if not phase_model.phases:
        return 0.0
    return sum(phase.confidence for phase in phase_model.phases) / len(
        phase_model.phases
    )


def _reconstruction_confidence(
    cycle: EventCycleEstimate,
    phase_model: EventPhaseDiscoveryResult,
) -> float:
    return round(
        max(
            0.0,
            min(
                1.0,
                min(
                    float(cycle.estimate.confidence),
                    _phase_confidence(phase_model),
                ),
            ),
        ),
        4,
    )


def reconstruct_event_session(
    events: Sequence[TrajectoryEvent],
    *,
    start_timestamp_ms: int,
    end_timestamp_ms: int,
    trajectory_count: int,
    sampling_seconds: float,
    bin_seconds: float,
) -> SessionReconstruction:
    ordered_events = tuple(
        sorted(
            events,
            key=lambda event: (
                event.timestamp_ms,
                event.event_type.value,
                event.approach,
                event.movement,
            ),
        )
    )
    duration_s = max(
        0.0,
        (end_timestamp_ms - start_timestamp_ms) / 1000.0,
    )

    try:
        cycle, phase_model = _estimate_models(
            ordered_events,
            sampling_seconds=sampling_seconds,
            bin_seconds=bin_seconds,
        )
    except ValueError as exc:
        return SessionReconstruction(
            start_timestamp_ms=start_timestamp_ms,
            end_timestamp_ms=end_timestamp_ms,
            duration_s=duration_s,
            trajectory_count=trajectory_count,
            event_count=len(ordered_events),
            cycle=None,
            phase_model=None,
            status="insufficient_data",
            confidence=0.0,
            error_reason=str(exc),
        )
    except Exception as exc:
        return SessionReconstruction(
            start_timestamp_ms=start_timestamp_ms,
            end_timestamp_ms=end_timestamp_ms,
            duration_s=duration_s,
            trajectory_count=trajectory_count,
            event_count=len(ordered_events),
            cycle=None,
            phase_model=None,
            status="error",
            confidence=0.0,
            error_reason=str(exc),
        )

    return SessionReconstruction(
        start_timestamp_ms=start_timestamp_ms,
        end_timestamp_ms=end_timestamp_ms,
        duration_s=duration_s,
        trajectory_count=trajectory_count,
        event_count=len(ordered_events),
        cycle=cycle,
        phase_model=phase_model,
        status="ok",
        confidence=_reconstruction_confidence(cycle, phase_model),
        error_reason=None,
    )


def reconstruct_trajectory_sessions(
    trajectories: Sequence[Trajectory],
    *,
    session_gap_seconds: float = DEFAULT_SESSION_GAP_SECONDS,
    sampling_seconds: float = 2.0,
    bin_seconds: float = 2.0,
) -> tuple[SessionReconstruction, ...]:
    """Reconstruct each continuous trajectory session independently."""
    sessions = split_trajectories_into_sessions(
        trajectories,
        session_gap_seconds=session_gap_seconds,
    )
    results: list[SessionReconstruction] = []

    for session in sessions:
        intervals = [_trajectory_interval_ms(item) for item in session]
        start_timestamp_ms = min(start for start, _ in intervals)
        end_timestamp_ms = max(end for _, end in intervals)
        events = extract_events_from_trajectories(session)
        results.append(
            reconstruct_event_session(
                events,
                start_timestamp_ms=start_timestamp_ms,
                end_timestamp_ms=end_timestamp_ms,
                trajectory_count=len(session),
                sampling_seconds=sampling_seconds,
                bin_seconds=bin_seconds,
            )
        )

    return tuple(results)


def reconstruct_event_sessions(
    events: Sequence[TrajectoryEvent],
    *,
    session_gap_seconds: float = DEFAULT_SESSION_GAP_SECONDS,
    sampling_seconds: float = 2.0,
    bin_seconds: float = 2.0,
) -> tuple[SessionReconstruction, ...]:
    """Reconstruct each continuous event session independently."""
    sessions = split_events_into_sessions(
        events,
        session_gap_seconds=session_gap_seconds,
    )
    results: list[SessionReconstruction] = []

    for session in sessions:
        start_timestamp_ms = session[0].timestamp_ms
        end_timestamp_ms = session[-1].timestamp_ms
        results.append(
            reconstruct_event_session(
                session,
                start_timestamp_ms=start_timestamp_ms,
                end_timestamp_ms=end_timestamp_ms,
                trajectory_count=0,
                sampling_seconds=sampling_seconds,
                bin_seconds=bin_seconds,
            )
        )

    return tuple(results)


def reconstruct_file(path: Path, **kwargs: object) -> BatchReconstruction:
    return reconstruct_trajectories(load_trajectory_file(path), **kwargs)
