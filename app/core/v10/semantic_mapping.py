from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment


DEFAULT_ACTIVITY_THRESHOLD = 0.05
DEFAULT_DURATION_WEIGHT = 0.80


@dataclass(frozen=True)
class PhaseSpec:
    """Physical phase definition used to interpret anonymous V9 states."""

    name: str
    green_movements: frozenset[str]
    duration_s: float | None = None
    additional_movements: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        name = str(self.name).strip()
        green = frozenset(str(item).strip() for item in self.green_movements if str(item).strip())
        additional = frozenset(
            str(item).strip()
            for item in self.additional_movements
            if str(item).strip()
        )
        if not name:
            raise ValueError("phase name must not be empty")
        if not green:
            raise ValueError("phase must contain at least one green movement")
        if self.duration_s is not None and float(self.duration_s) <= 0:
            raise ValueError("phase duration must be positive")
        if not additional <= green:
            raise ValueError("additional movements must be a subset of green movements")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "green_movements", green)
        object.__setattr__(self, "additional_movements", additional)
        if self.duration_s is not None:
            object.__setattr__(self, "duration_s", float(self.duration_s))


@dataclass(frozen=True)
class SemanticMappingResult:
    mapping: dict[str, str]
    confidence: float
    scores: dict[str, dict[str, float]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping": dict(self.mapping),
            "confidence": round(self.confidence, 4),
            "scores": {
                anonymous: {
                    physical: round(float(score), 6)
                    for physical, score in candidates.items()
                }
                for anonymous, candidates in self.scores.items()
            },
        }


def _phase_names(schedule: Mapping[str, Any]) -> list[str]:
    raw = schedule.get("phase_names")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        count = int(schedule.get("phase_count", 0))
        raw = [f"PHASE_{chr(ord('A') + index)}" for index in range(count)]
    names = [str(item).strip() for item in raw]
    if not names or any(not item for item in names) or len(set(names)) != len(names):
        raise ValueError("V9 phase names must be unique and non-empty")
    return names


