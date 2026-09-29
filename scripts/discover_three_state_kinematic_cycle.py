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

# User-validated standard signal states for this intersection:
#   EW      : E->W and W->E
#   N_ARROW : E->N and N->E; N->S may also continue
#   NS      : N->S and S->N
#
# N->S is intentionally active in both N_ARROW and NS because the manual
# annotation says that movement is present in both states.
MOVEMENT_ACTIVE_STATES = {
    "E->_W": frozenset({"EW"}),
    "W->_E": frozenset({"EW"}),
    "E->_N": frozenset({"N_ARROW"}),
    "N->_E": frozenset({"N_ARROW"}),
    "N->_S": frozenset({"N_ARROW", "NS"}),
    "S->_N": frozenset({"NS"}),
}


@dataclass(frozen=True)
class Evidence:
    movement: str
    phase: np.ndarray
    weights: np.ndarray
    event_count: int


@dataclass(frozen=True)
class Fit:
    period_s: int
    origin_offset_s: int
    boundary_1_s: int
    boundary_2_s: int
    score: float
    coverage: float
    movement_scores: dict[str, float]


def _event_weight(event: TrajectoryEvent) -> float:
    confidence = max(0.0, min(1.0, float(event.confidence)))
    if event.event_type is EventType.RELEASE:
        return 1.0 * confidence
    if event.event_type is EventType.CROSSING:
        return 0.8 * confidence
    if event.event_type is EventType.STOP:
        return 1.0 * confidence
    return 0.0


def _expected_active(stage: int, movement: str) -> bool:
    states = MOVEMENT_ACTIVE_STATES.get(movement)
    if states is None:
        return False
    return STATE_NAMES[stage] in states


def _phase_arrays(
    events: list[TrajectoryEvent],
    *,
    period_s: int,
    origin_ms: int,
) -> tuple[list[Evidence], int]:
    grouped: dict[str, list[TrajectoryEvent]] = defaultdict(list)
    for event in events:
        if event.movement in MOVEMENT_ACTIVE_STATES:
            grouped[event.movement].append(event)

    result: list[Evidence] = []
    for movement, movement_events in sorted(grouped.items()):
        if len(movement_events) < 4:
            continue

        # Store signed evidence for each possible stage:
        # positive when event timing agrees with that stage's active/inactive
        # expectation, negative otherwise.
        stage_phase = np.zeros((3, period_s), dtype=float)
        total_weight = 0.0

        for event in movement_events:
            weight = _event_weight(event)
            if weight <= 0.0:
                continue
            phase = int(
                math.floor(
                    ((event.timestamp_ms - origin_ms) / 1000.0) % period_s
                )
            ) % period_s
            total_weight += weight

            for stage in range(3):
                active = _expected_active(stage, movement)
                agrees = (
                    event.event_type is EventType.STOP
                    and not active
                ) or (
                    event.event_type in {
                        EventType.RELEASE,
                        EventType.CROSSING,
                    }
                    and active
                )
                stage_phase[stage, phase] += (
                    weight if agrees else -weight
                )

        if total_weight <= 0.0:
            continue

        # Keep the three stage channels separate until boundaries are scored.
        result.append(
            Evidence(
                movement=movement,
                phase=stage_phase,
                weights=np.array([total_weight], dtype=float),
                event_count=len(movement_events),
            )
        )

    return result, sum(item.event_count for item in result)


def _prefix(values: np.ndarray) -> np.ndarray:
    return np.concatenate(([0.0], np.cumsum(values)))


def _interval(prefix: np.ndarray, start: int, end: int) -> float:
    return float(prefix[end] - prefix[start])


def _boundary_limits(period_s: int) -> tuple[int, int, int, int]:
    min_ew = max(15, int(round(period_s * 0.15)))
    min_arrow = max(8, int(round(period_s * 0.08)))
    min_ns = max(15, int(round(period_s * 0.15)))
    max_arrow = max(min_arrow, int(round(period_s * 0.40)))
    return min_ew, min_arrow, min_ns, max_arrow


