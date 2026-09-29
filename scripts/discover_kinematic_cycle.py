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


@dataclass(frozen=True)
class EventPoint:
    movement: str
    event_type: EventType
    timestamp_s: float


@dataclass(frozen=True)
class MovementFit:
    movement: str
    cost: float
    start_s: float
    end_s: float
    duration_s: float
    release_anchor_score: float
    crossing_inside: float
    stop_outside: float
    event_count: int


def _circular_forward_distance(value: float, start: float, period: float) -> float:
    return (value - start) % period


def _movement_release_anchors(
    events: list[EventPoint],
    *,
    cluster_gap_s: float = 4.0,
) -> list[float]:
    releases = sorted(
        point.timestamp_s
        for point in events
        if point.event_type is EventType.RELEASE
    )
    if not releases:
        return []

    anchors = [releases[0]]
    last = releases[0]
    for timestamp_s in releases[1:]:
        if timestamp_s - last > cluster_gap_s:
            anchors.append(timestamp_s)
        last = timestamp_s
    return anchors


def _interval_contains(
    phase: float,
    start_s: float,
    end_s: float,
    period: float,
) -> bool:
    if start_s <= end_s:
        return start_s <= phase < end_s
    return phase >= start_s or phase < end_s


def _best_movement_fit(
    events: list[EventPoint],
    *,
    period_s: int,
    min_green_s: int = 8,
    max_green_fraction: float = 0.75,
    reaction_min_s: float = 0.5,
    reaction_max_s: float = 6.0,
) -> MovementFit | None:
    if not events:
        return None

    anchors = _movement_release_anchors(events)
    crossings = [
        point.timestamp_s % period_s
        for point in events
        if point.event_type is EventType.CROSSING
    ]
    stops = [
        point.timestamp_s % period_s
        for point in events
        if point.event_type is EventType.STOP
    ]

    max_green_s = min(
        period_s - 10,
        max(min_green_s, int(round(period_s * max_green_fraction))),
    )
    if max_green_s < min_green_s:
        return None

    best: MovementFit | None = None

    for duration_s in range(min_green_s, max_green_s + 1):
        for start_s in range(period_s):
            end_s = (start_s + duration_s) % period_s

            if anchors:
                anchor_scores = []
                for anchor in anchors:
                    phase = anchor % period_s
                    delay = _circular_forward_distance(
                        phase,
                        start_s,
                        period_s,
                    )
                    if reaction_min_s <= delay <= reaction_max_s:
                        anchor_scores.append(
                            math.exp(-((delay - 1.5) ** 2) / (2.0 * 1.5**2))
                        )
                    else:
                        anchor_scores.append(0.0)
                anchor_score = float(np.mean(anchor_scores))
            else:
                anchor_score = 0.0

            crossing_inside = (
                float(np.mean([
                    _interval_contains(
                        phase,
                        start_s,
                        end_s,
                        period_s,
                    )
                    for phase in crossings
                ]))
                if crossings
                else 0.5
            )

            stop_outside = (
                float(np.mean([
                    not _interval_contains(
                        phase,
                        start_s,
                        end_s,
                        period_s,
                    )
                    for phase in stops
                ]))
                if stops
                else 0.5
            )

            stop_inside = 1.0 - stop_outside
            cost = (
                7.0 * (1.0 - anchor_score)
                + 2.0 * (1.0 - crossing_inside)
                + 8.0 * stop_inside
                + 0.015 * duration_s
            )

            fit = MovementFit(
                movement=events[0].movement,
                cost=float(cost),
                start_s=float(start_s),
                end_s=float(end_s),
                duration_s=float(duration_s),
                release_anchor_score=float(anchor_score),
                crossing_inside=float(crossing_inside),
                stop_outside=float(stop_outside),
                event_count=len(events),
            )
            if best is None or fit.cost < best.cost:
                best = fit

    return best


def _family_for_movement(movement: str) -> str | None:
    approach = movement.split("->", 1)[0]
    if approach in {"N", "S"}:
        return "NS"
    if approach in {"E", "W"}:
        return "EW"
    return None


def _family_masks(
    fits: list[MovementFit],
    period_s: int,
) -> tuple[np.ndarray, np.ndarray]:
    ns = np.zeros(period_s, dtype=bool)
    ew = np.zeros(period_s, dtype=bool)

    for fit in fits:
        family = _family_for_movement(fit.movement)
        if family is None:
            continue
        for phase in range(period_s):
            active = _interval_contains(
                float(phase),
                fit.start_s,
                fit.end_s,
                period_s,
            )
            if family == "NS" and active:
                ns[phase] = True
            elif family == "EW" and active:
                ew[phase] = True

    return ns, ew


def _score_period(
    points: list[EventPoint],
    *,
    period_s: int,
    min_movement_events: int,
) -> tuple[float, list[MovementFit], float, float] | None:
    grouped: dict[str, list[EventPoint]] = defaultdict(list)
    for point in points:
        grouped[point.movement].append(point)

    fits: list[MovementFit] = []
    weights: list[float] = []

    for movement, events in sorted(grouped.items()):
        if len(events) < min_movement_events:
            continue
        fit = _best_movement_fit(events, period_s=period_s)
        if fit is None:
            continue
        fits.append(fit)
        weights.append(math.log1p(len(events)))

    if not fits:
        return None

    weight_sum = sum(weights)
    movement_cost = sum(
        fit.cost * weight
        for fit, weight in zip(fits, weights)
    ) / max(weight_sum, 1e-9)

    ns_mask, ew_mask = _family_masks(fits, period_s)
    overlap = float(np.mean(ns_mask & ew_mask))
    uncovered = float(np.mean(~(ns_mask | ew_mask)))

    total_cost = (
        movement_cost
        + 18.0 * overlap
        + 0.5 * uncovered
    )

    return (
        float(total_cost),
        fits,
        float(movement_cost),
        float(overlap),
    )


