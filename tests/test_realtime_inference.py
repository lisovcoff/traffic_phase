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
from app.core.adaptive_realtime import (
    AdaptiveRealtimeMode,
    AdaptiveRealtimeOverride,
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


def movement_event(
    event_type,
    timestamp_s,
    approach,
    movement,
    confidence=1.0,
):
    return TrajectoryEvent(
        event_type=event_type,
        timestamp_ms=int(timestamp_s * 1000),
        approach=approach,
        movement=movement,
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
    assert snapshot.template_signal_states["N"] == "UNKNOWN"
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
        event(EventType.RELEASE, 35.0, "N")
    )
    yellow = yellow_engine.ingest_event(
        event(EventType.RELEASE, 37.0, "N")
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
    assert snapshot.synchronization_status == "INCOMPATIBLE"
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
    assert snapshot.effective_movement_states is not None
    assert snapshot.effective_movement_states["N->x"]["effective_state"] == "GREEN"
    assert snapshot.effective_movement_states["N->x"]["evidence_weight"] >= 2.0
    assert (
        snapshot.effective_movement_states["N->x"]["reason"]
        == "live_override_movement"
    )
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


def test_partial_trajectory_ingestion_never_uses_future_detections():
    engine = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
    )
    partial = {
        "id": 501,
        "zone_in": "N",
        "zone_out": "_S",
        "movement": "N->_S",
        "detections": [
            {"millis": 0, "lat": 55.0, "lng": 61.0, "zone": "N"},
            {"millis": 1000, "lat": 55.0, "lng": 61.0, "zone": "N"},
            {"millis": 2000, "lat": 55.00001, "lng": 61.0, "zone": "N"},
        ],
    }
    early = engine.ingest_trajectory(partial)

    assert early.timestamp_ms == 2000
    assert all(
        event.event_type is not EventType.CROSSING
        for event in engine._events.values()
    )

    completed = dict(partial)
    completed["detections"] = [
        *partial["detections"],
        {"millis": 3000, "lat": 55.00002, "lng": 61.0, "zone": None},
    ]
    late = engine.ingest_trajectory(completed)

    assert late.timestamp_ms == 3000
    assert any(
        event.event_type is EventType.CROSSING
        for event in engine._events.values()
    )


def test_causal_equivalence_of_incremental_trajectory_prefixes():
    prefix = {
        "id": 777,
        "zone_in": "N",
        "zone_out": "_S",
        "movement": "N->_S",
        "detections": [
            {"millis": 0, "lat": 55.0, "lng": 61.0, "zone": "N"},
            {"millis": 1000, "lat": 55.0, "lng": 61.0, "zone": "N"},
            {"millis": 2000, "lat": 55.00001, "lng": 61.0, "zone": "N"},
        ],
    }
    future = {
        **prefix,
        "detections": [
            *prefix["detections"],
            {"millis": 3000, "lat": 55.00002, "lng": 61.0, "zone": None},
            {"millis": 4000, "lat": 55.00003, "lng": 61.0, "zone": "_S"},
        ],
    }

    incremental = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
    )
    reference = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
    )

    incremental_snapshot = incremental.ingest_trajectory(prefix)
    reference_snapshot = reference.ingest_trajectory(prefix)

    assert incremental_snapshot.to_dict() == reference_snapshot.to_dict()
    assert incremental_snapshot.timestamp_ms == 2000
    assert incremental_snapshot.synchronization_evidence_count == (
        reference_snapshot.synchronization_evidence_count
    )

    incremental.ingest_trajectory(future)
    assert incremental.current_timestamp_ms == 4000
    assert any(
        event.event_type is EventType.CROSSING
        for event in incremental._events.values()
    )
    assert reference.current_timestamp_ms == 2000


