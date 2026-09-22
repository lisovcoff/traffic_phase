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
                "ZIP members are compacted and ordered by trajectory time before session reconstruction.",
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
        "cycle_coverage": model.cycle_coverage,
        # phases is retained for API compatibility; stages is the preferred
        # name now that N/S/E/W activation is inferred independently.
        "phases": stages,
        "stages": stages,
        "distinct_movement_candidates": [
            candidate.to_dict()
            for candidate in model.distinct_movement_candidates
        ],
        "movement_stages": [
            stage.to_dict()
            for stage in model.movement_stages
        ],
        "boundary_recoveries": [
            recovery.to_dict()
            for recovery in model.boundary_recoveries
        ],
        "boundary_recovered_fraction": (
            model.boundary_recovered_fraction
        ),
    }


def _phase_coverage_gaps(
    phase_model: object | None,
) -> list[dict[str, float]]:
    if phase_model is None:
        return []
    cycle = float(getattr(phase_model, "cycle_seconds", 0.0))
    if cycle <= 0:
        return []

    segments: list[tuple[float, float]] = []
    for phase in tuple(getattr(phase_model, "phases", ())):
        start = float(phase.phase_start) % cycle
        end = float(phase.phase_end) % cycle
        if abs(start - end) <= 1e-9:
            return []
        if start < end:
            segments.append((start, end))
        else:
            segments.append((start, cycle))
            segments.append((0.0, end))

    if not segments:
        return [
            {
                "start_s": 0.0,
                "end_s": round(cycle, 3),
                "duration_s": round(cycle, 3),
            }
        ]

    segments.sort()
    merged: list[list[float]] = []
    for start, end in segments:
        if not merged or start > merged[-1][1] + 1e-9:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)

    gaps: list[dict[str, float]] = []
    cursor = 0.0
    for start, end in merged:
        if start > cursor + 1e-9:
            gaps.append(
                {
                    "start_s": round(cursor, 3),
                    "end_s": round(start, 3),
                    "duration_s": round(start - cursor, 3),
                }
            )
        cursor = max(cursor, end)
    if cursor < cycle - 1e-9:
        gaps.append(
            {
                "start_s": round(cursor, 3),
                "end_s": round(cycle, 3),
                "duration_s": round(cycle - cursor, 3),
            }
        )
    return gaps


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


def _movement_stages_at(
    session: SessionReconstruction,
    cycle_position_s: float | None,
) -> list[dict[str, object]]:
    model = session.phase_model
    if model is None or cycle_position_s is None:
        return []
    value = cycle_position_s % model.cycle_seconds
    result: list[dict[str, object]] = []
    for stage in model.movement_stages:
        start = stage.phase_start % model.cycle_seconds
        end = stage.phase_end % model.cycle_seconds
        inside = (
            start <= value < end
            if start <= end
            else value >= start or value < end
        )
        if inside:
            result.append(stage.to_dict())
    return result


def _axis_state(
    states: dict[str, str],
    approaches: tuple[str, str],
) -> str:
    values = {states.get(approach, "UNKNOWN") for approach in approaches}
    return next(iter(values)) if len(values) == 1 else "MIXED"


