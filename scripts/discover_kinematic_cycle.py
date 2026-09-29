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
class MovementEvidence:
    movement: str
    family: str
    phases: np.ndarray
    total_score: float
    total_abs_score: float
    event_count: int


@dataclass(frozen=True)
class PhaseFit:
    cycle_seconds: int
    boundary_1_s: int
    boundary_2_s: int
    score: float
    mixed_duration_s: int
    movement_scores: dict[str, float]


def _family_for_movement(movement: str) -> str | None:
    approach = movement.split("->", 1)[0]
    if approach in {"N", "S"}:
        return "NS"
    if approach in {"E", "W"}:
        return "EW"
    return None


def _event_score(event_type: EventType) -> float:
    # Positive evidence means "this movement is active".
    # STOP is negative evidence for active signal state.
    if event_type is EventType.RELEASE:
        return 1.0
    if event_type is EventType.CROSSING:
        return 0.8
    if event_type is EventType.STOP:
        return -1.0
    return 0.0


def _phase_evidence(
    events: list[EventPoint],
    *,
    period_s: int,
) -> MovementEvidence:
    family = _family_for_movement(events[0].movement)
    if family is None:
        raise ValueError(f"unsupported movement family: {events[0].movement}")

    phases = np.zeros(period_s, dtype=float)
    for point in events:
        phase = int(math.floor(point.timestamp_s % period_s)) % period_s
        phases[phase] += _event_score(point.event_type)

    total_score = float(np.sum(phases))
    total_abs_score = float(
        sum(abs(_event_score(point.event_type)) for point in events)
    )
    return MovementEvidence(
        movement=events[0].movement,
        family=family,
        phases=phases,
        total_score=total_score,
        total_abs_score=max(total_abs_score, 1.0),
        event_count=len(events),
    )


def _build_evidence(
    points: list[EventPoint],
    *,
    period_s: int,
    min_movement_events: int,
) -> list[MovementEvidence]:
    grouped: dict[str, list[EventPoint]] = defaultdict(list)
    for point in points:
        grouped[point.movement].append(point)

    result: list[MovementEvidence] = []
    for movement, events in sorted(grouped.items()):
        if len(events) < min_movement_events:
            continue
        result.append(_phase_evidence(events, period_s=period_s))

    return result


def _prefix(values: np.ndarray) -> np.ndarray:
    return np.concatenate(([0.0], np.cumsum(values)))


def _interval_sum(prefix: np.ndarray, start_s: int, end_s: int) -> float:
    return float(prefix[end_s] - prefix[start_s])


def _boundary_constraints(period_s: int) -> tuple[int, int, int]:
    min_primary = max(10, int(round(period_s * 0.20)))
    min_mixed = max(8, int(round(period_s * 0.10)))
    max_mixed = max(min_mixed, int(round(period_s * 0.35)))
    return min_primary, min_mixed, max_mixed


def _fit_period(
    evidence: list[MovementEvidence],
    *,
    period_s: int,
) -> PhaseFit | None:
    if not evidence:
        return None

    min_primary, min_mixed, max_mixed = _boundary_constraints(period_s)
    best: PhaseFit | None = None

    prefixes = {
        item.movement: _prefix(item.phases)
        for item in evidence
    }

    for boundary_1_s in range(min_primary, period_s - min_primary - min_mixed + 1):
        for boundary_2_s in range(
            boundary_1_s + min_mixed,
            min(period_s - min_primary, boundary_1_s + max_mixed) + 1,
        ):
            mixed_duration = boundary_2_s - boundary_1_s
            weighted_scores: list[float] = []
            movement_scores: dict[str, float] = {}

            for item in evidence:
                prefix = prefixes[item.movement]
                if item.family == "EW":
                    # EW is allowed in stage 1 + mixed stage; stage 3 is its
                    # exclusive red interval.
                    inactive_score = _interval_sum(
                        prefix,
                        boundary_2_s,
                        period_s,
                    )
                else:
                    # NS is allowed in mixed stage + stage 3; stage 1 is its
                    # exclusive red interval.
                    inactive_score = _interval_sum(
                        prefix,
                        0,
                        boundary_1_s,
                    )

                active_score = item.total_score - inactive_score
                fit_score = (
                    active_score - inactive_score
                ) / item.total_abs_score
                fit_score = float(np.clip(fit_score, -1.0, 1.0))
                movement_scores[item.movement] = fit_score
                weighted_scores.append(
                    fit_score * math.log1p(item.event_count)
                )

            if not weighted_scores:
                continue

            weight_sum = sum(
                math.log1p(item.event_count)
                for item in evidence
            )
            score = sum(weighted_scores) / max(weight_sum, 1e-9)

            fit = PhaseFit(
                cycle_seconds=period_s,
                boundary_1_s=boundary_1_s,
                boundary_2_s=boundary_2_s,
                score=float(score),
                mixed_duration_s=mixed_duration,
                movement_scores=movement_scores,
            )
            if best is None or fit.score > best.score:
                best = fit

    return best