def test_out_of_order_partial_detections_are_accepted_causally():
    engine = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
        recent_window_s=10.0,
    )
    first = {
        "id": 808,
        "zone_in": "N",
        "zone_out": "_S",
        "movement": "N->_S",
        "detections": [
            {"millis": 0, "lat": 55.0, "lng": 61.0, "zone": "N"},
            {"millis": 3000, "lat": 55.00001, "lng": 61.0, "zone": "N"},
            {"millis": 4000, "lat": 55.00002, "lng": 61.0, "zone": None},
        ],
    }
    engine.ingest_trajectory(first)

    late = {
        **first,
        "detections": [
            {"millis": 1000, "lat": 55.0, "lng": 61.0, "zone": "N"},
            {"millis": 2000, "lat": 55.0, "lng": 61.0, "zone": "N"},
        ],
    }
    snapshot = engine.ingest_trajectory(late)

    assert snapshot.timestamp_ms == 4000
    assert engine.active_trajectory_count == 1
    assert engine.current_timestamp_ms == 4000


def test_duplicate_trajectory_snapshot_is_idempotent():
    engine = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
    )
    payload = {
        "id": 909,
        "zone_in": "N",
        "zone_out": "_S",
        "movement": "N->_S",
        "detections": [
            {"millis": 0, "lat": 55.0, "lng": 61.0, "zone": "N"},
            {"millis": 1000, "lat": 55.00001, "lng": 61.0, "zone": None},
        ],
    }

    first = engine.ingest_trajectory(payload)
    second = engine.ingest_trajectory(payload)

    assert first.duplicate is False
    assert second.duplicate is True
    assert second.timestamp_ms == first.timestamp_ms
    assert engine.buffer_event_count == 2


def test_topology_rejects_unknown_trajectory_approach():
    engine = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
    )
    payload = {
        "id": 1001,
        "zone_in": "X",
        "zone_out": "_S",
        "movement": "X->_S",
        "detections": [
            {"millis": 1000, "lat": 55.0, "lng": 61.0, "zone": "X"},
        ],
    }

    with pytest.raises(ValueError, match="configured intersection topology"):
        engine.ingest_trajectory(payload)


def test_stale_out_of_order_event_does_not_reenter_realtime_window():
    engine = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
        recent_window_s=5.0,
    )
    engine.ingest_event(event(EventType.RELEASE, 20, "N"))
    before = engine.synchronization.evidence_count

    snapshot = engine.ingest_event(event(EventType.RELEASE, 1, "S"))

    assert snapshot.timestamp_ms == 20_000
    assert engine.current_timestamp_ms == 20_000
    assert engine.synchronization.evidence_count == before
    assert engine.buffer_event_count == 1


def test_realtime_idempotency_and_trajectory_buffers_are_bounded():
    engine = RealtimeSignalInferenceEngine(
        phase_model(),
        event_origin_ms=0,
        recent_window_s=30.0,
        max_active_trajectories=2,
        max_idempotency_entries=3,
    )

    for index in range(6):
        engine.ingest_trajectory(
            {
                "id": index,
                "zone_in": "N",
                "zone_out": "_S",
                "movement": "N->_S",
                "detections": [
                    {
                        "millis": index * 1000,
                        "lat": 55.0,
                        "lng": 61.0,
                        "zone": "N",
                    },
                ],
            }
        )

    assert engine.active_trajectory_count <= 2
    assert engine.idempotency_entry_count <= 3


def test_synthetic_realtime_ingestion_latency_stays_linear_and_bounded():
    import time

    engine = RealtimeSignalInferenceEngine(
        phase_model(),
        recent_window_s=12.0,
    )
    start = time.perf_counter()
    for index in range(1000):
        engine.ingest_event(
            event(
                EventType.RELEASE,
                index / 10.0,
                "N" if index % 2 == 0 else "E",
            )
        )
    elapsed = time.perf_counter() - start

    assert elapsed < 5.0
    assert engine.buffer_event_count <= 125
    assert engine.idempotency_entry_count <= 8192