def discover_kinematic_cycle(
    events: list[TrajectoryEvent],
    *,
    min_cycle_s: int = 50,
    max_cycle_s: int = 130,
    min_movement_events: int = 6,
) -> dict[str, object]:
    selected_events = [
        event
        for event in events
        if event.movement
        and "->" in event.movement
        and not event.movement.endswith("->UNKNOWN")
        and event.confidence > 0.0
    ]
    if not selected_events:
        raise ValueError("no usable movement events")

    origin_ms = min(event.timestamp_ms for event in selected_events)
    points = [
        EventPoint(
            movement=event.movement,
            event_type=event.event_type,
            timestamp_s=(event.timestamp_ms - origin_ms) / 1000.0,
        )
        for event in selected_events
        if event.event_type in {
            EventType.STOP,
            EventType.RELEASE,
            EventType.CROSSING,
        }
    ]

    candidates: list[dict[str, object]] = []
    for period_s in range(min_cycle_s, max_cycle_s + 1):
        scored = _score_period(
            points,
            period_s=period_s,
            min_movement_events=min_movement_events,
        )
        if scored is None:
            continue
        total_cost, fits, movement_cost, family_overlap = scored
        candidates.append({
            "cycle_seconds": period_s,
            "total_cost": round(total_cost, 4),
            "movement_cost": round(movement_cost, 4),
            "family_overlap": round(family_overlap, 4),
            "movement_count": len(fits),
        })

    if not candidates:
        raise ValueError(
            "no cycle candidates: not enough movement events in the requested range"
        )

    candidates.sort(key=lambda item: (
        float(item["total_cost"]),
        float(item["family_overlap"]),
        int(item["cycle_seconds"]),
    ))
    selected_cycle = int(candidates[0]["cycle_seconds"])

    selected_scored = _score_period(
        points,
        period_s=selected_cycle,
        min_movement_events=min_movement_events,
    )
    if selected_scored is None:
        raise RuntimeError("selected cycle could not be refit")

    _, fits, movement_cost, family_overlap = selected_scored
    ns_mask, ew_mask = _family_masks(fits, selected_cycle)

    return {
        "schema_version": 1,
        "meaning": (
            "Research prototype for cycle identification from kinematic event "
            "constraints. It is not controller telemetry and does not classify "
            "traffic-light colors."
        ),
        "selected_cycle_seconds": selected_cycle,
        "origin_timestamp_ms": origin_ms,
        "event_count": len(points),
        "movement_count": len({point.movement for point in points}),
        "candidate_cycles": candidates[:15],
        "selected_fit": {
            "movement_cost": round(movement_cost, 4),
            "family_overlap": round(family_overlap, 4),
            "ns_coverage": round(float(np.mean(ns_mask)), 4),
            "ew_coverage": round(float(np.mean(ew_mask)), 4),
            "movements": [
                {
                    "movement": fit.movement,
                    "start_s": fit.start_s,
                    "end_s": fit.end_s,
                    "duration_s": fit.duration_s,
                    "release_anchor_score": round(
                        fit.release_anchor_score,
                        4,
                    ),
                    "crossing_inside": round(
                        fit.crossing_inside,
                        4,
                    ),
                    "stop_outside": round(
                        fit.stop_outside,
                        4,
                    ),
                    "event_count": fit.event_count,
                }
                for fit in sorted(fits, key=lambda item: item.movement)
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Research prototype: infer traffic-signal cycle from STOP/"
            "RELEASE/CROSSING kinematic constraints."
        )
    )
    parser.add_argument("path", type=Path, help="Trajectory JSON file")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("kinematic_cycle_result.json"),
        help="Output JSON path",
    )
    parser.add_argument("--min-cycle", type=int, default=50)
    parser.add_argument("--max-cycle", type=int, default=130)
    parser.add_argument(
        "--min-movement-events",
        type=int,
        default=6,
        help="Minimum STOP/RELEASE/CROSSING events required per movement.",
    )
    args = parser.parse_args()

    if args.min_cycle <= 0 or args.max_cycle <= args.min_cycle:
        parser.error("--min-cycle/--max-cycle must define a positive range")
    if args.min_movement_events < 2:
        parser.error("--min-movement-events must be at least 2")

    trajectories = load_trajectory_file(args.path)
    if not trajectories:
        parser.error("source contains no usable car trajectories")

    events = extract_events_from_trajectories(trajectories)
    result = discover_kinematic_cycle(
        events,
        min_cycle_s=args.min_cycle,
        max_cycle_s=args.max_cycle,
        min_movement_events=args.min_movement_events,
    )
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        "Kinematic cycle prototype: "
        f"selected={result['selected_cycle_seconds']}s, "
        f"events={result['event_count']}, "
        f"movements={result['movement_count']}"
    )
    print(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
