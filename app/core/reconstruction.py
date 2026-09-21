from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, replace
from pathlib import Path
import statistics
from typing import Iterable, Sequence

from app.core.event_cycle_estimator import EventCycleEstimate, estimate_event_cycle
from app.core.event_phase_discovery import EventPhaseDiscovery, EventPhaseDiscoveryResult
from app.core.models import Trajectory, TrajectoryEvent
from app.core.preprocessing import load_trajectory_file
from app.core.trajectory_events import extract_trajectory_events
from app.core.trajectory_geometry import build_trajectory_geometry


DEFAULT_SESSION_GAP_SECONDS = 30.0 * 60.0
DEFAULT_REGIME_WINDOW_SECONDS = 60.0 * 60.0
DEFAULT_REGIME_STEP_SECONDS = 30.0 * 60.0
DEFAULT_REGIME_CONFIRMATION_WINDOWS = 3
DEFAULT_REGIME_PERIOD_TOLERANCE_SECONDS = 6.0
DEFAULT_REGIME_MIN_CYCLE_CONFIDENCE = 0.45
DEFAULT_MIN_PHASE_SECONDS = 8.0
DEFAULT_PHASE_AMBIGUITY_CONFIDENCE = 0.55


@dataclass(frozen=True)
class BatchReconstruction:
    """Authoritative batch reconstruction shared by API and diagnostics."""

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
class RollingCycleWindow:
    start_timestamp_ms: int
    end_timestamp_ms: int
    period_seconds: float
    confidence: float


@dataclass(frozen=True)
class EventRegimeSlice:
    start_timestamp_ms: int
    end_timestamp_ms: int
    events: tuple[TrajectoryEvent, ...]
    rolling_period_seconds: float | None = None
    rolling_window_count: int = 0


@dataclass(frozen=True)
class SessionReconstruction:
    """Independent reconstruction for one stable regime of a traffic session."""

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
    session_index: int = 1
    regime_index: int = 1
    regime_count: int = 1
    rolling_period_seconds: float | None = None
    rolling_window_count: int = 0

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
            "session_index": self.session_index,
            "regime_index": self.regime_index,
            "regime_count": self.regime_count,
            "rolling_period_seconds": self.rolling_period_seconds,
            "rolling_window_count": self.rolling_window_count,
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


def _phase_duration_seconds(
    phase_start: float,
    phase_end: float,
    cycle_seconds: float,
) -> float:
    duration = (float(phase_end) - float(phase_start)) % float(cycle_seconds)
    return float(cycle_seconds) if duration <= 0.0 else duration


def phase_model_ambiguity_reason(
    phase_model: EventPhaseDiscoveryResult,
    *,
    min_phase_seconds: float = DEFAULT_MIN_PHASE_SECONDS,
    weak_confidence: float = DEFAULT_PHASE_AMBIGUITY_CONFIDENCE,
) -> str | None:
    """Reject a floor-bound phase only when its evidence is weak/conflicting.

    A real short phase is still allowed when it has strong repeated support.
    The guard targets optimizer collapse where a weak group is pushed exactly
    to the configured minimum and then presented as a physical signal phase.
    """
    tolerance = max(0.001, phase_model.bin_seconds * 0.25)
    for phase in phase_model.phases:
        duration = _phase_duration_seconds(
            phase.phase_start,
            phase.phase_end,
            phase_model.cycle_seconds,
        )
        total = (
            phase.supporting_event_count
            + phase.contradictory_event_count
        )
        support_ratio = (
            phase.supporting_event_count / total
            if total
            else 0.0
        )
        weak = (
            phase.confidence < weak_confidence
            or support_ratio < 0.5
        )
        if duration <= min_phase_seconds + tolerance and weak:
            return (
                "ambiguous phase model: phase "
                f"{phase.phase_id} collapsed to the minimum duration "
                f"({duration:.1f}s) with weak/conflicting evidence "
                f"(confidence={phase.confidence:.4f}, "
                f"support_ratio={support_ratio:.4f})"
            )
    return None


