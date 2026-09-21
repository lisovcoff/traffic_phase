from __future__ import annotations

from dataclasses import dataclass
import json
from typing import BinaryIO, Iterable
import zipfile

from app.core.models import Trajectory, TrajectoryEvent
from app.core.preprocessing import load_trajectory_payload
from app.core.reconstruction import (
    DEFAULT_SESSION_GAP_SECONDS,
    SessionReconstruction,
    extract_events_from_trajectories,
    reconstruct_event_regimes,
    reconstruct_trajectory_sessions,
    split_trajectories_into_sessions,
)
from app.core.signal_state_estimator import SignalStateEstimator


DEFAULT_TIMELINE_POINTS = 240


@dataclass(frozen=True)
class ArchiveAnalysis:
    filename: str
    source_format: str
    json_member_count: int
    trajectory_count: int
    event_count: int
    sessions: tuple[SessionReconstruction, ...]
    member_errors: tuple[dict[str, str], ...] = ()

    def to_dict(self, *, timeline_points: int = DEFAULT_TIMELINE_POINTS) -> dict[str, object]:
        session_payloads = [
            _session_payload(index, session, timeline_points=timeline_points)
            for index, session in enumerate(self.sessions, start=1)
        ]
        single_ok = (
            len(session_payloads) == 1
            and session_payloads[0]["status"] == "ok"
        )
        physical_session_count = max(
            (session.session_index for session in self.sessions),
            default=0,
        )
        source = {
            "filename": self.filename,
            "format": self.source_format,
            "json_members": self.json_member_count,
            "cars_used": self.trajectory_count,
            "events_used": self.event_count,
            "session_count": physical_session_count,
            "regime_count": len(session_payloads),
            "analysis_segment_count": len(session_payloads),
            "member_errors": list(self.member_errors),
        }
        if len(session_payloads) == 1:
            source.update(
                {
                    "start_timestamp_ms": session_payloads[0]["start_timestamp_ms"],
                    "duration_s": session_payloads[0]["duration_s"],
                }
            )

        return {
            "mode": "session_based_event_inference",
            "ground_truth": "UNAVAILABLE",
            "source": source,
            "sessions": session_payloads,
            # Backward compatibility for the original single-JSON endpoint.
            "cycle": session_payloads[0]["cycle"] if single_ok else None,
            "phase_model": (
                session_payloads[0]["phase_model"]
                if single_ok
                else None
            ),
            "limitations": [
                "Traffic-light state is inferred indirectly from vehicle trajectory events.",
                "No controller or signal-state ground truth is present in the trajectory data.",
                "ZIP members are processed sequentially and must be chronological by trajectory time.",
                "Timeline points are sampled from the inferred recurring phase model and are not controller telemetry.",
            ],
        }


def _trajectory_interval_ms(trajectory: Trajectory) -> tuple[int, int]:
    if trajectory.detections:
        timestamps = [item.millis for item in trajectory.detections]
        return min(timestamps), max(timestamps)
    timestamp = int(trajectory.timestamp_ms)
    return timestamp, timestamp


def _session_bounds(
    trajectories: Iterable[Trajectory],
) -> tuple[int, int]:
    intervals = [_trajectory_interval_ms(item) for item in trajectories]
    return (
        min(start for start, _ in intervals),
        max(end for _, end in intervals),
    )


def _compact_cycle(session: SessionReconstruction) -> dict[str, object] | None:
    if session.cycle is None:
        return None
    estimate = session.cycle.estimate
    return {
        "estimated_cycle": estimate.cycle_seconds,
        "confidence": estimate.confidence,
        "used_events": session.cycle.flow.used_events,
        "release_events": session.cycle.flow.release_events,
        "crossing_events": session.cycle.flow.crossing_events,
    }


def _compact_phase_model(session: SessionReconstruction) -> dict[str, object] | None:
    if session.phase_model is None:
        return None
    model = session.phase_model
    total = model.supporting_event_count + model.contradictory_event_count
    stages = [phase.to_dict() for phase in model.phases]
    return {
        "model_type": "recurring_signal_stages",
        "cycle_seconds": model.cycle_seconds,
        "bin_seconds": model.bin_seconds,
        "origin_timestamp_ms": model.origin_timestamp_ms,
        "confidence": session.confidence,
        "supporting_event_count": model.supporting_event_count,
        "contradictory_event_count": model.contradictory_event_count,
        "support_ratio": (
            round(model.supporting_event_count / total, 4)
            if total
            else None
        ),
        # phases is retained for API compatibility; stages is the preferred
        # name now that N/S/E/W activation is inferred independently.
        "phases": stages,
        "stages": stages,
        "distinct_movement_candidates": [
            candidate.to_dict()
            for candidate in model.distinct_movement_candidates
        ],
    }