def _extract_activity(result: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    schedule = result.get("schedule")
    if not isinstance(schedule, Mapping):
        raise ValueError("V9 result has no schedule")

    rows = schedule.get("stream_activity_by_phase", ())
    if not isinstance(rows, Sequence):
        return {}

    activity: dict[str, dict[str, float]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        movement = str(row.get("stream", "")).strip()
        probabilities = row.get("event_probability_by_phase", {})
        if not movement or not isinstance(probabilities, Mapping):
            continue
        activity[movement] = {
            str(phase).strip(): float(value)
            for phase, value in probabilities.items()
            if str(phase).strip()
        }
    return activity


def _extract_durations(result: Mapping[str, Any]) -> dict[str, float]:
    schedule = result.get("schedule")
    if not isinstance(schedule, Mapping):
        raise ValueError("V9 result has no schedule")
    raw = schedule.get("baseline_duration_targets_s", {})
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(phase).strip(): float(value)
        for phase, value in raw.items()
        if str(phase).strip() and float(value) > 0
    }


def _signature_score(
    activity: Mapping[str, float],
    target: PhaseSpec,
    *,
    threshold: float,
) -> float:
    """Score how well per-stream activity matches a physical green set."""
    observed = {
        movement
        for movement, probability in activity.items()
        if float(probability) >= threshold
    }
    all_movements = set(activity) | set(target.green_movements)
    if not all_movements:
        return 0.0

    target_green = set(target.green_movements)
    target_red = all_movements - target_green
    green_score = (
        sum(float(activity.get(movement, 0.0)) for movement in target_green)
        / max(1, len(target_green))
    )
    red_score = (
        sum(max(0.0, 1.0 - float(activity.get(movement, 0.0))) for movement in target_red)
        / max(1, len(target_red))
        if target_red
        else 1.0
    )

    intersection = len(observed & target_green)
    union = len(observed | target_green)
    jaccard = intersection / union if union else 0.0
    coverage = intersection / max(1, len(target_green))
    return float(np.clip(
        0.45 * green_score
        + 0.20 * red_score
        + 0.20 * jaccard
        + 0.15 * coverage,
        0.0,
        1.0,
    ))


def _duration_score(observed: float | None, expected: float | None) -> float:
    if observed is None or expected is None:
        return 0.0
    scale = max(3.0, 0.12 * float(expected))
    return float(math.exp(-abs(float(observed) - float(expected)) / scale))


def map_v9_to_physical(
    result: Mapping[str, Any],
    physical_phases: Sequence[PhaseSpec],
    *,
    activity_threshold: float = DEFAULT_ACTIVITY_THRESHOLD,
    duration_weight: float = DEFAULT_DURATION_WEIGHT,
) -> SemanticMappingResult:
    """Map arbitrary anonymous V9 states to an arbitrary physical phase catalog."""
    if not 0.0 <= float(activity_threshold) <= 1.0:
        raise ValueError("activity_threshold must be in [0, 1]")
    if not 0.0 <= float(duration_weight) <= 1.0:
        raise ValueError("duration_weight must be in [0, 1]")
    if not physical_phases:
        raise ValueError("physical phase catalog must not be empty")

    schedule = result.get("schedule")
    if not isinstance(schedule, Mapping):
        raise ValueError("V9 result has no schedule")
    anonymous = _phase_names(schedule)
    physical = list(physical_phases)
    if len(anonymous) != len(physical):
        raise ValueError(
            "phase count mismatch: "
            f"decoded={len(anonymous)} catalog={len(physical)}"
        )

    activity = _extract_activity(result)
    durations = _extract_durations(result)

    scores: dict[str, dict[str, float]] = {}
    matrix = np.zeros((len(anonymous), len(physical)), dtype=float)
    for i, phase_name in enumerate(anonymous):
        phase_activity = {
            movement: probabilities.get(phase_name, 0.0)
            for movement, probabilities in activity.items()
        }
        scores[phase_name] = {}
        for j, spec in enumerate(physical):
            duration = _duration_score(durations.get(phase_name), spec.duration_s)
            signature = _signature_score(
                phase_activity,
                spec,
                threshold=activity_threshold,
            )
            score = (
                float(duration_weight) * duration
                + (1.0 - float(duration_weight)) * signature
            )
            matrix[i, j] = score
            scores[phase_name][spec.name] = score

    rows, cols = linear_sum_assignment(-matrix)
    mapping = {
        anonymous[int(row)]: physical[int(col)].name
        for row, col in zip(rows, cols)
    }

    selected = [matrix[int(row), int(col)] for row, col in zip(rows, cols)]
    confidence = float(np.mean(selected)) if selected else 0.0
    return SemanticMappingResult(
        mapping=mapping,
        confidence=float(np.clip(confidence, 0.0, 1.0)),
        scores=scores,
    )


def normalized_segments(
    result: Mapping[str, Any],
    mapping: Mapping[str, str],
) -> list[list[Any]]:
    schedule = result.get("schedule")
    if not isinstance(schedule, Mapping):
        raise ValueError("V9 result has no schedule")
    phase_names = _phase_names(schedule)
    raw = schedule.get("baseline_segments", ())
    if not isinstance(raw, Sequence):
        raise ValueError("V9 baseline segments must be a sequence")
    period = float(schedule.get("period_s", 0.0))
    if period <= 0:
        raise ValueError("V9 period must be positive")

    result_segments: list[list[Any]] = []
    for item in raw:
        if not isinstance(item, Sequence) or len(item) < 3:
            continue
        start, end, index = float(item[0]), float(item[1]), int(item[2])
        if start >= period - 1e-9:
            break
        if index < 0 or index >= len(phase_names):
            raise ValueError(f"invalid phase index in baseline segment: {index}")
        anonymous = phase_names[index]
        physical = mapping.get(anonymous)
        if physical is None:
            raise ValueError(f"no physical mapping for phase {anonymous!r}")
        result_segments.append([start, min(end, period), physical])
    return result_segments


def signal_state_at(
    result: Mapping[str, Any],
    timestamp_s: float,
    physical_phases: Sequence[PhaseSpec],
    mapping: Mapping[str, str],
) -> dict[str, Any]:
    if timestamp_s < 0:
        raise ValueError("timestamp_s must be non-negative")
    schedule = result.get("schedule")
    if not isinstance(schedule, Mapping):
        raise ValueError("V9 result has no schedule")
    period = float(schedule.get("period_s", 0.0))
    if period <= 0:
        raise ValueError("V9 period must be positive")

    specs = {phase.name: phase for phase in physical_phases}
    segments = normalized_segments(result, mapping)
    position = float(timestamp_s) % period
    active: str | None = None
    for start, end, physical in segments:
        if float(start) <= position < float(end):
            active = str(physical)
            break
    if active is None:
        raise ValueError("timestamp is outside the available baseline")
    spec = specs.get(active)
    if spec is None:
        raise ValueError(f"mapped physical phase {active!r} is not in catalog")

    all_green = set().union(*(item.green_movements for item in physical_phases))
    return {
        "timestamp_s": round(float(timestamp_s), 3),
        "cycle_position_s": round(position, 3),
        "phase": active,
        "green_movements": sorted(spec.green_movements),
        "additional_movements": sorted(spec.additional_movements),
        "red_movements": sorted(all_green - set(spec.green_movements)),
    }


def _circular_duration(start: float, end: float, cycle: float) -> float:
    start %= cycle
    end %= cycle
    return (end - start) % cycle or cycle


def build_phase_specs_from_signal_plan_dict(
    payload: Mapping[str, Any],
) -> tuple[PhaseSpec, ...]:
    """Adapt a serialized SignalPlan into V10 physical phase specs."""
    cycle = float(payload.get("cycle_seconds", 0.0))
    if cycle <= 0:
        raise ValueError("signal plan cycle must be positive")

    raw_stages = payload.get("stages", ())
    if not isinstance(raw_stages, Sequence):
        raise ValueError("signal plan stages must be a sequence")

    specs: list[PhaseSpec] = []
    for raw in raw_stages:
        if not isinstance(raw, Mapping):
            continue
        stage_id = int(raw.get("stage_id", len(specs) + 1))
        green = frozenset(
            str(item).strip()
            for item in raw.get("active_movements", ())
            if str(item).strip()
        )
        additional = frozenset(
            str(item).strip()
            for item in raw.get("additional_movements", ())
            if str(item).strip()
        )
        if not green:
            continue
        specs.append(
            PhaseSpec(
                name=str(raw.get("name", f"STAGE_{stage_id}")).strip(),
                green_movements=green,
                additional_movements=additional,
                duration_s=_circular_duration(
                    float(raw.get("phase_start", 0.0)),
                    float(raw.get("phase_end", 0.0)),
                    cycle,
                ),
            )
        )
    if not specs:
        raise ValueError("signal plan has no non-empty stages")
    return tuple(specs)


def build_phase_specs_from_signal_plan(plan: Any) -> tuple[PhaseSpec, ...]:
    """Adapt the existing SignalPlan stages into V10 physical phase specs."""
    cycle = float(plan.cycle_seconds)
    if cycle <= 0:
        raise ValueError("signal plan cycle must be positive")
    specs: list[PhaseSpec] = []
    for stage in plan.stages:
        green = frozenset(str(item).strip() for item in stage.active_movements if str(item).strip())
        if not green:
            continue
        specs.append(
            PhaseSpec(
                name=f"STAGE_{int(stage.stage_id)}",
                green_movements=green,
                duration_s=_circular_duration(
                    float(stage.phase_start),
                    float(stage.phase_end),
                    cycle,
                ),
            )
        )
    if not specs:
        raise ValueError("signal plan has no non-empty stages")
    return tuple(specs)


__all__ = [
    "DEFAULT_ACTIVITY_THRESHOLD",
    "DEFAULT_DURATION_WEIGHT",
    "PhaseSpec",
    "SemanticMappingResult",
    "build_phase_specs_from_signal_plan",
    "build_phase_specs_from_signal_plan_dict",
    "map_v9_to_physical",
    "normalized_segments",
    "signal_state_at",
]