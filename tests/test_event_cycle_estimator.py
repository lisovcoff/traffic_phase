from __future__ import annotations

import numpy as np

from app.core.cycle_estimator import CycleEstimator
from app.core.event_cycle_estimator import (
    build_event_flow_signal,
    estimate_event_cycle,
)
from app.core.models import EventType, TrajectoryEvent


def _event(event_type, timestamp_ms, approach):
    return TrajectoryEvent(
        event_type=event_type,
        timestamp_ms=timestamp_ms,
        approach=approach,
        movement=f"{approach}->x",
        confidence=1.0,
        quality="HIGH",
    )


def _synthetic_events(period_s=120.0, cycles=10):
    events = []
    for cycle in range(cycles):
        base = int(cycle * period_s * 1000)
        for offset, approach in ((10, "N"), (25, "S"), (70, "E"), (85, "W")):
            events.append(
                _event(EventType.RELEASE, base + offset * 1000, approach)
            )
            events.append(
                _event(EventType.CROSSING, base + (offset + 1) * 1000, approach)
            )
    return events


def test_event_flow_preserves_directional_contrast():
    events = [
        _event(EventType.RELEASE, 0, "N"),
        _event(EventType.CROSSING, 1000, "S"),
        _event(EventType.RELEASE, 4000, "E"),
        _event(EventType.CROSSING, 5000, "W"),
    ]
    flow = build_event_flow_signal(events, sampling_seconds=1.0)
    assert flow.used_events == 4
    assert flow.release_events == 2
    assert flow.crossing_events == 2
    assert flow.counts_by_direction == {"N": 1, "S": 1, "E": 1, "W": 1}
    assert flow.signal[0] > 0
    assert flow.signal[4] < 0


def test_event_cycle_recovers_synthetic_period():
    estimate = estimate_event_cycle(
        _synthetic_events(),
        estimator=CycleEstimator(),
        sampling_seconds=2.0,
    )
    assert 112.0 <= estimate.estimate.cycle_seconds <= 128.0
    assert estimate.flow.used_events == 80
    assert estimate.estimate.candidate_periods
    assert 0.0 <= estimate.estimate.confidence <= 1.0


def test_event_cycle_requires_enough_events():
    events = [
        _event(EventType.RELEASE, index * 1000, "N")
        for index in range(3)
    ]
    try:
        estimate_event_cycle(events, min_events=8)
    except ValueError as exc:
        assert "at least 8" in str(exc)
    else:
        raise AssertionError("expected ValueError")
