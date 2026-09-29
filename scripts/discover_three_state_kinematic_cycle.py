from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.core.models import EventType, TrajectoryEvent
from app.core.preprocessing import load_trajectory_file
from app.core.reconstruction import extract_events_from_trajectories


STATE_NAMES = ("EW", "N_ARROW", "NS")

# Validated signal-state structure for this intersection:
#
#   EW:
#       E->W, W->E
#
#   N_ARROW:
#       E->N, N->E, and N->S may continue
#
#   NS:
#       S->N, N->S
#
# N->S is deliberately active in both N_ARROW and NS.
MOVEMENT_ACTIVE_STATES = {
    "E->_W": frozenset({"EW"}),
    "W->_E": frozenset({"EW"}),
    "W->_S": frozenset({"EW"}),
    "E->_N": frozenset({"N_ARROW"}),
    "N->_E": frozenset({"N_ARROW"}),
    "N->_S": frozenset({"N_ARROW", "NS"}),
    "S->_N": frozenset({"NS"}),
    "S->_E": frozenset({"NS"}),
}


@dataclass(frozen=True)
class Evidence:
    movement: str
    activity: np.ndarray
    stops: np.ndarray
    total_weight: float
    event_count: int


@dataclass(frozen=True)
class Fit:
    period_s: int
    origin_offset_s: int
    boundary_1_s: int
    boundary_2_s: int
    score: float
    movement_scores: dict[str, float]


def _event_weights(event: TrajectoryEvent) -> tuple[float, float]:
    confidence = max(0.0, min(1.0, float(event.confidence)))
    if event.event_type is EventType.RELEASE:
        return 1.0 * confidence, 0.0
    if event.event_type is EventType.CROSSING:
        return 0.8 * confidence, 0.0
    if event.event_type is EventType.STOP:
        return 0.0, 0.25 * confidence
    return 0.0, 0.0


def _phase_arrays(
    events: list[TrajectoryEvent],
    *,
    period_s: int,
    origin_ms: int,
) -> list[Evidence]:
    grouped: dict[str, list[TrajectoryEvent]] = defaultdict(list)
    for event in events:
        if event.movement in MOVEMENT_ACTIVE_STATES:
            grouped[event.movement].append(event)

    result: list[Evidence] = []
    for movement, movement_events in sorted(grouped.items()):
        if len(movement_events) < 4:
            continue

        activity = np.zeros(period_s, dtype=float)
        stops = np.zeros(period_s, dtype=float)
        total_weight = 0.0
        event_count = 0

        for event in movement_events:
            activity_weight, stop_weight = _event_weights(event)
            weight = activity_weight + stop_weight
            if weight <= 0.0:
                continue

            phase = int(
                math.floor(
                    ((event.timestamp_ms - origin_ms) / 1000.0) % period_s
                )
            ) % period_s
            activity[phase] += activity_weight
            stops[phase] += stop_weight
            total_weight += weight
            event_count += 1

        if total_weight <= 0.0 or event_count < 4:
            continue

        result.append(
            Evidence(
                movement=movement,
                activity=activity,
                stops=stops,
                total_weight=total_weight,
                event_count=event_count,
            )
        )

    return result


def _prefix(values: np.ndarray) -> np.ndarray:
    return np.concatenate(([0.0], np.cumsum(values)))


def _interval(prefix: np.ndarray, start_s: int, end_s: int) -> float:
    return float(prefix[end_s] - prefix[start_s])


def _state_for_phase(
    phase_s: int,
    *,
    period_s: int,
    boundary_1_s: int,
    boundary_2_s: int,
) -> int:
    if phase_s < boundary_1_s:
        return 0
    if phase_s < boundary_2_s:
        return 1
    return 2


def _active_intervals(
    movement: str,
    *,
    period_s: int,
    boundary_1_s: int,
    boundary_2_s: int,
) -> tuple[tuple[int, int], ...]:
    states = MOVEMENT_ACTIVE_STATES[movement]

    intervals: list[tuple[int, int]] = []
    for state_index, state_name in enumerate(STATE_NAMES):
        if state_name not in states:
            continue

        if state_index == 0:
            intervals.append((0, boundary_1_s))
        elif state_index == 1:
            intervals.append((boundary_1_s, boundary_2_s))
        else:
            intervals.append((boundary_2_s, period_s))

    return tuple(intervals)