def _movement_score_summary(
    evidence: list[MovementEvidence],
    fit: PhaseFit,
) -> list[dict[str, object]]:
    return [
        {
            "movement": item.movement,
            "family": item.family,
            "fit_score": round(fit.movement_scores[item.movement], 4),
            "event_count": item.event_count,
        }
        for item in sorted(evidence, key=lambda value: value.movement)
    ]


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

    release_events = [
        event
        for event in selected_events
        if event.event_type is EventType.RELEASE
    ]
    origin_ms = (
        min(event.timestamp_ms for event in release_events)
        if release_events
        else min(event.timestamp_ms for event in selected_events)
    )

    points = [
        EventPoint(
            movement=event.movement,
            event_type=event.event_type,
            timestamp_s=(event.timestamp_ms - origin_ms) / 1000.0,
        )
        for event in selected_events
        if event.event_type
        in {EventType.STOP, EventType.RELEASE, EventType.CROSSING}
    ]

    candidates: list[dict[str, object]] = []
    selected_fits: dict[int, tuple[PhaseFit, list[MovementEvidence]]] = {}

    for period_s in range(min_cycle_s, max_cycle_s + 1):
        evidence = _build_evidence(
            points,
            period_s=period_s,
            min_movement_events=min_movement_events,
        )
        fit = _fit_period(evidence, period_s=period_s)
        if fit is None:
            continue

        selected_fits[period_s] = (fit, evidence)
        primary_fraction = (
            fit.boundary_1_s + (period_s - fit.boundary_2_s)
        ) / period_s
        candidates.append(
            {
                "cycle_seconds": period_s,
                "score": round(fit.score, 4),
                "boundary_1_s": fit.boundary_1_s,
                "boundary_2_s": fit.boundary_2_s,
                "mixed_duration_s": fit.mixed_duration_s,
                "primary_stage_fraction": round(primary_fraction, 4),
                "movement_count": len(evidence),
            }
        )

    if not candidates:
        raise ValueError(
            "no cycle candidates: not enough movement events in the requested range"
        )

    candidates.sort(
        key=lambda item: (
            -float(item["score"]),
            -int(item["movement_count"]),
            int(item["cycle_seconds"]),
        )
    )
    selected_cycle = int(candidates[0]["cycle_seconds"])
    selected_fit, selected_evidence = selected_fits[selected_cycle]

    b1 = selected_fit.boundary_1_s
    b2 = selected_fit.boundary_2_s

    return {
        "schema_version": 2,
        "meaning": (
            "Joint research prototype for cycle and shared phase-boundary "
            "identification from kinematic event evidence. It is not controller "
            "telemetry and does not classify traffic-light colors."
        ),
        "selected_cycle_seconds": selected_cycle,
        "origin_timestamp_ms": origin_ms,
        "event_count": len(points),
        "movement_count": len({point.movement for point in points}),
        "model": {
            "stage_count": 3,
            "stage_1": {
                "name": "EW_EXCLUSIVE",
                "start_s": 0,
                "end_s": b1,
            },
            "stage_2": {
                "name": "MIXED_TRANSITION",
                "start_s": b1,
                "end_s": b2,
            },
            "stage_3": {
                "name": "NS_EXCLUSIVE",
                "start_s": b2,
                "end_s": selected_cycle,
            },
            "constraint": (
                "EW movements are active in stage 1 + mixed stage; NS movements "
                "are active in mixed stage + stage 3. Stops are therefore evidence "
                "for the corresponding exclusive stage being red."
            ),
        },
        "candidate_cycles": candidates[:15],
        "selected_fit": {
            "score": round(selected_fit.score, 4),
            "mixed_duration_s": selected_fit.mixed_duration_s,
            "movement_scores": _movement_score_summary(
                selected_evidence,
                selected_fit,
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Research prototype: jointly infer cycle and three shared phase "
            "boundaries from STOP/RELEASE/CROSSING constraints."
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
        "Joint kinematic phase prototype: "
        f"selected={result['selected_cycle_seconds']}s, "
        f"events={result['event_count']}, "
        f"movements={result['movement_count']}"
    )
    print(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