def _wrong_phase_template():
    return EventPhaseDiscoveryResult(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=(
            EventPhase(1, 0.0, 10.0, ("N", "S"), 0.9, 20, 2, ("N", "S")),
            EventPhase(2, 50.0, 60.0, ("E", "W"), 0.9, 20, 2, ("E", "W")),
        ),
        profiles=(),
        cycle_coverage=0.20,
        overlap=0.0,
        supporting_event_count=40,
        contradictory_event_count=4,
    )


def test_synchronizer_wrong_historical_template_becomes_incompatible():
    sync = RealtimePhaseSynchronizer(
        RealtimePhaseTemplate.from_phase_model(_wrong_phase_template()),
        min_evidence_events=6,
    )
    state = sync.ingest_many(_events_for_known_offset(26.0))
    assert state.status == "INCOMPATIBLE"
    assert state.offset_seconds is None


def test_synchronizer_sparse_traffic_stays_warmup():
    sync = RealtimePhaseSynchronizer(
        RealtimePhaseTemplate.from_phase_model(phase_model()),
        min_evidence_events=6,
    )
    state = sync.ingest_many([
        _stream_event(10.0, "N"),
        _stream_event(55.0, "E"),
    ])
    assert state.status == "WARMUP"
    assert state.offset_seconds is None


def test_synchronizer_one_family_burst_never_synchronizes():
    sync = RealtimePhaseSynchronizer(
        RealtimePhaseTemplate.from_phase_model(phase_model()),
        min_evidence_events=6,
    )
    state = sync.ingest_many([
        _stream_event(20.0 + index * 0.1, "N")
        for index in range(12)
    ])
    assert state.status == "WARMUP"
    assert state.offset_seconds is None


def test_synchronizer_burst_with_tiny_opposing_family_stays_warmup():
    sync = RealtimePhaseSynchronizer(
        RealtimePhaseTemplate.from_phase_model(phase_model()),
        min_evidence_events=6,
    )
    state = sync.ingest_many([
        *[_stream_event(20.0 + index * 0.1, "N") for index in range(20)],
        _stream_event(60.0, "E"),
        _stream_event(60.5, "E"),
    ])
    assert state.status == "WARMUP"
    assert state.offset_seconds is None


def test_synchronizer_delayed_events_are_order_independent():
    source = _events_for_known_offset(26.0)
    ordered = RealtimePhaseSynchronizer(
        RealtimePhaseTemplate.from_phase_model(phase_model()),
        min_evidence_events=6,
    ).ingest_many(source)
    delayed = RealtimePhaseSynchronizer(
        RealtimePhaseTemplate.from_phase_model(phase_model()),
        min_evidence_events=6,
    ).ingest_many(reversed(source))
    assert delayed.status == ordered.status == "SYNCHRONIZED"
    assert delayed.offset_seconds == ordered.offset_seconds
    assert delayed.match_ratio == ordered.match_ratio


def test_synchronizer_requires_observation_span_for_bursty_evidence():
    sync = RealtimePhaseSynchronizer(
        RealtimePhaseTemplate.from_phase_model(phase_model()),
        min_evidence_events=6,
        min_observation_span_seconds=10.0,
    )
    state = sync.ingest_many([
        *[_stream_event(20.0 + index * 0.2, "N") for index in range(5)],
        _stream_event(22.0, "E"),
    ])
    assert state.status == "WARMUP"


def test_synchronizer_enters_recovery_and_requires_fresh_evidence():
    sync = RealtimePhaseSynchronizer(
        RealtimePhaseTemplate.from_phase_model(phase_model()),
        min_evidence_events=6,
    )
    assert sync.ingest_many(_events_for_known_offset(26.0)).status == "SYNCHRONIZED"
    sync.enter_recovery()
    assert sync.snapshot().status == "RECOVERY"
    assert sync.snapshot().offset_seconds is None
    resumed = sync.ingest(_stream_event(1000.0, "N"))
    assert resumed.status == "WARMUP"
    assert resumed.offset_seconds is None


