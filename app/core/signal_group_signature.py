from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import ceil, floor, isfinite
from typing import Iterable, Sequence

from app.core.models import EventType, TrajectoryEvent


class SignalGroupRelation(str, Enum):
    EQUIVALENT = "equivalent"
    CONTAINED = "contained"
    CONTAINS = "contains"
    PARTIAL_OVERLAP = "partial_overlap"
    DISJOINT = "disjoint"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CROSS_APPROACH = "cross_approach"


@dataclass(frozen=True)
class CircularInterval:
    """Half-open interval on the circular phase domain."""

    start: float
    end: float
    cycle_seconds: float

    def __post_init__(self) -> None:
        cycle = float(self.cycle_seconds)
        if not isfinite(cycle) or cycle <= 0:
            raise ValueError("cycle_seconds must be a positive finite number")
        object.__setattr__(self, "cycle_seconds", cycle)
        object.__setattr__(self, "start", float(self.start) % cycle)
        object.__setattr__(self, "end", float(self.end) % cycle)

    @property
    def duration(self) -> float:
        value = (self.end - self.start) % self.cycle_seconds
        if value == 0 and self.start == self.end:
            return self.cycle_seconds
        return value

    def contains(self, phase_seconds: float) -> bool:
        phase = float(phase_seconds) % self.cycle_seconds
        if self.start == self.end:
            return False
        if self.start < self.end:
            return self.start <= phase < self.end
        return phase >= self.start or phase < self.end

    def intersection_length(self, other: "CircularInterval") -> float:
        self._check_cycle(other)
        return sum(
            max(0.0, min(a_end, b_end) - max(a_start, b_start))
            for a_start, a_end in self._linear_segments()
            for b_start, b_end in other._linear_segments()
        )

    def union_length(self, other: "CircularInterval") -> float:
        self._check_cycle(other)
        return self.duration + other.duration - self.intersection_length(other)

    def iou(self, other: "CircularInterval") -> float:
        union = self.union_length(other)
        return self.intersection_length(other) / union if union > 0 else 0.0

    def containment(self, other: "CircularInterval") -> float:
        if self.duration <= 0:
            return 0.0
        return self.intersection_length(other) / self.duration

    def _linear_segments(self) -> tuple[tuple[float, float], ...]:
        if self.start == self.end:
            return ()
        if self.start < self.end:
            return ((self.start, self.end),)
        return (
            (self.start, self.cycle_seconds),
            (0.0, self.end),
        )

    def _check_cycle(self, other: "CircularInterval") -> None:
        if abs(self.cycle_seconds - other.cycle_seconds) > 1e-9:
            raise ValueError("intervals must use the same cycle_seconds")


@dataclass(frozen=True)
class MovementPhaseSignature:
    """Phase-folded evidence for one movement on one approach."""

    movement: str
    approach: str
    cycle_seconds: float
    bin_seconds: float
    phase_presence: tuple[float, ...]
    active_intervals: tuple[CircularInterval, ...]
    support_count: int
    observed_cycle_count: int
    active_cycle_count: int
    repeatability: float
    boundary_stability: float

    @property
    def support_ratio(self) -> float:
        if self.observed_cycle_count <= 0:
            return 0.0
        return self.active_cycle_count / self.observed_cycle_count

    @property
    def is_sufficient(self) -> bool:
        return self.support_count > 0 and self.active_cycle_count >= 3