def _sum_intervals(
    prefix: np.ndarray,
    intervals: tuple[tuple[int, int], ...],
) -> float:
    return sum(
        _interval(prefix, start_s, end_s)
        for start_s, end_s in intervals
        if end_s > start_s
    )


def _movement_fit_score(
    item: Evidence,
    *,
    period_s: int,
    boundary_1_s: int,
    boundary_2_s: int,
) -> float:
    activity_prefix = _prefix(item.activity)
    stop_prefix = _prefix(item.stops)

    active_intervals = _active_intervals(
        item.movement,
        period_s=period_s,
        boundary_1_s=boundary_1_s,
        boundary_2_s=boundary_2_s,
    )

    active_activity = _sum_intervals(activity_prefix, active_intervals)
    active_stops = _sum_intervals(stop_prefix, active_intervals)

    total_activity = float(np.sum(item.activity))
    total_stops = float(np.sum(item.stops))

    inactive_activity = total_activity - active_activity
    inactive_stops = total_stops - active_stops

    correct = active_activity + inactive_stops
    incorrect = inactive_activity + active_stops

    return float(
        np.clip(
            (correct - incorrect) / max(item.total_weight, 1e-9),
            -1.0,
            1.0,
        )
    )


def _boundary_limits(period_s: int) -> tuple[int, int, int, int]:
    min_ew = max(15, int(round(period_s * 0.15)))
    min_arrow = max(10, int(round(period_s * 0.10)))
    min_ns = max(15, int(round(period_s * 0.15)))
    max_arrow = max(min_arrow, int(round(period_s * 0.40)))
    return min_ew, min_arrow, min_ns, max_arrow


def _fit_period(
    evidence: list[Evidence],
    *,
    period_s: int,
) -> Fit | None:
    if not evidence:
        return None

    min_ew, min_arrow, min_ns, max_arrow = _boundary_limits(period_s)
    total_weight = sum(min(12.0, math.sqrt(item.event_count)) for item in evidence)

    best: Fit | None = None
    for boundary_1_s in range(
        min_ew,
        period_s - min_arrow - min_ns + 1,
    ):
        boundary_2_max = min(
            period_s - min_ns,
            boundary_1_s + max_arrow,
        )
        for boundary_2_s in range(
            boundary_1_s + min_arrow,
            boundary_2_max + 1,
        ):
            movement_scores = {
                item.movement: _movement_fit_score(
                    item,
                    period_s=period_s,
                    boundary_1_s=boundary_1_s,
                    boundary_2_s=boundary_2_s,
                )
                for item in evidence
            }

            score = sum(
                movement_scores[item.movement] * min(12.0, math.sqrt(item.event_count))
                for item in evidence
            ) / max(total_weight, 1e-9)

            fit = Fit(
                period_s=period_s,
                origin_offset_s=0,
                boundary_1_s=boundary_1_s,
                boundary_2_s=boundary_2_s,
                score=float(score),
                movement_scores=movement_scores,
            )
            if best is None or fit.score > best.score:
                best = fit

    return best


