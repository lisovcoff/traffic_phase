from __future__ import annotations

import pytest

import asyncio

from app.api.realtime import (
    PhasePayload,
    RealtimeEventPayload,
    _build_phase_model,
    RealtimeInferenceRequest,
    infer_realtime,
    registry,
)
from app.core.event_phase_discovery import (
    EventPhase,
    EventPhaseDiscoveryResult,
    MovementSignalStage,
)
from app.core.intersection_topology import (
    IntersectionTopology,
    SignalFamily,
)
from app.core.models import EventType, TrajectoryEvent
from app.core.realtime_inference import (
    DuplicateEventError,
    RealtimeSignalInferenceEngine,
)
from app.core.realtime_phase_sync import (
    RealtimePhaseSynchronizer,
    RealtimePhaseTemplate,
)
from app.core.signal_state_estimator import (
    DEFAULT_RED_YELLOW_DURATION_SECONDS,
    DEFAULT_YELLOW_DURATION_SECONDS,
    SignalState,
    SignalStateEstimator,
)


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



def test_realtime_template_carries_movement_stages_on_same_cycle_clock():
    model = staggered_phase_model()
    object.__setattr__(
        model,
        "movement_stages",
        (
            MovementSignalStage(
                movement_stage_id=1,
                approach="N",
                movement="N->_E",
                phase_start=0.0,
                phase_end=20.0,
                confidence=0.95,
                repeatability=1.0,
                stability=0.97,
                supporting_event_count=120,
                observed_cycle_count=20,
            ),
            MovementSignalStage(
                movement_stage_id=2,
                approach="E",
                movement="E->_N",
                phase_start=55.0,
                phase_end=70.0,
                confidence=0.91,
                repeatability=0.9,
                stability=0.94,
                supporting_event_count=90,
                observed_cycle_count=18,
            ),
        ),
    )

    template = RealtimePhaseTemplate.from_phase_model(model)

    assert [
        item.movement
        for item in template.active_movements_at(10.0)
    ] == ["N->_E"]
    assert [
        item.movement
        for item in template.active_movements_at(60.0)
    ] == ["E->_N"]
    assert template.active_movements_at(30.0) == ()
    assert template.to_phase_model().movement_stages == model.movement_stages


def test_movement_stages_do_not_change_main_realtime_synchronization():
    base = staggered_phase_model()
    with_movement = staggered_phase_model()
    object.__setattr__(
        with_movement,
        "movement_stages",
        (
            MovementSignalStage(
                movement_stage_id=1,
                approach="N",
                movement="N->_E",
                phase_start=0.0,
                phase_end=20.0,
                confidence=0.95,
                repeatability=1.0,
                stability=0.97,
                supporting_event_count=120,
                observed_cycle_count=20,
            ),
        ),
    )
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
    true_offset = 18.0
    for index, (position, approach) in enumerate(desired):
        timestamp_s = (
            (40 + index) * 100.0
            + ((position - true_offset) % 100.0)
        )
        events.append(_stream_event(timestamp_s, approach))

    base_sync = RealtimePhaseSynchronizer(
        RealtimePhaseTemplate.from_phase_model(base),
        min_evidence_events=6,
        resolution_seconds=2.0,
    ).ingest_many(events)
    movement_sync = RealtimePhaseSynchronizer(
        RealtimePhaseTemplate.from_phase_model(with_movement),
        min_evidence_events=6,
        resolution_seconds=2.0,
    ).ingest_many(events)

    assert base_sync.status == "SYNCHRONIZED"
    assert movement_sync.status == base_sync.status
    assert movement_sync.offset_seconds == base_sync.offset_seconds
    assert movement_sync.confidence == base_sync.confidence


def test_realtime_payload_preserves_movement_stages():
    payload = PhasePayload(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=[phase.to_dict() for phase in staggered_phase_model().phases],
        movement_stages=[
            {
                "movement_stage_id": 1,
                "approach": "N",
                "movement": "N->_E",
                "phase_start": 0.0,
                "phase_end": 20.0,
                "confidence": 0.95,
                "repeatability": 1.0,
                "stability": 0.97,
                "supporting_event_count": 120,
                "observed_cycle_count": 20,
            }
        ],
    )

    model = _build_phase_model(payload)

    assert len(model.movement_stages) == 1
    assert model.movement_stages[0].movement == "N->_E"
    assert model.origin_timestamp_ms == 0