def _phase_at(session: SessionReconstruction, timestamp_ms: int):
    model = session.phase_model
    if model is None:
        return None, None
    position = (
        (timestamp_ms - model.origin_timestamp_ms) / 1000.0
    ) % model.cycle_seconds
    for phase in model.phases:
        start = phase.phase_start % model.cycle_seconds
        end = phase.phase_end % model.cycle_seconds
        inside = (
            start <= position < end
            if start <= end
            else position >= start or position < end
        )
        if inside:
            return phase, round(position, 3)
    return None, round(position, 3)


def _axis_state(
    states: dict[str, str],
    approaches: tuple[str, str],
) -> str:
    values = {states.get(approach, "UNKNOWN") for approach in approaches}
    return next(iter(values)) if len(values) == 1 else "UNKNOWN"


def build_session_timeline(
    session: SessionReconstruction,
    *,
    max_points: int = DEFAULT_TIMELINE_POINTS,
) -> list[dict[str, object]]:
    if max_points <= 0:
        raise ValueError("max_points must be positive")
    if session.status != "ok" or session.phase_model is None:
        return []

    start_ms = max(
        session.start_timestamp_ms,
        int(session.phase_model.origin_timestamp_ms),
    )
    end_ms = max(start_ms, session.end_timestamp_ms)
    duration_ms = end_ms - start_ms
    point_count = min(
        max_points,
        max(1, int(duration_ms / 5000) + 1),
    )

    if point_count == 1:
        timestamps = [start_ms]
    else:
        timestamps = [
            start_ms + round(duration_ms * index / (point_count - 1))
            for index in range(point_count)
        ]

    estimator = SignalStateEstimator(
        session.phase_model,
        event_origin_ms=session.phase_model.origin_timestamp_ms,
    )
    timeline: list[dict[str, object]] = []
    for timestamp_ms in timestamps:
        phase, cycle_position_s = _phase_at(session, timestamp_ms)
        relative_time_s = max(
            0.0,
            (
                timestamp_ms
                - session.phase_model.origin_timestamp_ms
            )
            / 1000.0,
        )
        signal = estimator.estimate(relative_time_s, ())
        states = {
            item.approach: item.state.value
            for item in signal.approaches
        }
        timeline.append(
            {
                "timestamp_ms": int(timestamp_ms),
                "offset_s": round(
                    (timestamp_ms - session.start_timestamp_ms) / 1000.0,
                    3,
                ),
                "cycle_position_s": cycle_position_s,
                "phase_id": signal.phase_id,
                "transition": signal.transition,
                "active_approaches": (
                    list(phase.active_approaches)
                    if phase is not None
                    else []
                ),
                "confidence": signal.phase_confidence,
                "states": states,
                "axis_states": {
                    "NS": _axis_state(states, ("N", "S")),
                    "EW": _axis_state(states, ("E", "W")),
                },
            }
        )
    return timeline


def _session_payload(
    index: int,
    session: SessionReconstruction,
    *,
    timeline_points: int,
) -> dict[str, object]:
    return {
        "session_id": index,
        "physical_session_index": session.session_index,
        "regime_index": session.regime_index,
        "regime_count": session.regime_count,
        "rolling_period_seconds": session.rolling_period_seconds,
        "rolling_window_count": session.rolling_window_count,
        "start_timestamp_ms": session.start_timestamp_ms,
        "end_timestamp_ms": session.end_timestamp_ms,
        "duration_s": session.duration_s,
        "trajectory_count": session.trajectory_count,
        "event_count": session.event_count,
        "status": session.status,
        "confidence": session.confidence,
        "error_reason": session.error_reason,
        "cycle": _compact_cycle(session),
        "phase_model": _compact_phase_model(session),
        "timeline": build_session_timeline(
            session,
            max_points=timeline_points,
        ),
    }


def analyze_json_stream(
    stream: BinaryIO,
    *,
    filename: str,
    session_gap_seconds: float = DEFAULT_SESSION_GAP_SECONDS,
) -> ArchiveAnalysis:
    payload = json.load(stream)
    trajectories = load_trajectory_payload(payload)
    sessions = reconstruct_trajectory_sessions(
        trajectories,
        session_gap_seconds=session_gap_seconds,
    )
    return ArchiveAnalysis(
        filename=filename,
        source_format="json",
        json_member_count=1,
        trajectory_count=len(trajectories),
        event_count=sum(session.event_count for session in sessions),
        sessions=sessions,
    )