def discover_three_state_cycle(
    events: list[TrajectoryEvent],
    *,
    min_cycle_s: int = 70,
    max_cycle_s: int = 120,
) -> dict[str, object]:
    usable = [
        event
        for event in events
        if event.movement in MOVEMENT_ACTIVE_STATES
        and event.confidence > 0.0
        and event.event_type in {
            EventType.STOP,
            EventType.RELEASE,
            EventType.CROSSING,
        }
    ]
    if not usable:
        raise ValueError("no usable canonical movement events")

    anchor_ms = min(event.timestamp_ms for event in usable)

    candidates: list[dict[str, object]] = []
    selected_fits: dict[tuple[int, int], Fit] = {}

    for period_s in range(min_cycle_s, max_cycle_s + 1):
        # Phase zero is unknown. Search one complete phase rotation rather
        # than assuming that the first EW kinematic event is the cycle start.
        for origin_offset_s in range(period_s):
            origin_ms = anchor_ms + origin_offset_s * 1000
            evidence = _phase_arrays(
                usable,
                period_s=period_s,
                origin_ms=origin_ms,
            )
            fit = _fit_period(evidence, period_s=period_s)
            if fit is None:
                continue

            selected = Fit(
                period_s=fit.period_s,
                origin_offset_s=origin_offset_s,
                boundary_1_s=fit.boundary_1_s,
                boundary_2_s=fit.boundary_2_s,
                score=fit.score,
                movement_scores=fit.movement_scores,
            )
            selected_fits[(period_s, origin_offset_s)] = selected
            candidates.append({
                "cycle_seconds": period_s,
                "origin_offset_s": origin_offset_s,
                "score": round(selected.score, 4),
                "EW_duration_s": selected.boundary_1_s,
                "N_ARROW_duration_s": (
                    selected.boundary_2_s - selected.boundary_1_s
                ),
                "NS_duration_s": (
                    selected.period_s - selected.boundary_2_s
                ),
            })

    if not candidates:
        raise ValueError("no three-state cycle candidates")

    candidates.sort(
        key=lambda item: (
            -float(item["score"]),
            int(item["cycle_seconds"]),
            abs(int(item["origin_offset_s"])),
        )
    )

    selected = candidates[0]
    selected_fit = selected_fits[
        (
            int(selected["cycle_seconds"]),
            int(selected["origin_offset_s"]),
        )
    ]

    return {
        "schema_version": 2,
        "meaning": (
            "Research prototype for joint three-state cycle identification "
            "from kinematic events using a validated movement-state structure. "
            "It is not controller telemetry and does not classify traffic-light "
            "colors."
        ),
        "state_structure": {
            "stage_1": "EW",
            "stage_2": "N_ARROW",
            "stage_3": "NS",
            "movement_active_states": {
                movement: sorted(states)
                for movement, states in MOVEMENT_ACTIVE_STATES.items()
            },
        },
        "objective": (
            "Score every STOP/RELEASE/CROSSING event against the expected "
            "active/inactive state of its movement. Activity outside the "
            "movement's allowed states and STOP inside them are penalties."
        ),
        "selected_cycle_seconds": selected_fit.period_s,
        "origin_anchor_timestamp_ms": anchor_ms,
        "origin_offset_s": selected_fit.origin_offset_s,
        "selected_model": {
            "EW_duration_s": selected_fit.boundary_1_s,
            "N_ARROW_duration_s": (
                selected_fit.boundary_2_s - selected_fit.boundary_1_s
            ),
            "NS_duration_s": (
                selected_fit.period_s - selected_fit.boundary_2_s
            ),
            "score": round(selected_fit.score, 4),
            "movement_scores": {
                movement: round(score, 4)
                for movement, score in selected_fit.movement_scores.items()
            },
        },
        "candidate_cycles": candidates[:20],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Infer EW -> N+arrow -> NS using full movement-event agreement "
            "rather than scoring only events inside active windows."
        )
    )
    parser.add_argument("path", type=Path, help="Trajectory JSON")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("three_state_kinematic_cycle.json"),
    )
    parser.add_argument("--min-cycle", type=int, default=70)
    parser.add_argument("--max-cycle", type=int, default=120)
    args = parser.parse_args()

    if args.min_cycle <= 0 or args.max_cycle <= args.min_cycle:
        parser.error("--min-cycle/--max-cycle must define a positive range")

    trajectories = load_trajectory_file(args.path)
    if not trajectories:
        parser.error("source contains no usable trajectories")

    events = extract_events_from_trajectories(trajectories)
    result = discover_three_state_cycle(
        events,
        min_cycle_s=args.min_cycle,
        max_cycle_s=args.max_cycle,
    )

    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    model = result["selected_model"]
    print(
        "Three-state kinematic prototype: "
        f"schema={result['schema_version']}, "
        f"selected={result['selected_cycle_seconds']}s, "
        f"EW={model['EW_duration_s']}s, "
        f"N+arrow={model['N_ARROW_duration_s']}s, "
        f"NS={model['NS_duration_s']}s"
    )
    print(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
