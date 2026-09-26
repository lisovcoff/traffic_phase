from __future__ import annotations

import pytest

from app.core.archive_analysis import (
    _phase_model_cycle_timeline,
    _timeline_unknown_metrics,
)
from app.core.event_cycle_estimator import estimate_event_cycle
from app.core.event_phase_discovery import EventPhaseDiscovery
from app.core.realtime_inference import RealtimeSignalInferenceEngine
from app.api.realtime import RealtimeEngineRegistry
from app.core.realtime_phase_sync import RealtimePhaseSynchronizer, RealtimePhaseTemplate
from app.api.realtime import (
    PhasePayload,
    RealtimeEventPayload,
    RealtimeInferenceRequest,
    infer_realtime,
    registry,
)
from app.core.signal_state_estimator import SignalState, SignalStateEstimator

from tests.fixtures.intersection_configs import FIXTURES


@pytest.mark.parametrize("factory", FIXTURES, ids=lambda item: item.__name__)
def test_complex_intersection_fixture_end_to_end(factory):
    fixture = factory()
    config = fixture.config

    discovery = EventPhaseDiscovery(intersection_config=config)
    profiles, _evidence, _counts = discovery.build_profiles(
        fixture.events,
        cycle_seconds=fixture.phase_model.cycle_seconds,
    )
    profile_groups = {profile.group for profile in profiles}
    configured_groups = {
        head.approach for head in config.primary_signal_heads
    }
    assert configured_groups <= profile_groups

    estimator = SignalStateEstimator(
        fixture.phase_model,
        event_origin_ms=0,
        min_movement_evidence_events=1,
        intersection_config=config,
    )
    result = estimator.estimate(
        fixture.probe_time_s,
        fixture.events,
    )
    states = {
        state.signal_head_id: state
        for state in result.approaches
    }
    assert set(states) == {head.id for head in config.signal_heads}
    if fixture.name == "ordinary_ns_ew":
        assert states["N_MAIN"].state is SignalState.GREEN
    elif fixture.name in {"protected_left_turn", "separate_arrow_section"}:
        arrow_id = next(head.id for head in config.additional_signal_heads)
        assert states[arrow_id].state is SignalState.GREEN
    elif fixture.name == "independent_ns_signal_heads":
        assert states["N_MAIN"].state is SignalState.GREEN
        assert states["S_MAIN"].state is SignalState.GREEN
    elif fixture.name == "complex_overlap":
        assert states["A1_LEFT"].state is SignalState.GREEN
        assert states["A2_LEFT"].state is SignalState.GREEN

    template = RealtimePhaseTemplate.from_phase_model(
        fixture.phase_model,
        intersection_config=config,
    )
    assert template.to_dict()["intersection_config"] == config.to_dict()

    synchronizer = RealtimePhaseSynchronizer(
        template,
        min_evidence_events=1,
        evidence_history_size=8,
    )
    for event in fixture.events[:2]:
        synchronizer.ingest(event)
    assert template.group_for_approach(config.approaches[0]) == (
        config.family_for_approach(config.approaches[0]),
    )

    engine = RealtimeSignalInferenceEngine(
        fixture.phase_model,
        event_origin_ms=0,
        synchronization_min_events=1,
        intersection_config=config,
    )
    snapshot = engine.ingest_event(fixture.events[0], event_id=f"{fixture.name}-0")
    payload = snapshot.to_dict()
    assert payload["intersection_config"] == config.to_dict()
    assert set(payload["signal_head_states"]) == {
        head.id for head in config.signal_heads
    }

@pytest.mark.parametrize("factory", FIXTURES, ids=lambda item: item.__name__)
def test_custom_physical_names_are_not_interpreted_by_direction(factory):
    fixture = factory()
    config = fixture.config
    topology = config.to_topology()

    for approach in config.approaches:
        assert topology.family_for_approach(approach) == config.family_for_approach(
            approach
        )

    if fixture.name == "complex_overlap":
        assert set(config.approaches) == {"A1", "A2", "B1", "B2"}
        assert set(topology.conflicting_approaches_for("A1")) == {"B1", "B2"}