def analyze_zip_stream(
    stream: BinaryIO,
    *,
    filename: str,
    session_gap_seconds: float = DEFAULT_SESSION_GAP_SECONDS,
) -> ArchiveAnalysis:
    if session_gap_seconds <= 0:
        raise ValueError("session_gap_seconds must be positive")
    gap_ms = int(round(session_gap_seconds * 1000.0))

    completed: list[SessionReconstruction] = []
    current_events: list[TrajectoryEvent] = []
    current_start_ms: int | None = None
    current_end_ms: int | None = None
    current_trajectory_count = 0
    current_trajectory_end_times: list[int] = []
    physical_session_index = 0
    total_trajectories = 0
    total_events = 0
    member_errors: list[dict[str, str]] = []

    def flush_current() -> None:
        nonlocal current_events
        nonlocal current_start_ms
        nonlocal current_end_ms
        nonlocal current_trajectory_count
        nonlocal current_trajectory_end_times
        nonlocal physical_session_index

        if current_start_ms is None or current_end_ms is None:
            return
        physical_session_index += 1
        completed.extend(
            reconstruct_event_regimes(
                current_events,
                start_timestamp_ms=current_start_ms,
                end_timestamp_ms=current_end_ms,
                trajectory_count=current_trajectory_count,
                trajectory_end_timestamps_ms=current_trajectory_end_times,
                session_index=physical_session_index,
                sampling_seconds=2.0,
                bin_seconds=2.0,
            )
        )
        current_events = []
        current_start_ms = None
        current_end_ms = None
        current_trajectory_count = 0
        current_trajectory_end_times = []

    with zipfile.ZipFile(stream) as archive:
        members = [
            member
            for member in archive.infolist()
            if not member.is_dir()
            and member.filename.lower().endswith(".json")
        ]
        if not members:
            raise ValueError("ZIP archive contains no JSON trajectory files")

        for member in members:
            try:
                with archive.open(member) as handle:
                    payload = json.load(handle)
                trajectories = load_trajectory_payload(payload)
            except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                member_errors.append(
                    {
                        "member": member.filename,
                        "error": str(exc),
                    }
                )
                continue

            if not trajectories:
                member_errors.append(
                    {
                        "member": member.filename,
                        "error": "no usable car trajectories found",
                    }
                )
                continue

            total_trajectories += len(trajectories)
            member_sessions = split_trajectories_into_sessions(
                trajectories,
                session_gap_seconds=session_gap_seconds,
            )
            del payload
            del trajectories

            for trajectory_session in member_sessions:
                block_start_ms, block_end_ms = _session_bounds(
                    trajectory_session
                )
                block_events = extract_events_from_trajectories(
                    trajectory_session
                )
                block_end_times = [
                    _trajectory_interval_ms(item)[1]
                    for item in trajectory_session
                ]
                total_events += len(block_events)

                if current_start_ms is None:
                    current_start_ms = block_start_ms
                    current_end_ms = block_end_ms
                    current_trajectory_count = len(trajectory_session)
                    current_trajectory_end_times.extend(block_end_times)
                    current_events.extend(block_events)
                    continue

                assert current_end_ms is not None
                if block_end_ms < current_start_ms:
                    raise ValueError(
                        "ZIP JSON members are not chronological by trajectory time"
                    )

                if block_start_ms - current_end_ms > gap_ms:
                    flush_current()
                    current_start_ms = block_start_ms
                    current_end_ms = block_end_ms
                    current_trajectory_count = len(trajectory_session)
                    current_trajectory_end_times.extend(block_end_times)
                    current_events.extend(block_events)
                    continue

                current_start_ms = min(current_start_ms, block_start_ms)
                current_end_ms = max(current_end_ms, block_end_ms)
                current_trajectory_count += len(trajectory_session)
                current_trajectory_end_times.extend(block_end_times)
                current_events.extend(block_events)

    flush_current()
    if not completed:
        details = (
            "; ".join(
                f"{item['member']}: {item['error']}"
                for item in member_errors
            )
            or "no usable trajectories"
        )
        raise ValueError(f"ZIP archive could not be analyzed: {details}")

    return ArchiveAnalysis(
        filename=filename,
        source_format="zip",
        json_member_count=len(members),
        trajectory_count=total_trajectories,
        event_count=total_events,
        sessions=tuple(completed),
        member_errors=tuple(member_errors),
    )


def analyze_trajectory_stream(
    stream: BinaryIO,
    *,
    filename: str,
    session_gap_seconds: float = DEFAULT_SESSION_GAP_SECONDS,
) -> ArchiveAnalysis:
    lowered = filename.lower()
    if lowered.endswith(".json"):
        return analyze_json_stream(
            stream,
            filename=filename,
            session_gap_seconds=session_gap_seconds,
        )
    if lowered.endswith(".zip"):
        return analyze_zip_stream(
            stream,
            filename=filename,
            session_gap_seconds=session_gap_seconds,
        )
    raise ValueError("Only JSON and ZIP trajectory files are supported")
