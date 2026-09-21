from __future__ import annotations

from app.core.event_phase_discovery import EventPhase, EventPhaseDiscoveryResult
from app.core.models import EventType, TrajectoryEvent
from app.core.realtime_inference import RealtimeSignalInferenceEngine


def test_realtime_engine_ignores_historical_phase_model_origin():
    origin_ms = 5_000_000
    model = EventPhaseDiscoveryResult(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=(
            EventPhase(1, 0.0, 50.0, ("N", "S"), 0.9, 10, 1, ("N", "S")),
            EventPhase(2, 50.0, 100.0, ("E", "W"), 0.9, 10, 1, ("E", "W")),
        ),
        profiles=(),
        cycle_coverage=1.0,
        overlap=0.0,
        supporting_event_count=20,
        contradictory_event_count=2,
        origin_timestamp_ms=origin_ms,
    )
    engine = RealtimeSignalInferenceEngine(model)
    snapshot = engine.ingest_event(
        TrajectoryEvent(
            EventType.RELEASE,
            origin_ms + 20_000,
            "N",
            "N->S",
            1.0,
            "HIGH",
        )
    )

    assert engine.phase_model.origin_timestamp_ms == 0
    assert snapshot.timestamp_ms == origin_ms + 20_000
    assert snapshot.timestamp_s == 0.0
    assert snapshot.synchronization_status == "WARMUP"
    assert snapshot.phase_id is None
    assert set(snapshot.signal_states.values()) == {"UNKNOWN"}
