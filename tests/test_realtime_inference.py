from __future__ import annotations

import asyncio

from app.api.realtime import (
    PhasePayload,
    RealtimeEventPayload,
    RealtimeInferenceRequest,
    infer_realtime,
    registry,
)
from app.core.event_phase_discovery import EventPhase, EventPhaseDiscoveryResult
from app.core.models import EventType, TrajectoryEvent
from app.core.realtime_inference import (
    DuplicateEventError,
    RealtimeSignalInferenceEngine,
)
from app.core.signal_state_estimator import SignalState, SignalStateEstimator


def event(event_type, timestamp_s, approach, confidence=1.0):
    return TrajectoryEvent(
        event_type=event_type,
        timestamp_ms=int(timestamp_s * 1000),
        approach=approach,
        movement=f"{approach}->x",
        confidence=confidence,
        quality="HIGH",
    )


def phase_model():
    return EventPhaseDiscoveryResult(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=(
            EventPhase(1, 0.0, 40.0, ("N", "S"), 0.9, 20, 2, ("N", "S")),
            EventPhase(2, 40.0, 100.0, ("E", "W"), 0.9, 20, 2, ("E", "W")),
        ),
        profiles=(),
        cycle_coverage=1.0,
        overlap=0.0,
        supporting_event_count=40,
        contradictory_event_count=4,
    )


def phase_payload():
    return PhasePayload(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=[phase.to_dict() for phase in phase_model().phases],
    )


def states(snapshot):
    return snapshot.signal_states


def test_sequence_of_events_updates_incrementally():
    engine = RealtimeSignalInferenceEngine(phase_model())
    first = engine.ingest_event(event(EventType.RELEASE, 10, "N"))
    second = engine.ingest_event(event(EventType.RELEASE, 20, "S"))
    assert first.phase_id == 1
    assert second.phase_id == 1
    assert second.cycle_position_s == 20.0
    assert states(second)["N"] == SignalState.GREEN.value
    assert engine.buffer_event_count == 2


def test_duplicate_event_is_idempotent():
    engine = RealtimeSignalInferenceEngine(phase_model())
    source = event(EventType.RELEASE, 10, "N")
    first = engine.ingest_event(source, event_id="evt-1")
    duplicate = engine.ingest_event(source, event_id="evt-1")
    assert duplicate.duplicate is True
    assert duplicate.to_dict() == first.to_dict() | {"duplicate": True}
    assert engine.buffer_event_count == 1


def test_duplicate_without_explicit_id_is_idempotent():
    engine = RealtimeSignalInferenceEngine(phase_model())
    source = event(EventType.RELEASE, 10, "N")
    engine.ingest_event(source)
    duplicate = engine.ingest_event(source)
    assert duplicate.duplicate is True
    assert engine.buffer_event_count == 1


def test_reused_id_with_different_payload_is_rejected():
    engine = RealtimeSignalInferenceEngine(phase_model())
    engine.ingest_event(event(EventType.RELEASE, 10, "N"), event_id="evt-1")
    try:
        engine.ingest_event(event(EventType.RELEASE, 11, "N"), event_id="evt-1")
    except DuplicateEventError:
        pass
    else:
        raise AssertionError("expected DuplicateEventError")


def test_out_of_order_event_is_accepted_without_moving_current_time_backwards():
    engine = RealtimeSignalInferenceEngine(phase_model(), recent_window_s=12.0)
    latest = engine.ingest_event(event(EventType.RELEASE, 20, "N"))
    earlier = engine.ingest_event(event(EventType.RELEASE, 15, "S"))
    assert latest.timestamp_ms == 20_000
    assert earlier.timestamp_ms == 20_000
    assert earlier.cycle_position_s == 20.0
    assert engine.buffer_event_count == 2


def test_missing_events_keep_phase_structure_but_reduce_evidence():
    engine = RealtimeSignalInferenceEngine(phase_model())
    snapshot = engine.ingest_event(event(EventType.RELEASE, 10, "N"))
    assert snapshot.phase_id == 1
    assert snapshot.signal_states["N"] == SignalState.GREEN.value
    assert snapshot.traffic_evidence_confidence > 0


def test_rolling_buffer_drops_old_events():
    engine = RealtimeSignalInferenceEngine(phase_model(), recent_window_s=5.0)
    engine.ingest_event(event(EventType.RELEASE, 1, "N"))
    snapshot = engine.ingest_event(event(EventType.RELEASE, 10, "N"))
    assert snapshot.buffer_event_count == 1


def test_long_stream_keeps_bounded_memory():
    engine = RealtimeSignalInferenceEngine(phase_model(), recent_window_s=12.0)
    snapshot = None
    for timestamp in range(1000):
        snapshot = engine.ingest_event(
            event(
                EventType.RELEASE,
                timestamp / 10.0,
                "N" if timestamp % 2 == 0 else "E",
            )
        )
    assert snapshot is not None
    assert engine.current_timestamp_ms == 99_900
    assert engine.buffer_event_count <= 125


def test_realtime_matches_batch_on_same_event_set():
    events = [
        event(EventType.RELEASE, 10, "N"),
        event(EventType.CROSSING, 11, "N"),
        event(EventType.RELEASE, 15, "S"),
        event(EventType.RELEASE, 19, "E"),
        event(EventType.RELEASE, 20, "N"),
    ]
    batch = SignalStateEstimator(phase_model()).estimate(20.0, events)

    engine = RealtimeSignalInferenceEngine(phase_model())
    realtime = None
    for item in events:
        realtime = engine.ingest_event(item)

    assert realtime is not None
    assert realtime.phase_id == batch.phase_id
    assert realtime.signal_states == {
        state.approach: state.state.value
        for state in batch.approaches
    }
    assert realtime.phase_confidence == batch.phase_confidence
    assert (
        realtime.traffic_evidence_confidence
        == batch.traffic_evidence_confidence
    )


def test_endpoint_is_idempotent_for_duplicate_event():
    stream_id = "test-realtime-idempotent"
    registry.reset(stream_id)
    payload = RealtimeInferenceRequest(
        stream_id=stream_id,
        event_id="evt-1",
        event=RealtimeEventPayload(
            event_type=EventType.RELEASE,
            timestamp_ms=10_000,
            approach="N",
            movement="N->x",
            confidence=1.0,
            quality="HIGH",
        ),
        phase_model=phase_payload(),
    )
    first = asyncio.run(infer_realtime(payload))
    duplicate = asyncio.run(infer_realtime(payload))
    assert first["phase_id"] == duplicate["phase_id"]
    assert first["signal_states"] == duplicate["signal_states"]
    assert duplicate["duplicate"] is True
    registry.reset(stream_id)