def test_fixed_origin_remains_synchronized_without_evidence():
    sync = RealtimePhaseSynchronizer(
        RealtimePhaseTemplate.from_phase_model(phase_model()),
        fixed_origin_ms=0,
        min_evidence_events=6,
    )
    assert sync.snapshot().status == "SYNCHRONIZED"
    sync.enter_recovery()
    assert sync.snapshot().status == "SYNCHRONIZED"


def _extension_phase_model():
    return EventPhaseDiscoveryResult(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=(
            EventPhase(1, 0.0, 30.0, ("N", "S"), 0.9, 20, 2, ("N", "S")),
            EventPhase(2, 30.0, 100.0, ("E", "W"), 0.9, 20, 2, ("E", "W")),
        ),
        profiles=(),
        cycle_coverage=1.0,
        overlap=0.0,
        supporting_event_count=40,
        contradictory_event_count=4,
    )


def test_normal_cycle_does_not_enter_phase_extension():
    engine = RealtimeSignalInferenceEngine(
        _extension_phase_model(),
        event_origin_ms=0,
    )
    snapshot = None
    for timestamp in (10.0, 20.0, 25.0, 29.0):
        snapshot = engine.ingest_event(
            event(EventType.RELEASE, timestamp, "N")
        )

    assert snapshot is not None
    assert snapshot.adaptive_mode == "NORMAL"
    assert snapshot.phase_extension_duration_seconds == 0.0


def test_live_phase_extension_plus_five_seconds_preserves_ns_green():
    engine = RealtimeSignalInferenceEngine(
        _extension_phase_model(),
        event_origin_ms=0,
    )
    for timestamp in (10.0, 20.0, 25.0, 30.0, 31.0, 33.0):
        engine.ingest_event(
            event(EventType.RELEASE, timestamp, "N")
        )
    snapshot = engine.ingest_event(
        event(EventType.RELEASE, 35.0, "N")
    )

    assert snapshot.adaptive_mode == "PHASE_EXTENSION"
    assert snapshot.adaptive_reason == "confirmed_phase_extension"
    assert snapshot.signal_states["N"] == "GREEN"
    assert snapshot.signal_states["E"] == "UNKNOWN"
    assert snapshot.signal_states["W"] == "UNKNOWN"
    assert snapshot.phase_extension_duration_seconds >= 5.0
    assert snapshot.phase_extension_event_count >= 2
    assert snapshot.template_deviation_seconds >= 5.0


def test_live_phase_extension_plus_thirty_seconds_is_supported():
    engine = RealtimeSignalInferenceEngine(
        _extension_phase_model(),
        event_origin_ms=0,
        extension_max_seconds=60.0,
    )
    for timestamp in (10.0, 20.0, 25.0, 30.0, 32.0, 35.0, 40.0):
        engine.ingest_event(event(EventType.RELEASE, timestamp, "N"))
    for timestamp in (45.0, 50.0, 55.0, 60.0):
        snapshot = engine.ingest_event(
            event(EventType.RELEASE, timestamp, "N")
        )

    assert snapshot.adaptive_mode == "PHASE_EXTENSION"
    assert snapshot.signal_states["N"] == "GREEN"
    assert snapshot.phase_extension_duration_seconds >= 30.0
    assert snapshot.phase_extension_peak_duration_seconds >= 30.0


def test_one_post_deadline_false_event_does_not_confirm_extension():
    engine = RealtimeSignalInferenceEngine(
        _extension_phase_model(),
        event_origin_ms=0,
    )
    for timestamp in (10.0, 20.0, 25.0, 30.0):
        engine.ingest_event(event(EventType.RELEASE, timestamp, "N"))

    snapshot = engine.ingest_event(
        event(EventType.RELEASE, 31.0, "N")
    )

    assert snapshot.adaptive_mode == "SUSPECT"
    assert snapshot.signal_states["N"] == "UNKNOWN"