def test_batch_helpers_use_configured_topology_for_custom_names():
    fixture = FIXTURES[-1]()
    topology = fixture.config.to_topology()

    cycle = estimate_event_cycle(
        fixture.events,
        topology=topology,
    )
    assert cycle.flow.used_events == len(fixture.events)
    assert set(cycle.flow.counts_by_direction) == set(topology.approaches)

    timeline = _phase_model_cycle_timeline(
        fixture.phase_model.to_dict(),
        intersection_config=fixture.config,
        max_points=4,
    )
    states = timeline[0]["states"]
    assert states["A1"] == "GREEN"
    assert states["A2"] == "GREEN"
    assert states["B1"] == "RED"
    assert states["B2"] == "RED"

    metrics = _timeline_unknown_metrics(
        timeline,
        approaches=topology.approaches,
    )
    assert set(metrics["per_approach_rate"]) == set(topology.approaches)


def test_realtime_engine_registry_is_bounded():
    registry = RealtimeEngineRegistry(max_streams=2)

    def create(stream_id):
        return registry.get_or_create(
            stream_id,
            phase_model=None,
            event_origin_ms=None,
            recent_window_s=12.0,
            yellow_duration_seconds=3.0,
            red_yellow_duration_seconds=2.0,
            baseline=None,
            topology=None,
            intersection_config=None,
        )

    first = create("stream-1")
    create("stream-2")
    create("stream-3")

    assert registry.stream_count == 2
    assert create("stream-1") is not first
    assert registry.stream_count == 2


def test_default_config_remains_backward_compatible():
    fixture = FIXTURES[0]()
    assert fixture.config.to_dict()["intersection_id"] == "default-four-way"
    estimator = SignalStateEstimator(fixture.phase_model, event_origin_ms=0)
    result = estimator.estimate(fixture.probe_time_s, fixture.events)
    assert {state.signal_head_id for state in result.approaches} == {
        "N_MAIN",
        "S_MAIN",
        "E_MAIN",
        "W_MAIN",
    }


__all__ = ["FIXTURES"]


@pytest.mark.parametrize("factory", FIXTURES, ids=lambda item: item.__name__)
def test_realtime_api_roundtrip_uses_fixture_config(factory):
    import asyncio

    fixture = factory()
    source_event = fixture.events[0]
    phase_payload = PhasePayload(
        cycle_seconds=fixture.phase_model.cycle_seconds,
        bin_seconds=fixture.phase_model.bin_seconds,
        phases=[phase.to_dict() for phase in fixture.phase_model.phases],
        movement_stages=[
            stage.to_dict()
            for stage in fixture.phase_model.movement_stages
        ],
        intersection_config=fixture.config.to_dict(),
    )
    request = RealtimeInferenceRequest(
        stream_id=f"fixture-{fixture.name}",
        event=RealtimeEventPayload(
            event_type=source_event.event_type,
            timestamp_ms=source_event.timestamp_ms,
            approach=source_event.approach,
            movement=source_event.movement,
            confidence=source_event.confidence,
            quality=source_event.quality,
        ),
        event_id=f"{fixture.name}-api-1",
        phase_model=phase_payload,
        event_origin_ms=0,
        recent_window_s=12.0,
    )
    try:
        snapshot = asyncio.run(infer_realtime(request))
    finally:
        registry.reset(request.stream_id)
    assert snapshot["intersection_config"] == fixture.config.to_dict()
    assert set(snapshot["signal_head_states"]) == {
        head.id for head in fixture.config.signal_heads
    }
    renderer = snapshot["signal_renderer"]
    assert renderer["intersection_id"] == fixture.config.intersection_id
    assert {head["id"] for head in renderer["heads"]} == {
        head.id for head in fixture.config.signal_heads
    }