def _fit_period(
    events: list[TrajectoryEvent],
    *,
    period_s: int,
    origin_ms: int,
) -> Fit | None:
    evidence, _ = _phase_arrays(
        events,
        period_s=period_s,
        origin_ms=origin_ms,
    )
    if not evidence:
        return None

    min_ew, min_arrow, min_ns, max_arrow = _boundary_limits(period_s)
    prefixes = {
        item.movement: [
            _prefix(channel)
            for channel in item.phase
        ]
        for item in evidence
    }

    weight_sum = sum(float(item.weights[0]) for item in evidence)
    best: Fit | None = None

    for boundary_1 in range(min_ew, period_s - min_arrow - min_ns + 1):
        arrow_end_max = min(
            period_s - min_ns,
            boundary_1 + max_arrow,
        )
        for boundary_2 in range(
            boundary_1 + min_arrow,
            arrow_end_max + 1,
        ):
            movement_scores: dict[str, float] = {}

            for item in evidence:
                p_ew, p_arrow, p_ns = prefixes[item.movement]

                # Each movement gets one score according to the state pattern
                # declared above. N->S intentionally receives both arrow and NS
                # evidence, so its best explanation is the sum of both intervals.
                ew_score = _interval(p_ew, 0, boundary_1)
                arrow_score = _interval(p_arrow, boundary_1, boundary_2)
                ns_score = _interval(p_ns, boundary_2, period_s)

                if item.movement in {"E->_W", "W->_E"}:
                    raw = ew_score
                elif item.movement in {"E->_N", "N->_E"}:
                    raw = arrow_score
                elif item.movement == "N->_S":
                    raw = arrow_score + ns_score
                elif item.movement == "S->_N":
                    raw = ns_score
                else:
                    raw = 0.0

                # Normalize to [-1, 1]. Total event weight also keeps sparse
                # movements from dominating the objective.
                movement_scores[item.movement] = float(
                    np.clip(
                        raw / max(float(item.weights[0]), 1e-9),
                        -1.0,
                        1.0,
                    )
                )

            score = (
                sum(
                    movement_scores[item.movement]
                    * math.sqrt(item.event_count)
                    for item in evidence
                )
                / max(
                    sum(math.sqrt(item.event_count) for item in evidence),
                    1e-9,
                )
            )

            # Penalize degenerate arrow windows while allowing real variation
            # in green durations.
            arrow_duration = boundary_2 - boundary_1
            duration_penalty = (
                0.08 * max(0.0, 15.0 - float(arrow_duration)) / 15.0
            )
            final_score = score - duration_penalty

            fit = Fit(
                period_s=period_s,
                origin_offset_s=0,
                boundary_1_s=boundary_1,
                boundary_2_s=boundary_2,
                score=float(final_score),
                coverage=float(
                    (
                        boundary_1
                        + arrow_duration
                        + (period_s - boundary_2)
                    )
                    / period_s
                ),
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

    # Align phase 0 to an EW-candidate event, then test a small origin window.
    # This avoids assuming that the first RELEASE in the file is the cycle start.
    ew_events = [
        event for event in usable
        if event.movement in {"E->_W", "W->_E"}
        and event.event_type in {EventType.RELEASE, EventType.CROSSING}
    ]
    if not ew_events:
        raise ValueError("no EW candidate release/crossing events")

    anchor_ms = min(event.timestamp_ms for event in ew_events)
    candidates: list[dict[str, object]] = []
    fits: dict[tuple[int, int], Fit] = {}

    for period_s in range(min_cycle_s, max_cycle_s + 1):
        # Search phase origin in a deliberately small local window around the
        # earliest EW kinematic evidence. The window is a search parameter, not
        # a manual cycle value.
        for origin_offset_s in range(-15, 16):
            origin_ms = anchor_ms + origin_offset_s * 1000
            fit = _fit_period(
                usable,
                period_s=period_s,
                origin_ms=origin_ms,
            )
            if fit is None:
                continue
            fit = Fit(
                period_s=fit.period_s,
                origin_offset_s=origin_offset_s,
                boundary_1_s=fit.boundary_1_s,
                boundary_2_s=fit.boundary_2_s,
                score=fit.score,
                coverage=fit.coverage,
                movement_scores=fit.movement_scores,
            )
            fits[(period_s, origin_offset_s)] = fit
            candidates.append({
                "cycle_seconds": period_s,
                "origin_offset_s": origin_offset_s,
                "score": round(fit.score, 4),
                "boundary_1_s": fit.boundary_1_s,
                "boundary_2_s": fit.boundary_2_s,
                "EW_duration_s": fit.boundary_1_s,
                "N_ARROW_duration_s": fit.boundary_2_s - fit.boundary_1_s,
                "NS_duration_s": period_s - fit.boundary_2_s,
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
    key = (
        int(selected["cycle_seconds"]),
        int(selected["origin_offset_s"]),
    )
    selected_fit = fits[key]

    return {
        "schema_version": 1,
        "meaning": (
            "Research prototype for joint three-state cycle identification "
            "from kinematic events using the manually validated movement "
            "state structure. It is not controller telemetry and does not "
            "classify traffic-light colors."
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
        "selected_cycle_seconds": selected_fit.period_s,
        "origin_anchor_timestamp_ms": anchor_ms,
        "origin_offset_s": selected_fit.origin_offset_s,
        "selected_model": {
            "EW_duration_s": selected_fit.boundary_1_s,
            "N_ARROW_duration_s": (
                selected_fit.boundary_2_s
                - selected_fit.boundary_1_s
            ),
            "NS_duration_s": (
                selected_fit.period_s
                - selected_fit.boundary_2_s
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
            "Infer the EW -> N+arrow -> NS traffic-signal cycle from "
            "canonical movement kinematics."
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
        f"selected={result['selected_cycle_seconds']}s, "
        f"EW={model['EW_duration_s']}s, "
        f"N+arrow={model['N_ARROW_duration_s']}s, "
        f"NS={model['NS_duration_s']}s"
    )
    print(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
