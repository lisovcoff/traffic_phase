from __future__ import annotations

from types import SimpleNamespace

from app.core.event_phase_discovery import (
    EventPhase,
    EventPhaseDiscoveryResult,
)
from app.core.models import EventType, TrajectoryEvent
from app.core.online_phase_learning import RealtimeOnlineSession
from app.core.online_regime_memory import (
    OnlineRegimeMemory,
    phase_model_similarity,
)


def _phase(
    phase_id: int,
    start: float,
    end: float,
    approaches: tuple[str, ...],
) -> EventPhase:
    return EventPhase(
        phase_id=phase_id,
        phase_start=float(start),
        phase_end=float(end),
        active_approaches=approaches,
        confidence=0.9,
        supporting_event_count=40,
        contradictory_event_count=2,
        members=approaches,
    )


def _model(
    cycle_seconds: float,
    phases: tuple[EventPhase, ...],
    *,
    origin_timestamp_ms: int = 0,
    coverage: float = 0.9,
) -> EventPhaseDiscoveryResult:
    return EventPhaseDiscoveryResult(
        cycle_seconds=float(cycle_seconds),
        bin_seconds=2.0,
        phases=phases,
        profiles=(),
        cycle_coverage=float(coverage),
        overlap=0.0,
        supporting_event_count=100,
        contradictory_event_count=4,
        origin_timestamp_ms=int(origin_timestamp_ms),
    )


def _regime_a(*, shifted: bool = False) -> EventPhaseDiscoveryResult:
    if shifted:
        return _model(
            100.0,
            (
                _phase(1, 20.0, 60.0, ("N", "S")),
                _phase(2, 70.0, 10.0, ("E", "W")),
            ),
            origin_timestamp_ms=500_000,
            coverage=0.80,
        )
    return _model(
        100.0,
        (
            _phase(1, 0.0, 40.0, ("N", "S")),
            _phase(2, 50.0, 90.0, ("E", "W")),
        ),
        coverage=0.80,
    )


def _regime_b() -> EventPhaseDiscoveryResult:
    return _model(
        120.0,
        (
            _phase(1, 0.0, 55.0, ("N", "S")),
            _phase(2, 60.0, 115.0, ("E", "W")),
        ),
        origin_timestamp_ms=1_000_000,
        coverage=0.92,
    )


def _event(timestamp_ms: int, approach: str) -> TrajectoryEvent:
    return TrajectoryEvent(
        event_type=EventType.RELEASE,
        timestamp_ms=int(timestamp_ms),
        approach=approach,
        movement=f"{approach}->x",
        confidence=1.0,
        quality="HIGH",
    )


def test_regime_similarity_ignores_phase_origin_but_not_cycle_change():
    same_regime = phase_model_similarity(
        _regime_a(),
        _regime_a(shifted=True),
    )
    different_regime = phase_model_similarity(
        _regime_a(),
        _regime_b(),
    )

    assert same_regime >= 0.93
    assert different_regime < 0.93


def test_regime_memory_requires_repeated_candidate_and_can_return():
    memory = OnlineRegimeMemory(switch_confirmations=2)
    first_id = memory.seed(
        _regime_a(),
        timestamp_ms=0,
        model_quality="GOOD",
        confidence=0.9,
    )

    first_b = memory.observe_candidate(
        _regime_b(),
        timestamp_ms=1_000_000,
        model_quality="GOOD",
        confidence=0.9,
    )
    assert first_b.switch is False
    assert first_b.pending_confirmations == 1

    second_b = memory.observe_candidate(
        _regime_b(),
        timestamp_ms=1_120_000,
        model_quality="GOOD",
        confidence=0.92,
    )
    assert second_b.switch is True
    assert memory.current_regime_id == second_b.candidate_regime_id
    assert memory.switch_count == 1

    return_a = memory.observe_candidate(
        _regime_a(shifted=True),
        timestamp_ms=2_000_000,
        model_quality="GOOD",
        confidence=0.91,
    )
    assert return_a.switch is False
    assert return_a.candidate_regime_id == first_id

    return_a_confirmed = memory.observe_candidate(
        _regime_a(),
        timestamp_ms=2_120_000,
        model_quality="GOOD",
        confidence=0.93,
    )
    assert return_a_confirmed.switch is True
    assert memory.current_regime_id == first_id
    assert memory.switch_count == 2
    assert len(memory.entries) == 2


class _FakeRegimeScout:
    def __init__(self, candidate: EventPhaseDiscoveryResult) -> None:
        self.accepted_model = candidate
        self.accepted_revision = 0
        self.status = SimpleNamespace(
            last_model_quality="GOOD",
            last_confidence=0.9,
        )
        self.events: list[TrajectoryEvent] = []
        self.max_history_seconds = 45.0 * 60.0

    def ingest_event(self, event: TrajectoryEvent):
        if event.event_type in {
            EventType.RELEASE,
            EventType.CROSSING,
        }:
            self.events.append(event)
            self.accepted_revision += 1
        return self.status


def test_realtime_session_switches_only_after_repeated_usable_regime():
    session = RealtimeOnlineSession(
        _regime_a(),
        event_origin_ms=0,
    )
    session._regime_scout = _FakeRegimeScout(_regime_b())

    first = session.ingest_event(
        _event(1_010_000, "N"),
        event_id="r1",
    )
    assert first["regime_observation"]["switch"] is False
    assert first["regime_memory"]["switch_count"] == 0
    assert session._engine is not None
    assert session._engine.phase_template.cycle_seconds == 100.0

    second = session.ingest_event(
        _event(1_020_000, "E"),
        event_id="r2",
    )
    assert second["regime_observation"]["switch"] is True
    assert second["regime_memory"]["switch_count"] == 1
    assert second["regime_memory"]["regime_count"] == 2
    assert session._engine is not None
    assert session._engine.phase_template.cycle_seconds == 120.0
    assert second["synchronization_status"] == "SYNCHRONIZED"