def test_sustained_opposing_flow_ends_phase_extension_without_stale_extension_state():
    engine = RealtimeSignalInferenceEngine(
        _extension_phase_model(),
        event_origin_ms=0,
    )
    for timestamp in (10.0, 20.0, 25.0, 30.0, 31.0, 33.0):
        engine.ingest_event(event(EventType.RELEASE, timestamp, "N"))
    assert engine.adaptive_mode.value == "PHASE_EXTENSION"

    for timestamp in (35.0, 37.0, 40.0):
        snapshot = engine.ingest_event(
            event(EventType.RELEASE, timestamp, "E")
        )

    assert snapshot.adaptive_mode != "PHASE_EXTENSION"


def test_phase_extension_transitions_to_recovery_on_sustained_opposing_flow():
    override = AdaptiveRealtimeOverride()
    phases = _extension_phase_model().phases
    events = []

    for timestamp in (30.0, 31.0, 33.0):
        current = event(EventType.RELEASE, timestamp, "N")
        events.append(current)
        decision = override.evaluate(
            timestamp_ms=int(timestamp * 1000),
            cycle_position_s=timestamp,
            phase=phases[1],
            events=events,
            cycle_seconds=100.0,
            phases=phases,
        )

    assert decision.mode == AdaptiveRealtimeMode.PHASE_EXTENSION

    for timestamp in (35.0, 37.0, 40.0):
        current = event(EventType.RELEASE, timestamp, "E")
        events.append(current)
        decision = override.evaluate(
            timestamp_ms=int(timestamp * 1000),
            cycle_position_s=timestamp,
            phase=phases[1],
            events=events,
            cycle_seconds=100.0,
            phases=phases,
        )

    assert decision.mode == AdaptiveRealtimeMode.RECOVERY


def test_extension_confidence_reflects_conflicting_flow():
    engine = RealtimeSignalInferenceEngine(
        _extension_phase_model(),
        event_origin_ms=0,
    )
    for timestamp in (10.0, 20.0, 25.0, 30.0, 31.0, 33.0, 35.0):
        engine.ingest_event(event(EventType.RELEASE, timestamp, "N"))
    strong = engine.ingest_event(event(EventType.RELEASE, 37.0, "N"))
    before = strong.adaptive_confidence
    mixed = engine.ingest_event(event(EventType.RELEASE, 38.0, "E"))

    assert mixed.adaptive_mode == "PHASE_EXTENSION"
    assert mixed.adaptive_confidence <= before


def test_phase_extension_does_not_mutate_historical_template():
    model = _extension_phase_model()
    before = tuple(
        (phase.phase_id, phase.phase_start, phase.phase_end)
        for phase in model.phases
    )
    engine = RealtimeSignalInferenceEngine(model, event_origin_ms=0)
    for timestamp in (10.0, 20.0, 25.0, 30.0, 31.0, 33.0, 35.0):
        engine.ingest_event(event(EventType.RELEASE, timestamp, "N"))

    after = tuple(
        (phase.phase_id, phase.phase_start, phase.phase_end)
        for phase in model.phases
    )
    assert before == after



def _protected_turn_phase_model():
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
        movement_stages=(
            MovementSignalStage(
                1, "N", "N->E", 0.0, 40.0, 0.95, 0.9, 0.9, 20, 4
            ),
            MovementSignalStage(
                2, "S", "S->W", 0.0, 40.0, 0.90, 0.8, 0.8, 20, 4
            ),
            MovementSignalStage(
                3, "E", "E->W", 40.0, 100.0, 0.95, 0.9, 0.9, 20, 4
            ),
            MovementSignalStage(
                4, "W", "W->E", 40.0, 100.0, 0.90, 0.8, 0.8, 20, 4
            ),
        ),
    )


def _overlap_phase_model():
    model = _protected_turn_phase_model()
    return EventPhaseDiscoveryResult(
        cycle_seconds=model.cycle_seconds,
        bin_seconds=model.bin_seconds,
        phases=model.phases,
        profiles=model.profiles,
        cycle_coverage=model.cycle_coverage,
        overlap=model.overlap,
        supporting_event_count=model.supporting_event_count,
        contradictory_event_count=model.contradictory_event_count,
        movement_stages=(
            *model.movement_stages,
            MovementSignalStage(
                5, "N", "N->S", 0.0, 40.0, 0.92, 0.9, 0.9, 20, 4
            ),
        ),
    )


