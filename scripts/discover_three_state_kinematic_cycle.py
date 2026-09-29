from __future__ import annotations

import argparse
import json
import math
import statistics
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


# RELEASE is the closest available kinematic proxy for a green onset.
# CROSSING is supporting evidence but is delayed by queue discharge.
# STOP is excluded from the phase objective because a stop during green
# can be caused by spillback or non-signal effects.
SIGNAL_REACTION_DELAY_S = 2.0
GREEN_START_CLUSTER_GAP_S = 6.0


def _event_weights(event: TrajectoryEvent) -> tuple[float, float]:
    confidence = max(0.0, min(1.0, float(event.confidence)))
    if event.event_type is EventType.RELEASE:
        return 1.0 * confidence, 0.0
    if event.event_type is EventType.CROSSING:
        return 0.25 * confidence, 0.0
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

            adjusted_timestamp_ms = (
                event.timestamp_ms - int(SIGNAL_REACTION_DELAY_S * 1000)
            )
            phase = int(
                math.floor(
                    ((adjusted_timestamp_ms - origin_ms) / 1000.0) % period_s
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


def _circular_window_matrix(values: np.ndarray) -> np.ndarray:
    """Return sums for every window length and circular start position."""
    period_s = len(values)
    doubled = np.concatenate((values, values))
    prefix = np.concatenate(([0.0], np.cumsum(doubled)))
    windows = np.zeros((period_s + 1, period_s), dtype=float)

    for duration_s in range(1, period_s + 1):
        windows[duration_s] = (
            prefix[duration_s : duration_s + period_s] - prefix[:period_s]
        )
    return windows


def _fit_period(
    evidence: list[Evidence],
    *,
    period_s: int,
) -> Fit | None:
    if not evidence:
        return None

    min_ew, min_arrow, min_ns, max_arrow = _boundary_limits(period_s)
    movement_weights = np.array(
        [min(12.0, math.sqrt(item.event_count)) for item in evidence],
        dtype=float,
    )
    total_weight = float(np.sum(movement_weights))
    if total_weight <= 0.0:
        return None

    # The original implementation searched:
    #   period × origin × boundary_1 × boundary_2 × movement.
    # The phase origin is only a rotation of the same circular cycle.  Because
    # every movement score is additive over its active state intervals, we can
    # aggregate movement evidence by state first and evaluate every origin
    # vectorially.  This removes one full O(period) loop and most Python-level
    # work while preserving the same objective.
    state_activity = np.zeros((len(STATE_NAMES), period_s), dtype=float)
    state_stops = np.zeros((len(STATE_NAMES), period_s), dtype=float)

    for item, movement_weight in zip(evidence, movement_weights):
        coefficient = float(movement_weight) / max(item.total_weight, 1e-9)
        active_states = sorted(
            STATE_NAMES.index(state_name)
            for state_name in MOVEMENT_ACTIVE_STATES[item.movement]
        )
        # Every supported movement has a contiguous active-state span.  Using
        # the span prevents N->S, which is active in N_ARROW and NS, from
        # being counted twice at their shared boundary.
        first_state = active_states[0]
        last_state = active_states[-1]
        for state_index in range(first_state, last_state + 1):
            state_activity[state_index] += coefficient * item.activity
            state_stops[state_index] += coefficient * item.stops

    activity_windows = [
        _circular_window_matrix(state_activity[state_index])
        for state_index in range(len(STATE_NAMES))
    ]
    stop_windows = [
        _circular_window_matrix(state_stops[state_index])
        for state_index in range(len(STATE_NAMES))
    ]

    best: Fit | None = None
    phase_positions = np.arange(period_s)

    for boundary_1_s in range(
        min_ew,
        period_s - min_arrow - min_ns + 1,
    ):
        for boundary_2_s in range(
            boundary_1_s + min_arrow,
            min(period_s - min_ns, boundary_1_s + max_arrow) + 1,
        ):
            arrow_duration = boundary_2_s - boundary_1_s
            ns_duration = period_s - boundary_2_s

            # For every possible EW origin, the following three intervals are:
            #   EW      [origin, origin + boundary_1)
            #   N_ARROW [origin + boundary_1, origin + boundary_2)
            #   NS      [origin + boundary_2, origin + period)
            #
            # The precomputed circular-window matrices make each interval
            # lookup O(1).  np.take handles the modulo rotation without
            # allocating rolled arrays for every candidate.
            ew_sum = activity_windows[0][boundary_1_s, phase_positions]
            arrow_starts = (phase_positions + boundary_1_s) % period_s
            ns_starts = (phase_positions + boundary_2_s) % period_s
            arrow_sum = activity_windows[1][arrow_duration, arrow_starts]
            ns_sum = activity_windows[2][ns_duration, ns_starts]

            ew_stop = stop_windows[0][boundary_1_s, phase_positions]
            arrow_stop = stop_windows[1][arrow_duration, arrow_starts]
            ns_stop = stop_windows[2][ns_duration, ns_starts]

            active_activity = ew_sum + arrow_sum + ns_sum
            active_stops = ew_stop + arrow_stop + ns_stop
            total_stops = float(
                np.sum(state_stops)
            )
            variable_score = active_activity + total_stops - active_stops
            scores = 2.0 * variable_score / total_weight - 1.0
            best_index = int(np.argmax(scores))
            score = float(scores[best_index])

            if best is None or score > best.score:
                best = Fit(
                    period_s=period_s,
                    origin_offset_s=best_index,
                    boundary_1_s=boundary_1_s,
                    boundary_2_s=boundary_2_s,
                    score=score,
                    movement_scores={},
                )

    if best is None:
        return None

    # Recompute per-movement scores only for the winning structure.  This is
    # intentionally kept separate from the fast search path because these
    # values are diagnostic output, not part of the candidate ranking.
    movement_scores: dict[str, float] = {}
    for item in evidence:
        active_intervals: list[tuple[int, int]] = []
        for state_index, state_name in enumerate(STATE_NAMES):
            if state_name not in MOVEMENT_ACTIVE_STATES[item.movement]:
                continue

            if state_index == 0:
                duration = best.boundary_1_s
                start = best.origin_offset_s
            elif state_index == 1:
                duration = best.boundary_2_s - best.boundary_1_s
                start = best.origin_offset_s + best.boundary_1_s
            else:
                duration = best.period_s - best.boundary_2_s
                start = best.origin_offset_s + best.boundary_2_s

            start %= best.period_s
            end = start + duration
            if end <= best.period_s:
                active_intervals.append((start, end))
            else:
                active_intervals.append((start, best.period_s))
                active_intervals.append((0, end - best.period_s))

        activity_prefix = _prefix(item.activity)
        active_activity = _sum_intervals(
            activity_prefix,
            tuple(active_intervals),
        )
        stop_prefix = _prefix(item.stops)
        active_stops = _sum_intervals(
            stop_prefix,
            tuple(active_intervals),
        )
        total_activity = float(np.sum(item.activity))
        total_stops = float(np.sum(item.stops))
        movement_scores[item.movement] = float(
            np.clip(
                (
                    2.0 * (active_activity + total_stops - active_stops)
                    - (total_activity + total_stops)
                )
                / max(item.total_weight, 1e-9),
                -1.0,
                1.0,
            )
        )

    return Fit(
        period_s=best.period_s,
        origin_offset_s=best.origin_offset_s,
        boundary_1_s=best.boundary_1_s,
        boundary_2_s=best.boundary_2_s,
        score=best.score,
        movement_scores=movement_scores,
    )


def _release_start_times(events: list[TrajectoryEvent]) -> list[float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for event in events:
        if (
            event.movement in MOVEMENT_ACTIVE_STATES
            and event.event_type is EventType.RELEASE
            and event.confidence > 0.0
        ):
            grouped[event.movement].append(event.timestamp_ms / 1000.0)

    starts: list[float] = []
    for times in grouped.values():
        times.sort()
        previous: float | None = None
        for timestamp_s in times:
            if previous is None or timestamp_s - previous > GREEN_START_CLUSTER_GAP_S:
                starts.append(timestamp_s)
            previous = timestamp_s
    return sorted(starts)


def _periodicity_score(
    release_starts_s: list[float],
    *,
    period_s: int,
    tolerance_s: float = 3.0,
) -> float:
    if len(release_starts_s) < 2:
        return 0.0

    matched = 0
    errors: list[float] = []
    for index, left in enumerate(release_starts_s[:-1]):
        for right in release_starts_s[index + 1:]:
            delta = right - left
            if delta < period_s - tolerance_s:
                continue
            multiple = max(1, round(delta / period_s))
            error = abs(delta - multiple * period_s)
            if error <= tolerance_s:
                matched += 1
                errors.append(error)
            if delta > 3 * period_s + tolerance_s:
                break

    if matched == 0:
        return 0.0
    coverage = matched / max(1, len(release_starts_s) - 1)
    precision = 1.0 - statistics.mean(errors) / max(tolerance_s, 1e-9)
    return float(min(1.0, coverage) * max(0.0, precision))



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
    release_starts_s = _release_start_times(usable)

    candidates: list[dict[str, object]] = []
    selected_fits: dict[tuple[int, int], Fit] = {}

    for period_s in range(min_cycle_s, max_cycle_s + 1):
        # Anchor the phase arrays once.  _fit_period treats the origin as a
        # circular rotation, so rebuilding the event arrays for every origin
        # is unnecessary.
        evidence = _phase_arrays(
            usable,
            period_s=period_s,
            origin_ms=anchor_ms,
        )
        selected = _fit_period(evidence, period_s=period_s)
        if selected is None:
            continue

        selected_fits[(period_s, selected.origin_offset_s)] = selected
        periodicity = _periodicity_score(
            release_starts_s,
            period_s=period_s,
        )
        joint_score = 0.65 * periodicity + 0.35 * selected.score
        candidates.append({
            "cycle_seconds": period_s,
            "origin_offset_s": selected.origin_offset_s,
            "score": round(joint_score, 4),
            "phase_fit_score": round(selected.score, 4),
            "release_periodicity_score": round(periodicity, 4),
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
        "schema_version": 3,
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
            "Score RELEASE events as primary green-onset evidence and "
            "CROSSING events as weaker supporting evidence against the "
            "expected active/inactive state of each movement. STOP events "
            "are excluded from the phase objective."
        ),
        "signal_reaction_delay_s": SIGNAL_REACTION_DELAY_S,
        "green_start_cluster_gap_s": GREEN_START_CLUSTER_GAP_S,
        "release_start_count": len(release_starts_s),
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
