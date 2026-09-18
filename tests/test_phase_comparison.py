from __future__ import annotations

from app.core.event_phase_discovery import EventPhaseDiscovery
from app.core.models import EventType, TrajectoryEvent


def _event(event_type, t, approach):
    return TrajectoryEvent(
        event_type=event_type,
        timestamp_ms=int(t * 1000),
        approach=approach,
        movement=f"{approach}->x",
        confidence=1.0,
        quality="HIGH",
    )


def test_phase_result_contains_required_event_metrics():
    events = [
        _event(EventType.RELEASE, 10, "N"),
        _event(EventType.CROSSING, 11, "N"),
        _event(EventType.RELEASE, 70, "E"),
        _event(EventType.CROSSING, 71, "E"),
    ] * 4
    result = EventPhaseDiscovery().discover(events, cycle_seconds=120.0)
    assert result.cycle_coverage == 1.0
    assert result.overlap == 0.0
    for phase in result.phases:
        assert phase.phase_start != phase.phase_end
        assert phase.active_approaches
        assert 0.0 <= phase.confidence <= 1.0
        assert phase.supporting_event_count >= 0
        assert phase.contradictory_event_count >= 0