def test_movement_specific_override_identifies_protected_turn():
    topology = IntersectionTopology(
        families=(
            SignalFamily("NS", ("N", "S")),
            SignalFamily("EW", ("E", "W")),
        ),
        family_conflicts=(("NS", "EW"),),
        movement_conflicts=(("N->S", "N->E"),),
    )
    engine = RealtimeSignalInferenceEngine(
        _protected_turn_phase_model(),
        event_origin_ms=0,
        topology=topology,
    )

    snapshot = None
    for timestamp in (10.0, 12.0, 14.0, 16.0):
        snapshot = engine.ingest_event(
            movement_event(EventType.RELEASE, timestamp, "N", "N->S")
        )

    assert snapshot is not None
    assert snapshot.adaptive_mode == "LIVE_OVERRIDE"
    assert snapshot.effective_axis == "NS"
    assert snapshot.signal_states["N"] == "UNKNOWN"
    states = snapshot.effective_movement_states
    assert states is not None
    assert states["N->S"]["effective_state"] == "GREEN"
    assert states["N->E"]["expected_state"] == "GREEN"
    assert states["N->E"]["effective_state"] == "RED"
    assert states["N->E"]["reason"] == "conflicts_with_live_override"
    assert states["N->S"]["supporting_event_count"] >= 4


def test_compatible_movements_can_overlap_without_live_override():
    topology = IntersectionTopology(
        families=(
            SignalFamily("NS", ("N", "S")),
            SignalFamily("EW", ("E", "W")),
        ),
        family_conflicts=(("NS", "EW"),),
        movement_compatibilities=(("N->S", "N->E"),),
    )
    engine = RealtimeSignalInferenceEngine(
        _overlap_phase_model(),
        event_origin_ms=0,
        topology=topology,
    )

    snapshot = None
    for timestamp in (10.0, 12.0, 14.0, 16.0):
        snapshot = engine.ingest_event(
            movement_event(EventType.RELEASE, timestamp, "N", "N->S")
        )
        snapshot = engine.ingest_event(
            movement_event(EventType.RELEASE, timestamp, "N", "N->E")
        )

    assert snapshot is not None
    assert snapshot.adaptive_mode == "NORMAL"
    states = snapshot.effective_movement_states
    assert states is not None
    assert states["N->E"]["effective_state"] == "GREEN"
    assert states["N->S"]["effective_state"] == "GREEN"
    greens = [
        movement
        for movement, details in states.items()
        if details["effective_state"] == "GREEN"
    ]
    assert not any(
        topology.movements_conflict(left, right)
        for left in greens
        for right in greens
        if left < right
    )


def test_movement_override_does_not_create_conflicting_green_pair():
    topology = IntersectionTopology(
        families=(
            SignalFamily("NS", ("N", "S")),
            SignalFamily("EW", ("E", "W")),
        ),
        family_conflicts=(("NS", "EW"),),
        movement_conflicts=(("N->S", "E->W"),),
    )
    engine = RealtimeSignalInferenceEngine(
        _protected_turn_phase_model(),
        event_origin_ms=0,
        topology=topology,
    )
    snapshot = None
    for timestamp in (44.0, 46.0, 48.0, 50.0):
        snapshot = engine.ingest_event(
            movement_event(EventType.RELEASE, timestamp, "N", "N->S")
        )

    assert snapshot is not None
    assert snapshot.adaptive_mode == "LIVE_OVERRIDE"
    states = snapshot.effective_movement_states or {}
    greens = [
        movement
        for movement, details in states.items()
        if details["effective_state"] == "GREEN"
    ]
    assert not any(
        topology.movements_conflict(left, right)
        for left in greens
        for right in greens
        if left < right
    )
