from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import json
from typing import BinaryIO, Iterable, Sequence
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
from app.core.regime_aggregation import build_regime_families


DEFAULT_TIMELINE_POINTS = 240
CLEARANCE_CANDIDATE_MAX_SECONDS = 4.0
RESOLVED_MODEL_MIN_CYCLE_CONFIDENCE = 0.75
RESOLVED_MODEL_MIN_PHASE_CONFIDENCE = 0.75


@dataclass(frozen=True)
class ArchiveAnalysis:
    filename: str
    source_format: str
    json_member_count: int
    trajectory_count: int
    event_count: int
    sessions: tuple[SessionReconstruction, ...]
    segment_events: tuple[
        tuple[TrajectoryEvent, ...], ...
    ] = ()
    member_errors: tuple[dict[str, str], ...] = ()

    def to_dict(self, *, timeline_points: int = DEFAULT_TIMELINE_POINTS) -> dict[str, object]:
        session_payloads = [
            _session_payload(index, session, timeline_points=timeline_points)
            for index, session in enumerate(self.sessions, start=1)
        ]
        regime_families = build_regime_families(
            self.sessions,
            segment_events=self.segment_events,
        )
        family_payloads = [
            family.to_dict()
            for family in regime_families
        ]
        for family, family_payload in zip(
            regime_families,
            family_payloads,
        ):
            for member in family.members:
                index = member.analysis_segment_id - 1
                if not 0 <= index < len(session_payloads):
                    continue
                session_payloads[index].update(
                    {
                        "regime_family_id": family.family_id,
                        "regime_family_member_count": (
                            family.member_count
                        ),
                        "regime_family_quality": (
                            family.model_quality
                        ),
                        "regime_family_consensus_coverage": (
                            family.consensus_coverage
                        ),
                        "regime_family_pooled_coverage": (
                            family.pooled_coverage
                        ),
                        "regime_family_pooled_quality": (
                            family.pooled_model_quality
                        ),
                        "regime_family_pooling_status": (
                            family.pooling_status
                        ),
                    }
                )
                local_determination = dict(
                    session_payloads[index]["determination"]
                )
                pooled_determination = _determination_payload(
                    family_payload.get("pooled_phase_model"),
                    model_quality=family.pooled_model_quality,
                    confidence=family.pooled_confidence,
                    source=f"pooled_regime_family:{family.family_id}",
                    reasons=(
                        ()
                        if family.pooling_status == "ok"
                        else (family.pooling_status,)
                    ),
                )
                local_coverage = float(
                    local_determination.get(
                        "determined_fraction",
                        0.0,
                    )
                )
                pooled_coverage = float(
                    pooled_determination.get(
                        "determined_fraction",
                        0.0,
                    )
                )
                if (
                    pooled_determination["usable"]
                    and (
                        not local_determination["usable"]
                        or pooled_coverage > local_coverage
                    )
                ):
                    session_payloads[index]["determination"] = (
                        pooled_determination
                    )
                    session_payloads[index]["effective_phase_model"] = (
                        family_payload.get("pooled_phase_model")
                    )
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
            "regime_family_count": len(family_payloads),
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
            "regime_families": family_payloads,
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
        "movement_stage_decisions": [
            decision.to_dict()
            for decision in model.movement_stage_decisions
        ],
        "boundary_recoveries": [
            recovery.to_dict()
            for recovery in model.boundary_recoveries
        ],
        "boundary_recovered_fraction": (
            model.boundary_recovered_fraction
        ),
        "boundary_suggested_fraction": (
            model.boundary_suggested_fraction
        ),
        "boundary_recovery_applied": (
            model.boundary_recovery_applied
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


def _phase_axis(
    active_approaches: Iterable[str],
) -> str | None:
    values = set(active_approaches)
    if values and values <= {"N", "S"}:
        return "NS"
    if values and values <= {"E", "W"}:
        return "EW"
    return None


def _circular_distance(
    left: float,
    right: float,
    cycle_seconds: float,
) -> float:
    direct = abs(left - right)
    return min(direct, cycle_seconds - direct)


def _split_cycle_interval(
    start: float,
    end: float,
    cycle_seconds: float,
) -> list[tuple[float, float]]:
    start %= cycle_seconds
    end %= cycle_seconds
    if abs(start - end) <= 1e-9:
        return [(0.0, cycle_seconds)]
    if start < end:
        return [(start, end)]
    return [(start, cycle_seconds), (0.0, end)]


def _interval_overlap_seconds(
    left_start: float,
    left_end: float,
    right_start: float,
    right_end: float,
    cycle_seconds: float,
) -> float:
    overlap = 0.0
    for a_start, a_end in _split_cycle_interval(
        left_start,
        left_end,
        cycle_seconds,
    ):
        for b_start, b_end in _split_cycle_interval(
            right_start,
            right_end,
            cycle_seconds,
        ):
            overlap += max(
                0.0,
                min(a_end, b_end) - max(a_start, b_start),
            )
    return overlap


def _gap_movement_probe(
    session: SessionReconstruction,
    gap: dict[str, float],
) -> list[dict[str, object]]:
    model = session.phase_model
    if model is None:
        return []
    cycle = float(model.cycle_seconds)
    gap_duration = max(0.0, float(gap["duration_s"]))
    minimum_overlap = min(
        2.0,
        max(0.5, gap_duration * 0.25),
    )
    probes: list[dict[str, object]] = []

    for candidate in model.distinct_movement_candidates:
        overlap = _interval_overlap_seconds(
            float(candidate.phase_start),
            float(candidate.phase_end),
            float(gap["start_s"]),
            float(gap["end_s"]),
            cycle,
        )
        if overlap < minimum_overlap:
            continue
        probes.append(
            {
                "source": "movement_candidate",
                "approach": candidate.approach,
                "movement": candidate.movement,
                "phase_start": candidate.phase_start,
                "phase_end": candidate.phase_end,
                "overlap_s": round(overlap, 3),
                "gap_overlap_fraction": round(
                    overlap / max(gap_duration, 1e-9),
                    4,
                ),
                "repeatability": candidate.repeatability,
                "stability": candidate.stability,
                "confidence": candidate.score,
            }
        )

    for stage in model.movement_stages:
        overlap = _interval_overlap_seconds(
            float(stage.phase_start),
            float(stage.phase_end),
            float(gap["start_s"]),
            float(gap["end_s"]),
            cycle,
        )
        if overlap < minimum_overlap:
            continue
        probes.append(
            {
                "source": "promoted_movement_stage",
                "approach": stage.approach,
                "movement": stage.movement,
                "phase_start": stage.phase_start,
                "phase_end": stage.phase_end,
                "overlap_s": round(overlap, 3),
                "gap_overlap_fraction": round(
                    overlap / max(gap_duration, 1e-9),
                    4,
                ),
                "repeatability": stage.repeatability,
                "stability": stage.stability,
                "confidence": stage.confidence,
            }
        )

    probes.sort(
        key=lambda item: (
            item["source"] == "promoted_movement_stage",
            float(item["confidence"]),
            float(item["overlap_s"]),
        ),
        reverse=True,
    )
    return probes


def _adjacent_gap_axes(
    session: SessionReconstruction,
    gap: dict[str, float],
) -> tuple[str | None, str | None]:
    model = session.phase_model
    if model is None:
        return None, None
    cycle = float(model.cycle_seconds)
    tolerance = max(
        0.001,
        float(model.bin_seconds) * 0.75,
    )
    previous = None
    following = None
    previous_distance = float("inf")
    following_distance = float("inf")
    for phase in model.phases:
        end_distance = _circular_distance(
            float(phase.phase_end) % cycle,
            float(gap["start_s"]) % cycle,
            cycle,
        )
        if end_distance < previous_distance:
            previous_distance = end_distance
            previous = phase
        start_distance = _circular_distance(
            float(phase.phase_start) % cycle,
            float(gap["end_s"]) % cycle,
            cycle,
        )
        if start_distance < following_distance:
            following_distance = start_distance
            following = phase

    previous_axis = (
        _phase_axis(previous.active_approaches)
        if previous is not None
        and previous_distance <= tolerance
        else None
    )
    following_axis = (
        _phase_axis(following.active_approaches)
        if following is not None
        and following_distance <= tolerance
        else None
    )
    return previous_axis, following_axis


def _mean_phase_confidence(
    session: SessionReconstruction,
) -> float:
    model = session.phase_model
    if model is None or not model.phases:
        return 0.0
    return sum(
        float(phase.confidence)
        for phase in model.phases
    ) / len(model.phases)


def _gap_semantics(
    session: SessionReconstruction,
) -> dict[str, object]:
    model = session.phase_model
    if model is None or session.cycle is None:
        return {
            "gaps": [],
            "clearance_candidate_rate": 0.0,
            "transition_ambiguous_rate": 0.0,
            "unresolved_stage_rate": 0.0,
            "unobserved_rate": 0.0,
            "unresolved_unknown_rate": 1.0,
            "unable_to_determine_rate": 1.0,
        }

    cycle = float(model.cycle_seconds)
    cycle_confidence = float(
        session.cycle.estimate.confidence
    )
    phase_confidence = _mean_phase_confidence(session)
    gaps = _phase_coverage_gaps(model)
    classified: list[dict[str, object]] = []
    duration_by_kind = {
        "CLEARANCE_CANDIDATE": 0.0,
        "TRANSITION_AMBIGUOUS": 0.0,
        "UNRESOLVED_STAGE": 0.0,
        "UNOBSERVED": 0.0,
    }

    for gap in gaps:
        duration = float(gap["duration_s"])
        previous_axis, following_axis = (
            _adjacent_gap_axes(session, gap)
        )
        movement_evidence = _gap_movement_probe(
            session,
            gap,
        )
        promoted = any(
            item["source"] == "promoted_movement_stage"
            for item in movement_evidence
        )
        conflicting_boundary = (
            previous_axis is not None
            and following_axis is not None
            and previous_axis != following_axis
        )

        if promoted:
            kind = "UNRESOLVED_STAGE"
            reason = "promoted movement stage overlaps uncovered interval"
        elif (
            duration <= CLEARANCE_CANDIDATE_MAX_SECONDS
            and conflicting_boundary
            and movement_evidence
        ):
            kind = "TRANSITION_AMBIGUOUS"
            reason = (
                "short conflict-family transition also contains recurring "
                "movement evidence"
            )
        elif (
            duration <= CLEARANCE_CANDIDATE_MAX_SECONDS
            and conflicting_boundary
        ):
            kind = "CLEARANCE_CANDIDATE"
            reason = (
                "short recurring gap between conflicting signal families"
            )
        elif movement_evidence:
            kind = "UNRESOLVED_STAGE"
            reason = "recurring movement evidence exists inside the gap"
        elif (
            cycle_confidence
            >= RESOLVED_MODEL_MIN_CYCLE_CONFIDENCE
            and phase_confidence
            >= RESOLVED_MODEL_MIN_PHASE_CONFIDENCE
        ):
            kind = "UNRESOLVED_STAGE"
            reason = (
                "high-confidence cycle and phases leave a persistent gap"
            )
        else:
            kind = "UNOBSERVED"
            reason = (
                "insufficient cycle/phase confidence to resolve the gap"
            )

        duration_by_kind[kind] += duration
        classified.append(
            {
                **gap,
                "kind": kind,
                "reason": reason,
                "previous_axis": previous_axis,
                "following_axis": following_axis,
                "cycle_confidence": round(
                    cycle_confidence,
                    4,
                ),
                "phase_confidence": round(
                    phase_confidence,
                    4,
                ),
                "movement_evidence": movement_evidence,
            }
        )

    rates = {
        kind: duration / cycle
        for kind, duration in duration_by_kind.items()
    }
    # Every uncovered interval is outside the supported phase model.
    # Diagnostic labels may explain the gap, but they must not turn absence of
    # direct evidence into a determined phase.
    unresolved = sum(rates.values())
    return {
        "gaps": classified,
        "clearance_candidate_rate": round(
            rates["CLEARANCE_CANDIDATE"],
            4,
        ),
        "transition_ambiguous_rate": round(
            rates["TRANSITION_AMBIGUOUS"],
            4,
        ),
        "unresolved_stage_rate": round(
            rates["UNRESOLVED_STAGE"],
            4,
        ),
        "unobserved_rate": round(
            rates["UNOBSERVED"],
            4,
        ),
        "unresolved_unknown_rate": round(
            unresolved,
            4,
        ),
        "unable_to_determine_rate": round(
            unresolved,
            4,
        ),
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
    """Report observability, not a target to eliminate UNKNOWN.

    UNKNOWN is the expected answer whenever the phase cannot be supported by
    the available indirect traffic evidence. No arbitrary '<1%' target is
    applied.
    """
    approaches = ("N", "S", "E", "W")
    if not timeline:
        return {
            "sample_count": 0,
            "overall_rate": None,
            "unable_to_determine_rate": None,
            "determined_rate": None,
            "per_approach_rate": {
                approach: None for approach in approaches
            },
            "longest_unknown_s": {
                approach: None for approach in approaches
            },
            "reason_rate": {},
            "reason_seconds": {},
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
    unable_rate = (
        round(overall_unknown / overall_denominator, 4)
        if overall_denominator > 0
        else None
    )
    determined_rate = (
        round(1.0 - unable_rate, 4)
        if unable_rate is not None
        else None
    )
    return {
        # overall_rate is retained for API compatibility; semantically it is
        # identical to unable_to_determine_rate.
        "overall_rate": unable_rate,
        "unable_to_determine_rate": unable_rate,
        "determined_rate": determined_rate,
        "sample_count": len(timeline),
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


def _determination_payload(
    phase_model: dict[str, object] | None,
    *,
    model_quality: str | None,
    confidence: float | None,
    source: str,
    reasons: Sequence[str] = (),
) -> dict[str, object]:
    coverage = (
        float(phase_model.get("cycle_coverage", 0.0))
        if phase_model is not None
        else 0.0
    )
    coverage = max(0.0, min(1.0, coverage))
    quality = str(model_quality or "INSUFFICIENT")
    usable = (
        phase_model is not None
        and quality in {"GOOD", "PARTIAL"}
        and bool(phase_model.get("phases"))
    )
    if not usable:
        status = "UNABLE_TO_DETERMINE"
    elif quality == "GOOD":
        status = "AVAILABLE"
    else:
        status = "PARTIAL"
    return {
        "status": status,
        "usable": usable,
        "source": source,
        "model_quality": quality,
        "confidence": (
            round(float(confidence), 4)
            if confidence is not None
            else None
        ),
        "determined_fraction": round(
            coverage if usable else 0.0,
            4,
        ),
        "unable_to_determine_fraction": round(
            1.0 - coverage if usable else 1.0,
            4,
        ),
        "reasons": list(reasons),
    }


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
    gap_semantics = _gap_semantics(session)
    phase_model = _compact_phase_model(session)
    determination = _determination_payload(
        phase_model,
        model_quality=session.model_quality,
        confidence=session.confidence,
        source="local_segment",
        reasons=session.quality_reasons,
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
        "phase_model": phase_model,
        "effective_phase_model": (
            phase_model if determination["usable"] else None
        ),
        "determination": determination,
        "timeline": timeline,
        "unknown_metrics": _timeline_unknown_metrics(timeline),
        "uncovered_cycle_intervals": _phase_coverage_gaps(
            session.phase_model
        ),
        "gap_semantics": gap_semantics["gaps"],
        "gap_metrics": {
            key: value
            for key, value in gap_semantics.items()
            if key != "gaps"
        },
        "regime_family_id": None,
        "regime_family_member_count": 0,
        "regime_family_quality": None,
        "regime_family_consensus_coverage": None,
        "regime_family_pooled_coverage": None,
        "regime_family_pooled_quality": None,
        "regime_family_pooling_status": None,
    }


def _partition_segment_events(
    events: Sequence[TrajectoryEvent],
    sessions: Sequence[SessionReconstruction],
) -> tuple[tuple[TrajectoryEvent, ...], ...]:
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
    if not sessions:
        return ()
    if not ordered:
        return tuple(() for _ in sessions)

    timestamps = [event.timestamp_ms for event in ordered]
    result: list[tuple[TrajectoryEvent, ...]] = []
    for session in sessions:
        left = bisect_left(
            timestamps,
            int(session.start_timestamp_ms),
        )
        right = bisect_right(
            timestamps,
            int(session.end_timestamp_ms),
        )
        result.append(tuple(ordered[left:right]))
    return tuple(result)


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
    all_events = tuple(
        extract_events_from_trajectories(trajectories)
    )
    segment_events = _partition_segment_events(
        all_events,
        sessions,
    )
    return ArchiveAnalysis(
        filename=filename,
        source_format="json",
        json_member_count=1,
        trajectory_count=len(trajectories),
        event_count=len(all_events),
        sessions=sessions,
        segment_events=segment_events,
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
    completed_segment_events: list[
        tuple[TrajectoryEvent, ...]
    ] = []
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
        regimes = reconstruct_event_regimes(
            current_events,
            start_timestamp_ms=current_start_ms,
            end_timestamp_ms=current_end_ms,
            trajectory_count=current_trajectory_count,
            trajectory_end_timestamps_ms=current_trajectory_end_times,
            session_index=physical_session_index,
            sampling_seconds=2.0,
            bin_seconds=2.0,
        )
        completed.extend(regimes)
        completed_segment_events.extend(
            _partition_segment_events(
                current_events,
                regimes,
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
        segment_events=tuple(completed_segment_events),
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
