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
from app.core.realtime_phase_sync import (
    RealtimePhaseSynchronizer,
    RealtimePhaseTemplate,
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


def test_stream_starts_in_warmup_without_realtime_origin():
    engine = RealtimeSignalInferenceEngine(phase_model())
    first = engine.ingest_event(event(EventType.RELEASE, 10, "N"))
    second = engine.ingest_event(event(EventType.RELEASE, 20, "S"))

    assert first.synchronization_status == "WARMUP"
    assert second.synchronization_status == "WARMUP"
    assert first.phase_id is None
    assert second.cycle_position_s is None
    assert set(second.signal_states.values()) == {SignalState.UNKNOWN.value}
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
    engine = RealtimeSignalInferenceEngine(
        phase_model(),
        recent_window_s=12.0,
        event_origin_ms=0,
    )
    latest = engine.ingest_event(event(EventType.RELEASE, 20, "N"))
    earlier = engine.ingest_event(event(EventType.RELEASE, 15, "S"))
    assert latest.timestamp_ms == 20_000
    assert earlier.timestamp_ms == 20_000
    assert earlier.cycle_position_s == 20.0
    assert engine.buffer_event_count == 2


def test_explicit_realtime_origin_can_skip_warmup_for_compatibility():
    engine = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
    )
    snapshot = engine.ingest_event(event(EventType.RELEASE, 10, "N"))

    assert snapshot.synchronization_status == "SYNCHRONIZED"
    assert snapshot.phase_id == 1
    assert snapshot.signal_states["N"] == SignalState.GREEN.value
    assert snapshot.phase_offset_s == 0.0


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

    engine = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
    )
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



def _stream_event(timestamp_s, approach, event_type=EventType.RELEASE):
    return event(event_type, timestamp_s, approach)


def _events_for_known_offset(offset_s):
    desired = (
        (4.0, "N"),
        (18.0, "S"),
        (36.0, "N"),
        (44.0, "E"),
        (62.0, "W"),
        (82.0, "E"),
        (96.0, "W"),
        (8.0, "S"),
    )
    result = []
    base_cycle = 20
    for index, (position, approach) in enumerate(desired):
        cycle = base_cycle + index
        timestamp_s = (
            cycle * 100.0
            + ((position - offset_s) % 100.0)
        )
        result.append(_stream_event(timestamp_s, approach))
    return result


def _circular_error(left, right, cycle=100.0):
    delta = abs(left - right) % cycle
    return min(delta, cycle - delta)


def test_phase_synchronizer_recovers_arbitrary_realtime_offset():
    template = RealtimePhaseTemplate.from_phase_model(phase_model())
    synchronizer = RealtimePhaseSynchronizer(
        template,
        min_evidence_events=6,
        resolution_seconds=2.0,
    )
    true_offset = 26.0

    state = synchronizer.ingest_many(
        _events_for_known_offset(true_offset)
    )

    assert state.status == "SYNCHRONIZED"
    assert state.offset_seconds is not None
    assert _circular_error(state.offset_seconds, true_offset) <= 4.0
    assert state.confidence >= 0.8


def test_realtime_engine_warms_up_then_synchronizes_without_reference_origin():
    engine = RealtimeSignalInferenceEngine(
        phase_model(),
        synchronization_min_events=6,
    )
    source = _events_for_known_offset(26.0)

    for item in source[:5]:
        snapshot = engine.ingest_event(item)
        assert snapshot.synchronization_status == "WARMUP"
        assert snapshot.phase_id is None
        assert set(snapshot.signal_states.values()) == {"UNKNOWN"}

    snapshot = None
    for item in source[5:]:
        snapshot = engine.ingest_event(item)

    assert snapshot is not None
    assert snapshot.synchronization_status == "SYNCHRONIZED"
    assert snapshot.phase_offset_s is not None
    assert _circular_error(snapshot.phase_offset_s, 26.0) <= 4.0
    assert snapshot.phase_id is not None
    assert snapshot.cycle_position_s is not None


def test_synchronization_has_no_lookahead():
    prefix = _events_for_known_offset(26.0)[:5]
    first = RealtimeSignalInferenceEngine(
        phase_model(),
        synchronization_min_events=6,
    )
    second = RealtimeSignalInferenceEngine(
        phase_model(),
        synchronization_min_events=6,
    )

    first_snapshots = [
        first.ingest_event(item).to_dict()
        for item in prefix
    ]
    second_snapshots = [
        second.ingest_event(item).to_dict()
        for item in prefix
    ]

    assert first_snapshots == second_snapshots
    assert first_snapshots[-1]["synchronization_status"] == "WARMUP"

    for item in _events_for_known_offset(26.0)[5:]:
        future_snapshot = first.ingest_event(item)

    assert future_snapshot.synchronization_status == "SYNCHRONIZED"
    assert second.snapshot().synchronization_status == "WARMUP"


def test_phase_template_does_not_keep_historical_origin():
    historical = phase_model()
    object.__setattr__(historical, "origin_timestamp_ms", 987654321000)

    template = RealtimePhaseTemplate.from_phase_model(historical)

    assert "origin_timestamp_ms" not in template.to_dict()
    assert template.to_phase_model().origin_timestamp_ms == 0



def staggered_phase_model():
    return EventPhaseDiscoveryResult(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=(
            EventPhase(1, 0.0, 20.0, ("N",), 0.9, 20, 1, ("N",)),
            EventPhase(
                2,
                20.0,
                50.0,
                ("N", "S"),
                0.9,
                30,
                1,
                ("N", "S"),
            ),
            EventPhase(
                3,
                55.0,
                100.0,
                ("E", "W"),
                0.9,
                40,
                1,
                ("E", "W"),
            ),
        ),
        profiles=(),
        cycle_coverage=0.95,
        overlap=0.0,
        supporting_event_count=90,
        contradictory_event_count=3,
    )


def test_realtime_template_supports_repeated_approach_across_stages():
    template = RealtimePhaseTemplate.from_phase_model(
        staggered_phase_model()
    )

    assert template.phase_at(10.0).active_approaches == ("N",)
    assert template.phase_at(30.0).active_approaches == ("N", "S")
    assert template.phase_at(52.0) is None
    assert template.phase_at(70.0).active_approaches == ("E", "W")
    assert template.group_for_approach("N") == ("NS",)
    assert template.group_for_approach("S") == ("NS",)
    assert template.group_for_approach("E") == ("EW",)


def test_phase_synchronizer_handles_staggered_stage_template():
    template = RealtimePhaseTemplate.from_phase_model(
        staggered_phase_model()
    )
    synchronizer = RealtimePhaseSynchronizer(
        template,
        min_evidence_events=6,
        resolution_seconds=2.0,
    )
    true_offset = 18.0
    desired = (
        (10.0, "N"),
        (34.0, "N"),
        (36.0, "S"),
        (76.0, "E"),
        (78.0, "W"),
        (12.0, "N"),
        (38.0, "S"),
        (80.0, "E"),
    )
    events = []
    for index, (position, approach) in enumerate(desired):
        timestamp_s = (
            (30 + index) * 100.0
            + ((position - true_offset) % 100.0)
        )
        events.append(
            _stream_event(
                timestamp_s,
                approach,
            )
        )

    state = synchronizer.ingest_many(events)

    assert state.status == "SYNCHRONIZED"
    assert state.offset_seconds is not None
    assert _circular_error(
        state.offset_seconds,
        true_offset,
    ) <= 4.0