def _timeline_unknown_metrics(
    timeline: list[dict[str, object]],
) -> dict[str, object]:
    approaches = ("N", "S", "E", "W")
    target_rate = 0.01
    if not timeline:
        return {
            "target_rate": target_rate,
            "sample_count": 0,
            "overall_rate": None,
            "per_approach_rate": {
                approach: None for approach in approaches
            },
            "longest_unknown_s": {
                approach: None for approach in approaches
            },
            "meets_target": None,
        }

    if len(timeline) == 1:
        weights = [1.0]
    else:
        weights = [
            max(
                0.0,
                (
                    int(timeline[index + 1]["timestamp_ms"])
                    - int(point["timestamp_ms"])
                )
                / 1000.0,
            )
            for index, point in enumerate(timeline[:-1])
        ]
        weights.append(0.0)
        if sum(weights) <= 0:
            weights = [1.0 for _ in timeline]

    total_weight = sum(weights)
    unknown_weight = {
        approach: 0.0 for approach in approaches
    }
    longest = {
        approach: 0.0 for approach in approaches
    }
    reason_weight: dict[str, float] = {}
    current_run = {
        approach: 0.0 for approach in approaches
    }

    for point, weight in zip(timeline, weights):
        states = dict(point.get("states", {}) or {})
        reason = point.get("unknown_reason")
        if reason:
            reason_weight[str(reason)] = (
                reason_weight.get(str(reason), 0.0) + weight
            )
        for approach in approaches:
            if states.get(approach, "UNKNOWN") == "UNKNOWN":
                unknown_weight[approach] += weight
                current_run[approach] += weight
                longest[approach] = max(
                    longest[approach],
                    current_run[approach],
                )
            else:
                current_run[approach] = 0.0

    per_approach = {
        approach: round(
            unknown_weight[approach] / total_weight,
            4,
        )
        if total_weight > 0
        else None
        for approach in approaches
    }
    overall_unknown = sum(unknown_weight.values())
    overall_denominator = total_weight * len(approaches)
    overall_rate = (
        round(overall_unknown / overall_denominator, 4)
        if overall_denominator > 0
        else None
    )
    return {
        "target_rate": target_rate,
        "sample_count": len(timeline),
        "overall_rate": overall_rate,
        "per_approach_rate": per_approach,
        "longest_unknown_s": {
            approach: round(value, 3)
            for approach, value in longest.items()
        },
        "reason_rate": {
            reason: round(weight / total_weight, 4)
            for reason, weight in reason_weight.items()
        } if total_weight > 0 else {},
        "reason_seconds": {
            reason: round(weight, 3)
            for reason, weight in reason_weight.items()
        },
        "meets_target": (
            overall_rate < target_rate
            if overall_rate is not None
            else None
        ),
    }


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
        has_unknown = any(
            state == "UNKNOWN"
            for state in states.values()
        )
        if not has_unknown:
            unknown_reason = None
        elif phase is None:
            unknown_reason = "uncovered_phase"
        elif signal.phase_confidence < estimator.min_phase_confidence:
            unknown_reason = "low_phase_confidence"
        else:
            unknown_reason = "estimator_unknown"
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
                "active_movements": _movement_stages_at(
                    session,
                    cycle_position_s,
                ),
                "confidence": signal.phase_confidence,
                "states": states,
                "unknown_reason": unknown_reason,
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
    timeline = build_session_timeline(
        session,
        max_points=timeline_points,
    )
    return {
        "session_id": index,
        "physical_session_index": session.session_index,
        "regime_index": session.regime_index,
        "regime_count": session.regime_count,
        "rolling_period_seconds": session.rolling_period_seconds,
        "rolling_window_count": session.rolling_window_count,
        "model_quality": session.model_quality,
        "quality_reasons": list(session.quality_reasons),
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
        "timeline": timeline,
        "unknown_metrics": _timeline_unknown_metrics(timeline),
        "uncovered_cycle_intervals": _phase_coverage_gaps(
            session.phase_model
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
    compact_blocks: list[
        tuple[
            int,
            int,
            int,
            tuple[int, ...],
            tuple[TrajectoryEvent, ...],
            str,
        ]
    ] = []

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
                block_events = tuple(
                    extract_events_from_trajectories(
                        trajectory_session
                    )
                )
                block_end_times = tuple(
                    _trajectory_interval_ms(item)[1]
                    for item in trajectory_session
                )
                total_events += len(block_events)
                compact_blocks.append(
                    (
                        block_start_ms,
                        block_end_ms,
                        len(trajectory_session),
                        block_end_times,
                        block_events,
                        member.filename,
                    )
                )

    for (
        block_start_ms,
        block_end_ms,
        block_trajectory_count,
        block_end_times,
        block_events,
        _member_name,
    ) in sorted(
        compact_blocks,
        key=lambda item: (
            item[0],
            item[1],
            item[5],
        ),
    ):
        if current_start_ms is None:
            current_start_ms = block_start_ms
            current_end_ms = block_end_ms
            current_trajectory_count = block_trajectory_count
            current_trajectory_end_times.extend(block_end_times)
            current_events.extend(block_events)
            continue

        assert current_end_ms is not None
        if block_start_ms - current_end_ms > gap_ms:
            flush_current()
            current_start_ms = block_start_ms
            current_end_ms = block_end_ms
            current_trajectory_count = block_trajectory_count
            current_trajectory_end_times.extend(block_end_times)
            current_events.extend(block_events)
            continue

        current_start_ms = min(current_start_ms, block_start_ms)
        current_end_ms = max(current_end_ms, block_end_ms)
        current_trajectory_count += block_trajectory_count
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