def test_adaptive_override_ignores_normal_template_aligned_flow():
    engine = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
    )

    snapshots = [
        engine.ingest_event(
            event(EventType.RELEASE, timestamp, approach)
        )
        for timestamp, approach in (
            (44.0, "E"),
            (46.0, "W"),
            (48.0, "E"),
            (50.0, "W"),
        )
    ]

    assert all(
        snapshot.adaptive_mode == "NORMAL"
        for snapshot in snapshots
    )
    assert snapshots[-1].effective_axis == "EW"
    assert snapshots[-1].template_disagreement is False
    assert snapshots[-1].signal_states["E"] == "GREEN"


def test_single_late_release_does_not_trigger_live_override():
    engine = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
    )

    snapshot = engine.ingest_event(
        event(EventType.RELEASE, 46.0, "N")
    )

    assert snapshot.adaptive_mode == "NORMAL"
    assert snapshot.template_expected_axis == "EW"
    assert snapshot.template_disagreement is False


def test_persistent_release_after_expected_transition_triggers_live_override():
    engine = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
    )

    snapshots = [
        engine.ingest_event(
            event(EventType.RELEASE, timestamp, "N")
        )
        for timestamp in (44.0, 46.0, 48.0, 50.0)
    ]
    snapshot = snapshots[-1]

    assert snapshots[1].adaptive_mode == "SUSPECT"
    assert snapshot.adaptive_mode == "LIVE_OVERRIDE"
    assert snapshot.template_expected_axis == "EW"
    assert snapshot.effective_axis == "NS"
    assert snapshot.template_disagreement is True
    assert snapshot.adaptive_reason == (
        "persistent_release_outside_template"
    )
    assert snapshot.signal_states["N"] == "GREEN"
    assert snapshot.signal_states["S"] == "UNKNOWN"
    assert snapshot.signal_states["E"] == "RED"
    assert snapshot.signal_states["W"] == "RED"
    assert snapshot.template_signal_states["N"] == "RED"
    assert snapshot.active_movements == []
    # The event that first raised suspicion is scored, then synchronization
    # evidence is frozen while SUSPECT/LIVE_OVERRIDE is active.
    assert snapshot.synchronization_evidence_count == 2


def test_live_override_recovers_when_template_axis_has_persistent_release():
    engine = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
    )
    for timestamp in (44.0, 46.0, 48.0, 50.0):
        override = engine.ingest_event(
            event(EventType.RELEASE, timestamp, "N")
        )

    assert override.adaptive_mode == "LIVE_OVERRIDE"

    recovered = None
    for timestamp in (54.0, 57.0, 60.0):
        recovered = engine.ingest_event(
            event(EventType.RELEASE, timestamp, "E")
        )

    assert recovered is not None
    assert recovered.adaptive_mode == "NORMAL"
    assert recovered.template_disagreement is False
    assert recovered.effective_axis == "EW"
    assert recovered.signal_states["E"] == "GREEN"
    assert recovered.synchronization_status == "SYNCHRONIZED"



def test_realtime_defaults_use_physical_transition_durations():
    yellow_engine = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
    )
    yellow = yellow_engine.ingest_event(
        event(EventType.CROSSING, 37.0, "N")
    )

    red_yellow_engine = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
    )
    red_yellow = red_yellow_engine.ingest_event(
        event(EventType.RELEASE, 40.0, "E")
    )
    green = red_yellow_engine.ingest_event(
        event(EventType.RELEASE, 42.0, "E")
    )

    assert DEFAULT_YELLOW_DURATION_SECONDS == 3.0
    assert DEFAULT_RED_YELLOW_DURATION_SECONDS == 2.0
    assert yellow.signal_states["N"] == SignalState.YELLOW.value
    assert red_yellow.signal_states["E"] == SignalState.RED_YELLOW.value
    assert green.signal_states["E"] == SignalState.GREEN.value


def test_realtime_api_defaults_keep_yellow_and_red_yellow_separate():
    payload = RealtimeInferenceRequest(
        stream_id="timing-defaults",
        event=RealtimeEventPayload(
            event_type=EventType.RELEASE,
            timestamp_ms=10_000,
            approach="N",
            movement="N->x",
        ),
        phase_model=phase_payload(),
    )
    assert payload.yellow_duration_seconds == 3.0
    assert payload.red_yellow_duration_seconds == 2.0



