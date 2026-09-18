from __future__ import annotations

from app.core.event_phase_discovery import EventPhase, EventPhaseDiscoveryResult
from app.core.models import EventType, TrajectoryEvent
from app.core.review_log import review_summary


def test_review_summary_flags_non_overlapping_phase_model_as_valid():
    events = [
        TrajectoryEvent(EventType.RELEASE, 5000, "N", "N->_W", 1.0, "HIGH"),
        TrajectoryEvent(EventType.RELEASE, 6000, "S", "S->_N", 1.0, "HIGH"),
        TrajectoryEvent(EventType.RELEASE, 55000, "E", "E->_W", 1.0, "HIGH"),
        TrajectoryEvent(EventType.RELEASE, 56000, "W", "W->_E", 1.0, "HIGH"),
    ]
    model = EventPhaseDiscoveryResult(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=(
            EventPhase(1, 0.0, 40.0, ("N", "S"), 0.8, 2, 0, ("N", "S")),
            EventPhase(2, 50.0, 90.0, ("E", "W"), 0.8, 2, 0, ("E", "W")),
        ),
        profiles=(),
        cycle_coverage=0.8,
        overlap=0.0,
        supporting_event_count=4,
        contradictory_event_count=0,
        origin_timestamp_ms=5000,
    )
    timeline = [
        {
            "timestamp_s": 10.0,
            "cycle_phase_s": 10.0,
            "approaches": {a: {"state": "GREEN" if a in ("N", "S") else "RED"} for a in ("N", "S", "E", "W")},
        },
        {
            "timestamp_s": 60.0,
            "cycle_phase_s": 60.0,
            "approaches": {a: {"state": "GREEN" if a in ("E", "W") else "RED"} for a in ("N", "S", "E", "W")},
        },
    ]
    summary = review_summary(events, model, timeline, cycle_confidence=0.8)
    assert summary["status"] in {"PASS", "WARN"}
    assert summary["metrics"]["phase_overlap_ratio"] == 0.0
