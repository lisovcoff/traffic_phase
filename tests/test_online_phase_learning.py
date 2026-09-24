from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.api.realtime import (
    RealtimeEventPayload,
    RealtimeInferenceRequest,
    infer_realtime,
    registry,
)
from app.core.models import EventType, TrajectoryEvent
from app.core.online_phase_learning import OnlinePhaseBootstrap


def _event(
    event_type: EventType,
    timestamp_ms: int,
    approach: str,
) -> TrajectoryEvent:
    return TrajectoryEvent(
        event_type=event_type,
        timestamp_ms=int(timestamp_ms),
        approach=approach,
        movement=f"{approach}->x",
        confidence=1.0,
        quality="HIGH",
    )


def _synthetic_events(
    period_s: float = 100.0,
    *,
    cycles: int = 12,
) -> list[TrajectoryEvent]:
    events: list[TrajectoryEvent] = []
    offsets = (
        (0.10, "N"),
        (0.25, "S"),
        (0.60, "E"),
        (0.75, "W"),
    )
    for cycle in range(cycles):
        base_ms = int(cycle * period_s * 1000.0)
        for fraction, approach in offsets:
            timestamp_ms = base_ms + int(
                period_s * fraction * 1000.0
            )
            events.append(
                _event(
                    EventType.RELEASE,
                    timestamp_ms,
                    approach,
                )
            )
            events.append(
                _event(
                    EventType.CROSSING,
                    timestamp_ms + 1000,
                    approach,
                )
            )
    return events


def test_online_bootstrap_accepts_reusable_template_after_causal_observation(
    monkeypatch,
):
    learned_model = SimpleNamespace(
        cycle_coverage=0.80,
        origin_timestamp_ms=10_000,
    )

    def fake_reconstruct(*args, **kwargs):
        return SimpleNamespace(
            status="ok",
            phase_model=learned_model,
            cycle=SimpleNamespace(
                estimate=SimpleNamespace(cycle_seconds=100.0)
            ),
            model_quality="PARTIAL",
            confidence=0.75,
            error_reason=None,
        )

    monkeypatch.setattr(
        "app.core.online_phase_learning.reconstruct_event_session",
        fake_reconstruct,
    )
    bootstrap = OnlinePhaseBootstrap(
        min_observation_seconds=300.0,
        min_observed_cycles=4.0,
        min_usable_events=16,
        retry_event_stride=8,
        retry_seconds=30.0,
    )

    status = None
    for event in _synthetic_events(cycles=6):
        status = bootstrap.ingest_event(event)
        if status.ready:
            break

    assert status is not None
    assert status.ready is True
    assert status.mode == "READY"
    assert status.last_model_quality == "PARTIAL"
    assert status.candidate_cycle_seconds == 100.0
    assert status.candidate_coverage == 0.80
    assert status.observed_cycles is not None
    assert status.observed_cycles >= 4.0
    assert bootstrap.accepted_model is learned_model


def test_online_bootstrap_does_not_guess_from_short_prefix():
    bootstrap = OnlinePhaseBootstrap(
        min_observation_seconds=600.0,
        min_observed_cycles=8.0,
        min_usable_events=32,
    )

    status = None
    for event in _synthetic_events(cycles=2):
        status = bootstrap.ingest_event(event)

    assert status is not None
    assert status.ready is False
    assert status.mode == "LEARNING"
    assert bootstrap.accepted_model is None
    assert status.reason in {
        "need_more_release_or_crossing_events",
        "need_more_observation_time",
    }


def test_realtime_api_can_start_without_phase_model():
    stream_id = "online-bootstrap-no-template"
    registry.reset(stream_id)
    payload = RealtimeInferenceRequest(
        stream_id=stream_id,
        event=RealtimeEventPayload(
            event_type=EventType.RELEASE,
            timestamp_ms=10_000,
            approach="N",
            movement="N->x",
        ),
    )

    result = asyncio.run(infer_realtime(payload))

    assert result["synchronization_status"] == "LEARNING"
    assert result["phase_id"] is None
    assert set(result["signal_states"].values()) == {"UNKNOWN"}
    assert result["learning"]["mode"] == "LEARNING"
    assert result["learning"]["ready"] is False
    assert result["unknown_reasons"]["N"] == "learning_phase_model"
    registry.reset(stream_id)


def test_realtime_learning_duplicate_is_idempotent():
    stream_id = "online-bootstrap-duplicate"
    registry.reset(stream_id)
    payload = RealtimeInferenceRequest(
        stream_id=stream_id,
        event_id="evt-1",
        event=RealtimeEventPayload(
            event_type=EventType.RELEASE,
            timestamp_ms=10_000,
            approach="N",
            movement="N->x",
        ),
    )

    first = asyncio.run(infer_realtime(payload))
    duplicate = asyncio.run(infer_realtime(payload))

    assert first["duplicate"] is False
    assert duplicate["duplicate"] is True
    assert duplicate["learning"] == first["learning"]
    assert duplicate["buffer_event_count"] == 1
    registry.reset(stream_id)



def test_real_reconstruction_candidate_is_measured_even_when_not_yet_safe():
    bootstrap = OnlinePhaseBootstrap(
        min_observation_seconds=300.0,
        min_observed_cycles=4.0,
        min_usable_events=16,
        retry_event_stride=24,
        retry_seconds=30.0,
    )

    status = None
    for event in _synthetic_events():
        status = bootstrap.ingest_event(event)

    assert status is not None
    assert status.candidate_cycle_seconds is not None
    assert 92.0 <= status.candidate_cycle_seconds <= 108.0
    assert status.candidate_coverage is not None
    assert status.candidate_coverage >= 0.70
    if not status.ready:
        assert status.reason in {
            "candidate_not_safe_for_realtime_template",
            "waiting_for_next_learning_attempt",
        }