def test_custom_topology_drives_sync_family_names_and_adaptive_override():
    topology = IntersectionTopology(
        families=(
            SignalFamily("MAIN", ("N", "S")),
            SignalFamily("CROSS", ("E", "W")),
        ),
        family_conflicts=(("MAIN", "CROSS"),),
    )
    template = RealtimePhaseTemplate.from_phase_model(
        phase_model(),
        topology=topology,
    )
    assert template.group_for_approach("N") == ("MAIN",)
    assert template.group_for_approach("E") == ("CROSS",)

    engine = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
        topology=topology,
    )
    snapshots = [
        engine.ingest_event(
            event(EventType.RELEASE, timestamp, "N")
        )
        for timestamp in (44.0, 46.0, 48.0, 50.0)
    ]
    snapshot = snapshots[-1]

    assert snapshot.adaptive_mode == "LIVE_OVERRIDE"
    assert snapshot.template_expected_axis == "CROSS"
    assert snapshot.effective_axis == "MAIN"
    assert snapshot.signal_states["N"] == "GREEN"
    assert snapshot.signal_states["E"] == "RED"


def test_realtime_phase_payload_accepts_custom_conflict_topology():
    payload = PhasePayload(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=[phase.to_dict() for phase in phase_model().phases],
        topology={
            "families": [
                {"name": "MAIN", "approaches": ["N", "S"]},
                {"name": "CROSS", "approaches": ["E", "W"]},
            ],
            "family_conflicts": [["MAIN", "CROSS"]],
            "movement_compatibilities": [["N->x", "E->x"]],
        },
    )
    topology = IntersectionTopology.from_dict(payload.topology)

    assert topology.family_for_approach("S") == "MAIN"
    assert topology.family_for_approach("W") == "CROSS"
    assert not topology.movements_conflict(
        "N->x",
        "E->x",
        left_approach="N",
        right_approach="E",
    )



def test_template_compatibility_rejects_persistent_two_family_mismatch():
    engine = RealtimeSignalInferenceEngine(
        phase_model(),
    )
    snapshot = None
    for timestamp in (10.0, 20.0, 30.0, 40.0, 50.0, 60.0):
        snapshot = engine.ingest_event(
            event(EventType.RELEASE, timestamp, "N")
        )
        snapshot = engine.ingest_event(
            event(EventType.RELEASE, timestamp, "E")
        )

    assert snapshot is not None
    assert snapshot.synchronization_status == "WARMUP"
    assert snapshot.synchronization_match_ratio <= 0.55
    assert snapshot.template_compatibility == "INCOMPATIBLE"
    assert snapshot.instant_unknown_rate == 1.0
    assert set(snapshot.unknown_reasons.values()) == {
        "template_incompatible"
    }


def test_realtime_rejects_approach_outside_configured_topology():
    engine = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
    )

    with pytest.raises(ValueError, match="configured intersection topology"):
        engine.ingest_event(
            event(EventType.RELEASE, 10.0, "X")
        )


def test_emergency_green_extension_is_observed_then_recovers():
    engine = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
    )

    snapshot = None
    for timestamp in (44.0, 46.0, 48.0, 50.0):
        snapshot = engine.ingest_event(
            event(EventType.RELEASE, timestamp, "N")
        )

    assert snapshot is not None
    assert snapshot.adaptive_mode == "LIVE_OVERRIDE"
    assert snapshot.template_compatibility == "COMPATIBLE"
    assert snapshot.signal_states["N"] == "GREEN"
    assert snapshot.signal_states["E"] == "RED"
    assert snapshot.template_deviation_seconds == 10.0

    recovered = None
    for timestamp in (54.0, 57.0, 60.0):
        recovered = engine.ingest_event(
            event(EventType.RELEASE, timestamp, "E")
        )

    assert recovered is not None
    assert recovered.adaptive_mode == "NORMAL"
    assert recovered.template_compatibility == "COMPATIBLE"
    assert recovered.template_deviation_seconds is None
    assert recovered.signal_states["E"] == "GREEN"
