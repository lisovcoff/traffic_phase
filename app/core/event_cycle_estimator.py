from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

from app.core.cycle_estimator import CycleEstimate, CycleEstimator
from app.core.intersection_topology import (
    DEFAULT_INTERSECTION_TOPOLOGY,
    IntersectionTopology,
)
from app.core.models import EventType, TrajectoryEvent


@dataclass(frozen=True)
class EventFlowSignal:
    signal: np.ndarray
    sampling_seconds: float
    start_timestamp_ms: int
    used_events: int
    release_events: int
    crossing_events: int
    counts_by_direction: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "sampling_seconds": self.sampling_seconds,
            "start_timestamp_ms": self.start_timestamp_ms,
            "used_events": self.used_events,
            "release_events": self.release_events,
            "crossing_events": self.crossing_events,
            "counts_by_direction": dict(self.counts_by_direction),
        }


@dataclass(frozen=True)
class EventCycleEstimate:
    estimate: CycleEstimate
    flow: EventFlowSignal

    def to_dict(self) -> dict[str, object]:
        return {
            "estimated_cycle": self.estimate.cycle_seconds,
            "candidate_periods": [
                candidate.to_dict()
                for candidate in self.estimate.candidate_periods
            ],
            "autocorrelation_strength": (
                self.estimate.candidate_periods[0].strength
                if self.estimate.candidate_periods
                else 0.0
            ),
            "confidence": self.estimate.confidence,
            "used_events": self.flow.used_events,
            "release_events": self.flow.release_events,
            "crossing_events": self.flow.crossing_events,
            "counts_by_direction": self.flow.counts_by_direction,
        }


def _axis(approach: str) -> str | None:
    if approach in {"N", "S"}:
        return "NS"
    if approach in {"E", "W"}:
        return "EW"
    return None


def build_event_flow_signal(
    events: Iterable[TrajectoryEvent],
    *,
    sampling_seconds: float = 2.0,
    topology: IntersectionTopology | None = None,
) -> EventFlowSignal:
    if sampling_seconds <= 0:
        raise ValueError("sampling_seconds must be positive")

    topology = topology or DEFAULT_INTERSECTION_TOPOLOGY
    families = tuple(topology.families)
    if not families:
        raise ValueError("topology requires at least one signal family")

    selected = [
        event
        for event in events
        if event.event_type in {EventType.RELEASE, EventType.CROSSING}
        and event.approach in topology.approaches
    ]
    if not selected:
        raise ValueError("no usable RELEASE/CROSSING events")

    start_ms = min(event.timestamp_ms for event in selected)
    end_ms = max(event.timestamp_ms for event in selected)
    n_bins = int(np.floor((end_ms - start_ms) / 1000.0 / sampling_seconds)) + 1
    signal = np.zeros(max(1, n_bins), dtype=float)

    counts = {approach: 0 for approach in topology.approaches}
    for event in selected:
        index = int(
            (event.timestamp_ms - start_ms) / 1000.0 / sampling_seconds
        )
        weight = 1.0 if event.event_type == EventType.RELEASE else 0.5
        family = topology.family_for_approach(event.approach)
        # Preserve the signed two-family representation for the default and
        # custom two-family intersections. With three or more families,
        # avoid inventing an arbitrary sign axis.
        if len(families) == 2 and family == families[1].name:
            weight *= -1.0
        signal[index] += weight
        counts[event.approach] += 1

    return EventFlowSignal(
        signal=signal,
        sampling_seconds=sampling_seconds,
        start_timestamp_ms=start_ms,
        used_events=len(selected),
        release_events=sum(
            event.event_type == EventType.RELEASE for event in selected
        ),
        crossing_events=sum(
            event.event_type == EventType.CROSSING for event in selected
        ),
        counts_by_direction=counts,
    )


def estimate_event_cycle(
    events: Sequence[TrajectoryEvent],
    *,
    estimator: CycleEstimator | None = None,
    sampling_seconds: float = 2.0,
    min_events: int = 8,
    topology: IntersectionTopology | None = None,
) -> EventCycleEstimate:
    flow = build_event_flow_signal(
        events,
        sampling_seconds=sampling_seconds,
        topology=topology,
    )
    if flow.used_events < min_events:
        raise ValueError(
            f"at least {min_events} usable events are required, "
            f"got {flow.used_events}"
        )

    estimator = estimator or CycleEstimator()
    raw_estimate = estimator.estimate(
        flow.signal,
        sampling_seconds=flow.sampling_seconds,
    )
    estimate = CycleEstimate(
        cycle_seconds=raw_estimate.cycle_seconds,
        confidence=round(
            max(0.0, min(1.0, raw_estimate.confidence)),
            4,
        ),
        candidate_periods=raw_estimate.candidate_periods,
    )
    return EventCycleEstimate(estimate=estimate, flow=flow)