def build_movement_phase_signatures(
    events: Iterable[TrajectoryEvent],
    *,
    cycle_seconds: float,
    origin_timestamp_ms: int | None = None,
    bin_seconds: float = 1.0,
    min_cycle_presence: float = 0.35,
    dedupe_seconds: float = 2.0,
) -> tuple[MovementPhaseSignature, ...]:
    """Build conservative phase-folded signatures from RELEASE/CROSSING.

    Presence is measured per cycle rather than by raw event count, preventing
    a high-volume movement from dominating a sparse movement.
    """

    cycle = float(cycle_seconds)
    bin_width = float(bin_seconds)
    if cycle <= 0 or not isfinite(cycle):
        raise ValueError("cycle_seconds must be positive and finite")
    if bin_width <= 0 or bin_width > cycle:
        raise ValueError("bin_seconds must be positive and <= cycle_seconds")
    if not 0 < min_cycle_presence <= 1:
        raise ValueError("min_cycle_presence must be in (0, 1]")
    if dedupe_seconds < 0:
        raise ValueError("dedupe_seconds must be non-negative")

    selected = [
        event
        for event in events
        if event.event_type in {EventType.RELEASE, EventType.CROSSING}
        and "->" in str(event.movement)
        and not str(event.movement).endswith("->UNKNOWN")
    ]
    if not selected:
        return ()

    anchor = (
        min(event.timestamp_ms for event in selected)
        if origin_timestamp_ms is None
        else int(origin_timestamp_ms)
    )

    grouped: dict[tuple[str, str], dict[int, list[float]]] = {}
    for event in selected:
        relative_seconds = (event.timestamp_ms - anchor) / 1000.0
        cycle_index = floor(relative_seconds / cycle)
        phase = relative_seconds % cycle
        key = (str(event.approach).strip(), str(event.movement).strip())
        grouped.setdefault(key, {}).setdefault(cycle_index, []).append(phase)

    signatures: list[MovementPhaseSignature] = []
    for (approach, movement), cycles in sorted(grouped.items()):
        deduped: dict[int, list[float]] = {}
        for cycle_index, phases in cycles.items():
            values = sorted(phases)
            kept: list[float] = []
            for phase in values:
                if not kept or phase - kept[-1] > dedupe_seconds:
                    kept.append(phase)
            if len(kept) > 1 and kept[0] + cycle - kept[-1] <= dedupe_seconds:
                merged = ((kept[0] + kept[-1] - cycle) / 2.0) % cycle
                kept = [merged] + kept[1:-1]
            deduped[cycle_index] = kept

        observed_cycles = len(deduped)
        if observed_cycles == 0:
            continue

        bins = max(1, ceil(cycle / bin_width))
        presence_counts = [0] * bins
        occupied_by_cycle: dict[int, set[int]] = {}
        all_phases: list[float] = []

        for cycle_index, phases in deduped.items():
            occupied = {
                min(bins - 1, int(phase / bin_width))
                for phase in phases
            }
            occupied_by_cycle[cycle_index] = occupied
            for index in occupied:
                presence_counts[index] += 1
            all_phases.extend(phases)

        threshold = max(1, ceil(observed_cycles * min_cycle_presence))
        active_bins = [count >= threshold for count in presence_counts]
        intervals = _active_intervals(
            active_bins,
            cycle_seconds=cycle,
            bin_seconds=bin_width,
        )

        active_cycles = sum(
            1
            for phases in deduped.values()
            if any(
                interval.contains(phase)
                for phase in phases
                for interval in intervals
            )
        )

        centers = [
            _circular_mean(phases, cycle)
            for phases in deduped.values()
            if phases
        ]
        boundary_stability = _circular_stability(centers, cycle)
        repeatability = active_cycles / observed_cycles

        signatures.append(
            MovementPhaseSignature(
                movement=movement,
                approach=approach,
                cycle_seconds=cycle,
                bin_seconds=bin_width,
                phase_presence=tuple(
                    count / observed_cycles for count in presence_counts
                ),
                active_intervals=tuple(intervals),
                support_count=len(all_phases),
                observed_cycle_count=observed_cycles,
                active_cycle_count=active_cycles,
                repeatability=repeatability,
                boundary_stability=boundary_stability,
            )
        )

    return tuple(signatures)