def reconstruct_trajectories(
    trajectories: Sequence[Trajectory],
    *,
    sampling_seconds: float = 2.0,
    bin_seconds: float = 2.0,
) -> BatchReconstruction:
    """Single-regime helper kept for small files and benchmark compatibility."""
    normalized = tuple(trajectories)
    if not normalized:
        raise ValueError("no usable car trajectories found")

    events = tuple(extract_events_from_trajectories(normalized))
    cycle, phase_model = _estimate_models(
        events,
        sampling_seconds=sampling_seconds,
        bin_seconds=bin_seconds,
    )
    ambiguity = phase_model_ambiguity_reason(phase_model)
    if ambiguity is not None:
        raise ValueError(ambiguity)
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
    """Split trajectories at large unobserved time gaps."""
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


def _rolling_cycle_windows(
    events: Sequence[TrajectoryEvent],
    *,
    window_seconds: float,
    step_seconds: float,
    sampling_seconds: float,
    min_cycle_confidence: float,
) -> tuple[RollingCycleWindow, ...]:
    if window_seconds <= 0 or step_seconds <= 0:
        raise ValueError("regime window and step must be positive")
    if not 0.0 <= min_cycle_confidence <= 1.0:
        raise ValueError("min_cycle_confidence must be in [0, 1]")

    ordered = tuple(
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
    if not ordered:
        return ()

    start_ms = ordered[0].timestamp_ms
    end_ms = ordered[-1].timestamp_ms
    window_ms = int(round(window_seconds * 1000.0))
    step_ms = int(round(step_seconds * 1000.0))
    if end_ms - start_ms < window_ms:
        return ()

    timestamps = [event.timestamp_ms for event in ordered]
    windows: list[RollingCycleWindow] = []
    window_start = start_ms
    while window_start + window_ms <= end_ms + step_ms:
        window_end = min(end_ms, window_start + window_ms)
        if window_end - window_start < window_ms * 0.75:
            break
        left = bisect_left(timestamps, window_start)
        right = bisect_left(timestamps, window_end)
        sample = ordered[left:right]
        if sample:
            try:
                result = estimate_event_cycle(
                    sample,
                    sampling_seconds=sampling_seconds,
                )
            except ValueError:
                result = None
            if (
                result is not None
                and result.estimate.confidence >= min_cycle_confidence
            ):
                windows.append(
                    RollingCycleWindow(
                        start_timestamp_ms=window_start,
                        end_timestamp_ms=window_end,
                        period_seconds=float(
                            result.estimate.cycle_seconds
                        ),
                        confidence=float(
                            result.estimate.confidence
                        ),
                    )
                )
        window_start += step_ms
    return tuple(windows)


def _periods_consistent(
    left: float,
    right: float,
    *,
    tolerance_seconds: float,
) -> bool:
    return abs(float(left) - float(right)) <= tolerance_seconds


def confirmed_cycle_regime_boundaries(
    windows: Sequence[RollingCycleWindow],
    *,
    confirmation_windows: int = DEFAULT_REGIME_CONFIRMATION_WINDOWS,
    tolerance_seconds: float = DEFAULT_REGIME_PERIOD_TOLERANCE_SECONDS,
) -> tuple[int, ...]:
    """Return boundaries only after a run of consistent changed windows."""
    if confirmation_windows < 2:
        raise ValueError("confirmation_windows must be at least 2")
    if tolerance_seconds <= 0:
        raise ValueError("tolerance_seconds must be positive")
    if len(windows) < confirmation_windows + 1:
        return ()

    current_period = float(windows[0].period_seconds)
    current_periods = [current_period]
    pending: list[RollingCycleWindow] = []
    boundaries: list[int] = []

    for window in windows[1:]:
        baseline = float(statistics.median(current_periods[-5:]))
        if _periods_consistent(
            window.period_seconds,
            baseline,
            tolerance_seconds=tolerance_seconds,
        ):
            current_periods.append(float(window.period_seconds))
            pending = []
            continue

        if not pending:
            pending = [window]
        else:
            pending_period = float(
                statistics.median(
                    item.period_seconds for item in pending
                )
            )
            if _periods_consistent(
                window.period_seconds,
                pending_period,
                tolerance_seconds=tolerance_seconds,
            ):
                pending.append(window)
            else:
                pending = [window]

        if len(pending) < confirmation_windows:
            continue

        candidate = float(
            statistics.median(
                item.period_seconds for item in pending
            )
        )
        if _periods_consistent(
            candidate,
            baseline,
            tolerance_seconds=tolerance_seconds,
        ):
            current_periods.extend(
                float(item.period_seconds) for item in pending
            )
            pending = []
            continue

        first = pending[0]
        boundary_ms = int(
            first.start_timestamp_ms
            + (
                first.end_timestamp_ms
                - first.start_timestamp_ms
            )
            / 2
        )
        if not boundaries or boundary_ms > boundaries[-1]:
            boundaries.append(boundary_ms)
        current_period = candidate
        current_periods = [
            float(item.period_seconds) for item in pending
        ]
        pending = []

    return tuple(boundaries)


def split_event_session_into_regimes(
    events: Sequence[TrajectoryEvent],
    *,
    start_timestamp_ms: int | None = None,
    end_timestamp_ms: int | None = None,
    sampling_seconds: float = 2.0,
    regime_window_seconds: float = DEFAULT_REGIME_WINDOW_SECONDS,
    regime_step_seconds: float = DEFAULT_REGIME_STEP_SECONDS,
    regime_confirmation_windows: int = DEFAULT_REGIME_CONFIRMATION_WINDOWS,
    regime_period_tolerance_seconds: float = DEFAULT_REGIME_PERIOD_TOLERANCE_SECONDS,
    regime_min_cycle_confidence: float = DEFAULT_REGIME_MIN_CYCLE_CONFIDENCE,
) -> tuple[EventRegimeSlice, ...]:
    ordered = tuple(
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
    if not ordered:
        return ()

    physical_start = int(
        start_timestamp_ms
        if start_timestamp_ms is not None
        else ordered[0].timestamp_ms
    )
    physical_end = int(
        end_timestamp_ms
        if end_timestamp_ms is not None
        else ordered[-1].timestamp_ms
    )
    windows = _rolling_cycle_windows(
        ordered,
        window_seconds=regime_window_seconds,
        step_seconds=regime_step_seconds,
        sampling_seconds=sampling_seconds,
        min_cycle_confidence=regime_min_cycle_confidence,
    )
    boundaries = confirmed_cycle_regime_boundaries(
        windows,
        confirmation_windows=regime_confirmation_windows,
        tolerance_seconds=regime_period_tolerance_seconds,
    )
    boundaries = tuple(
        boundary
        for boundary in boundaries
        if physical_start < boundary <= physical_end
    )
    timestamps = [event.timestamp_ms for event in ordered]
    edges = (physical_start, *boundaries, physical_end + 1)
    slices: list[EventRegimeSlice] = []

    for index in range(len(edges) - 1):
        left_ms = int(edges[index])
        right_exclusive_ms = int(edges[index + 1])
        left = bisect_left(timestamps, left_ms)
        right = bisect_left(timestamps, right_exclusive_ms)
        regime_events = ordered[left:right]
        if not regime_events:
            continue
        matching_windows = [
            window
            for window in windows
            if (
                window.start_timestamp_ms >= left_ms
                and window.end_timestamp_ms < right_exclusive_ms
            )
        ]
        rolling_period = (
            round(
                float(
                    statistics.median(
                        item.period_seconds
                        for item in matching_windows
                    )
                ),
                4,
            )
            if matching_windows
            else None
        )
        slices.append(
            EventRegimeSlice(
                start_timestamp_ms=left_ms,
                end_timestamp_ms=right_exclusive_ms - 1,
                events=regime_events,
                rolling_period_seconds=rolling_period,
                rolling_window_count=len(matching_windows),
            )
        )

    return tuple(slices) if slices else (
        EventRegimeSlice(
            start_timestamp_ms=physical_start,
            end_timestamp_ms=physical_end,
            events=ordered,
        ),
    )


def _phase_confidence(
    phase_model: EventPhaseDiscoveryResult,
) -> float:
    if not phase_model.phases:
        return 0.0
    return sum(
        phase.confidence for phase in phase_model.phases
    ) / len(phase_model.phases)


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
    session_index: int = 1,
    regime_index: int = 1,
    regime_count: int = 1,
    rolling_period_seconds: float | None = None,
    rolling_window_count: int = 0,
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
            session_index=session_index,
            regime_index=regime_index,
            regime_count=regime_count,
            rolling_period_seconds=rolling_period_seconds,
            rolling_window_count=rolling_window_count,
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
            session_index=session_index,
            regime_index=regime_index,
            regime_count=regime_count,
            rolling_period_seconds=rolling_period_seconds,
            rolling_window_count=rolling_window_count,
        )

    ambiguity = phase_model_ambiguity_reason(phase_model)
    if ambiguity is not None:
        return SessionReconstruction(
            start_timestamp_ms=start_timestamp_ms,
            end_timestamp_ms=end_timestamp_ms,
            duration_s=duration_s,
            trajectory_count=trajectory_count,
            event_count=len(ordered_events),
            cycle=cycle,
            phase_model=None,
            status="ambiguous",
            confidence=0.0,
            error_reason=ambiguity,
            session_index=session_index,
            regime_index=regime_index,
            regime_count=regime_count,
            rolling_period_seconds=rolling_period_seconds,
            rolling_window_count=rolling_window_count,
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
        confidence=_reconstruction_confidence(
            cycle,
            phase_model,
        ),
        error_reason=None,
        session_index=session_index,
        regime_index=regime_index,
        regime_count=regime_count,
        rolling_period_seconds=rolling_period_seconds,
        rolling_window_count=rolling_window_count,
    )


def _trajectory_counts_by_regime(
    trajectory_end_timestamps_ms: Sequence[int] | None,
    regimes: Sequence[EventRegimeSlice],
    fallback_total: int,
) -> list[int]:
    if not regimes:
        return []
    if trajectory_end_timestamps_ms:
        ordered = sorted(int(item) for item in trajectory_end_timestamps_ms)
        counts: list[int] = []
        for regime in regimes:
            left = bisect_left(ordered, regime.start_timestamp_ms)
            right = bisect_left(
                ordered,
                regime.end_timestamp_ms + 1,
            )
            counts.append(right - left)
        return counts
    if len(regimes) == 1:
        return [int(fallback_total)]

    total_events = sum(len(regime.events) for regime in regimes)
    if total_events <= 0:
        return [0 for _ in regimes]
    raw = [
        fallback_total * len(regime.events) / total_events
        for regime in regimes
    ]
    counts = [int(value) for value in raw]
    remainder = fallback_total - sum(counts)
    for index in sorted(
        range(len(regimes)),
        key=lambda i: raw[i] - counts[i],
        reverse=True,
    )[:remainder]:
        counts[index] += 1
    return counts


def reconstruct_event_regimes(
    events: Sequence[TrajectoryEvent],
    *,
    start_timestamp_ms: int,
    end_timestamp_ms: int,
    trajectory_count: int,
    trajectory_end_timestamps_ms: Sequence[int] | None = None,
    session_index: int = 1,
    sampling_seconds: float = 2.0,
    bin_seconds: float = 2.0,
    regime_window_seconds: float = DEFAULT_REGIME_WINDOW_SECONDS,
    regime_step_seconds: float = DEFAULT_REGIME_STEP_SECONDS,
    regime_confirmation_windows: int = DEFAULT_REGIME_CONFIRMATION_WINDOWS,
    regime_period_tolerance_seconds: float = DEFAULT_REGIME_PERIOD_TOLERANCE_SECONDS,
    regime_min_cycle_confidence: float = DEFAULT_REGIME_MIN_CYCLE_CONFIDENCE,
) -> tuple[SessionReconstruction, ...]:
    regimes = split_event_session_into_regimes(
        events,
        start_timestamp_ms=start_timestamp_ms,
        end_timestamp_ms=end_timestamp_ms,
        sampling_seconds=sampling_seconds,
        regime_window_seconds=regime_window_seconds,
        regime_step_seconds=regime_step_seconds,
        regime_confirmation_windows=regime_confirmation_windows,
        regime_period_tolerance_seconds=regime_period_tolerance_seconds,
        regime_min_cycle_confidence=regime_min_cycle_confidence,
    )
    if not regimes:
        return ()
    counts = _trajectory_counts_by_regime(
        trajectory_end_timestamps_ms,
        regimes,
        trajectory_count,
    )
    results = [
        reconstruct_event_session(
            regime.events,
            start_timestamp_ms=regime.start_timestamp_ms,
            end_timestamp_ms=regime.end_timestamp_ms,
            trajectory_count=counts[index],
            sampling_seconds=sampling_seconds,
            bin_seconds=bin_seconds,
            session_index=session_index,
            regime_index=index + 1,
            regime_count=len(regimes),
            rolling_period_seconds=regime.rolling_period_seconds,
            rolling_window_count=regime.rolling_window_count,
        )
        for index, regime in enumerate(regimes)
    ]
    return tuple(results)


def reconstruct_trajectory_sessions(
    trajectories: Sequence[Trajectory],
    *,
    session_gap_seconds: float = DEFAULT_SESSION_GAP_SECONDS,
    sampling_seconds: float = 2.0,
    bin_seconds: float = 2.0,
    regime_window_seconds: float = DEFAULT_REGIME_WINDOW_SECONDS,
    regime_step_seconds: float = DEFAULT_REGIME_STEP_SECONDS,
    regime_confirmation_windows: int = DEFAULT_REGIME_CONFIRMATION_WINDOWS,
    regime_period_tolerance_seconds: float = DEFAULT_REGIME_PERIOD_TOLERANCE_SECONDS,
    regime_min_cycle_confidence: float = DEFAULT_REGIME_MIN_CYCLE_CONFIDENCE,
) -> tuple[SessionReconstruction, ...]:
    """Reconstruct stable regimes inside every continuous traffic session."""
    sessions = split_trajectories_into_sessions(
        trajectories,
        session_gap_seconds=session_gap_seconds,
    )
    results: list[SessionReconstruction] = []

    for session_index, session in enumerate(sessions, start=1):
        intervals = [
            _trajectory_interval_ms(item)
            for item in session
        ]
        start_timestamp_ms = min(start for start, _ in intervals)
        end_timestamp_ms = max(end for _, end in intervals)
        events = extract_events_from_trajectories(session)
        results.extend(
            reconstruct_event_regimes(
                events,
                start_timestamp_ms=start_timestamp_ms,
                end_timestamp_ms=end_timestamp_ms,
                trajectory_count=len(session),
                trajectory_end_timestamps_ms=[
                    end for _, end in intervals
                ],
                session_index=session_index,
                sampling_seconds=sampling_seconds,
                bin_seconds=bin_seconds,
                regime_window_seconds=regime_window_seconds,
                regime_step_seconds=regime_step_seconds,
                regime_confirmation_windows=regime_confirmation_windows,
                regime_period_tolerance_seconds=regime_period_tolerance_seconds,
                regime_min_cycle_confidence=regime_min_cycle_confidence,
            )
        )

    return tuple(results)


def reconstruct_event_sessions(
    events: Sequence[TrajectoryEvent],
    *,
    session_gap_seconds: float = DEFAULT_SESSION_GAP_SECONDS,
    sampling_seconds: float = 2.0,
    bin_seconds: float = 2.0,
    regime_window_seconds: float = DEFAULT_REGIME_WINDOW_SECONDS,
    regime_step_seconds: float = DEFAULT_REGIME_STEP_SECONDS,
    regime_confirmation_windows: int = DEFAULT_REGIME_CONFIRMATION_WINDOWS,
    regime_period_tolerance_seconds: float = DEFAULT_REGIME_PERIOD_TOLERANCE_SECONDS,
    regime_min_cycle_confidence: float = DEFAULT_REGIME_MIN_CYCLE_CONFIDENCE,
) -> tuple[SessionReconstruction, ...]:
    """Authoritative event path: physical sessions first, stable regimes next."""
    sessions = split_events_into_sessions(
        events,
        session_gap_seconds=session_gap_seconds,
    )
    results: list[SessionReconstruction] = []

    for session_index, session in enumerate(sessions, start=1):
        results.extend(
            reconstruct_event_regimes(
                session,
                start_timestamp_ms=session[0].timestamp_ms,
                end_timestamp_ms=session[-1].timestamp_ms,
                trajectory_count=0,
                session_index=session_index,
                sampling_seconds=sampling_seconds,
                bin_seconds=bin_seconds,
                regime_window_seconds=regime_window_seconds,
                regime_step_seconds=regime_step_seconds,
                regime_confirmation_windows=regime_confirmation_windows,
                regime_period_tolerance_seconds=regime_period_tolerance_seconds,
                regime_min_cycle_confidence=regime_min_cycle_confidence,
            )
        )

    return tuple(results)


def reconstruct_file(
    path: Path,
    **kwargs: object,
) -> BatchReconstruction:
    return reconstruct_trajectories(
        load_trajectory_file(path),
        **kwargs,
    )
