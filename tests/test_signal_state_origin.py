from __future__ import annotations

from app.core.event_phase_discovery import EventPhase, EventPhaseDiscoveryResult
from app.core.models import EventType, TrajectoryEvent
from app.core.signal_state_estimator import SignalStateEstimator


def test_signal_estimator_uses_phase_model_origin_by_default():
    origin_ms = 1_000_000
    model = EventPhaseDiscoveryResult(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=(
            EventPhase(1, 0.0, 40.0, ("N", "S"), 0.9, 10, 1, ("N", "S")),
            EventPhase(2, 40.0, 100.0, ("E", "W"), 0.9, 10, 1, ("E", "W")),
        ),
        profiles=(),
        cycle_coverage=1.0,
        overlap=0.0,
        supporting_event_count=20,
        contradictory_event_count=2,
        origin_timestamp_ms=origin_ms,
    )
    result = SignalStateEstimator(model).estimate(
        20.0,
        [
            TrajectoryEvent(
                EventType.RELEASE,
                origin_ms + 10_000,
                "N",
                "N->x",
                1.0,
                "HIGH",
            )
        ],
    )
    n_state = {item.approach: item for item in result.approaches}["N"]
    assert n_state.supporting_event_count == 1