def compare_movement_signatures(
    left: MovementPhaseSignature,
    right: MovementPhaseSignature,
    *,
    equivalence_iou: float = 0.70,
    containment: float = 0.85,
    minimum_support_cycles: int = 3,
) -> SignalGroupRelation:
    """Classify the temporal relationship between two movement signatures."""

    if abs(left.cycle_seconds - right.cycle_seconds) > 1e-9:
        raise ValueError("signatures must use the same cycle_seconds")
    if left.approach != right.approach:
        return SignalGroupRelation.CROSS_APPROACH
    if (
        left.active_cycle_count < minimum_support_cycles
        or right.active_cycle_count < minimum_support_cycles
        or not left.active_intervals
        or not right.active_intervals
    ):
        return SignalGroupRelation.INSUFFICIENT_EVIDENCE

    intersection, left_duration, right_duration = _interval_set_metrics(
        left.active_intervals,
        right.active_intervals,
    )
    union = left_duration + right_duration - intersection
    set_iou = intersection / union if union > 0 else 0.0
    left_in_right = intersection / left_duration if left_duration > 0 else 0.0
    right_in_left = intersection / right_duration if right_duration > 0 else 0.0

    if set_iou >= equivalence_iou:
        return SignalGroupRelation.EQUIVALENT
    if left_in_right >= containment:
        return SignalGroupRelation.CONTAINED
    if right_in_left >= containment:
        return SignalGroupRelation.CONTAINS
    if intersection > 0:
        return SignalGroupRelation.PARTIAL_OVERLAP
    return SignalGroupRelation.DISJOINT


def _interval_set_metrics(
    left: Sequence[CircularInterval],
    right: Sequence[CircularInterval],
) -> tuple[float, float, float]:
    """Compare disjoint circular interval sets without best-pair bias."""

    intersection = sum(
        first.intersection_length(second)
        for first in left
        for second in right
    )
    left_duration = sum(interval.duration for interval in left)
    right_duration = sum(interval.duration for interval in right)
    return intersection, left_duration, right_duration


def _active_intervals(
    active_bins: Sequence[bool],
    *,
    cycle_seconds: float,
    bin_seconds: float,
) -> list[CircularInterval]:
    if not any(active_bins):
        return []
    size = len(active_bins)
    if all(active_bins):
        return [CircularInterval(0.0, 0.0, cycle_seconds)]

    runs: list[tuple[int, int]] = []
    index = 0
    while index < size:
        if not active_bins[index]:
            index += 1
            continue
        start = index
        while index < size and active_bins[index]:
            index += 1
        runs.append((start, index))

    if len(runs) >= 2 and runs[0][0] == 0 and runs[-1][1] == size:
        runs = [(runs[-1][0], runs[0][1])] + runs[1:-1]

    intervals: list[CircularInterval] = []
    for start_bin, end_bin in runs:
        start = start_bin * bin_seconds
        end = min(end_bin * bin_seconds, cycle_seconds)
        intervals.append(
            CircularInterval(start, end % cycle_seconds, cycle_seconds)
        )
    return intervals


def _circular_mean(values: Sequence[float], cycle_seconds: float) -> float:
    import math

    if not values:
        return 0.0
    angles = [2.0 * math.pi * value / cycle_seconds for value in values]
    sin_mean = sum(math.sin(angle) for angle in angles) / len(angles)
    cos_mean = sum(math.cos(angle) for angle in angles) / len(angles)
    angle = math.atan2(sin_mean, cos_mean)
    if angle < 0:
        angle += 2.0 * math.pi
    return angle * cycle_seconds / (2.0 * math.pi)


def _circular_distance(left: float, right: float, cycle_seconds: float) -> float:
    difference = abs(left - right) % cycle_seconds
    return min(difference, cycle_seconds - difference)


def _circular_stability(centers: Sequence[float], cycle_seconds: float) -> float:
    if len(centers) < 2:
        return 1.0 if centers else 0.0
    mean = _circular_mean(centers, cycle_seconds)
    mean_distance = sum(
        _circular_distance(value, mean, cycle_seconds)
        for value in centers
    ) / len(centers)
    return max(0.0, 1.0 - mean_distance / (cycle_seconds / 2.0))
