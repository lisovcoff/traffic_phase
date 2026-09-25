from __future__ import annotations

import pytest

from app.core.models import EventType, MovementEvidenceQuality, TrajectoryEvent
from app.core.observability import (
    DiagnosticReason,
    DeterminationStatus,
    ObservabilitySnapshot,
    TrafficObservabilityLevel,
    TrafficObservabilityModel,
    build_batch_observability,
    build_realtime_observability,
)


def _event(approach: str, timestamp_ms: int, *, movement: str | None = None,
           quality: MovementEvidenceQuality = MovementEvidenceQuality.VALID,
           confidence: float = 1.0) -> TrajectoryEvent:
    return TrajectoryEvent(
        event_type=EventType.RELEASE,
        timestamp_ms=timestamp_ms,
        approach=approach,
        movement=movement or f"{approach}->x",
        confidence=confidence,
        quality="HIGH",
        movement_quality=quality,
    )


def _events(count: int = 12):
    return [
        _event(("N", "S", "E", "W")[index % 4], index * 1000)
        for index in range(count)
    ]


def test_known_status_exposes_six_independent_confidences():
    result = build_batch_observability(
        _events(),
        cycle_confidence=0.9,
        phase_confidence=0.9,
        phase_coverage=0.9,
    )
    assert result.determination_status is DeterminationStatus.KNOWN
    assert result.diagnostic_reason is None
    assert result.cycle_confidence == 0.9
    assert result.synchronization_confidence == 0.9
    assert result.phase_confidence == 0.9
    assert result.movement_confidence == 1.0
    assert result.traffic_evidence_confidence == 1.0
    assert result.observability_confidence == 0.9


@pytest.mark.parametrize(
    ("reason", "events"),
    [
        (DiagnosticReason.NO_EVIDENCE, []),
        (DiagnosticReason.INSUFFICIENT_EVENTS, _events(4)),
        (DiagnosticReason.ONLY_ONE_FAMILY, [_event("N", i * 1000) for i in range(12)]),
        (
            DiagnosticReason.UNOBSERVED_MOVEMENT,
            [
                _event(
                    ("N", "S", "E", "W")[i % 4],
                    i * 1000,
                    movement=f"{('N','S','E','W')[i%4]}->UNKNOWN",
                    quality=MovementEvidenceQuality.UNKNOWN,
                )
                for i in range(12)
            ],
        ),
        (DiagnosticReason.LOW_PHASE_CONFIDENCE, _events()),
        (
            DiagnosticReason.OUTSIDE_TOPOLOGY,
            [_event(("N", "S", "E", "X")[i % 4], i * 1000) for i in range(12)],
        ),
    ],
)
def test_batch_diagnostic_reasons(reason, events):
    kwargs = dict(
        cycle_confidence=0.9,
        phase_confidence=0.9,
        phase_coverage=0.9,
    )
    if reason is DiagnosticReason.LOW_PHASE_CONFIDENCE:
        kwargs["phase_confidence"] = 0.1
    result = build_batch_observability(events, **kwargs)
    assert result.diagnostic_reason is reason


def test_batch_conflicting_evidence_is_unknown():
    phase = type(
        "PhaseModel",
        (),
        {
            "phases": (
                type(
                    "Phase",
                    (),
                    {
                        "supporting_event_count": 2,
                        "contradictory_event_count": 4,
                    },
                )(),
            )
        },
    )()
    result = build_batch_observability(
        _events(),
        cycle_confidence=0.9,
        phase_confidence=0.9,
        phase_coverage=0.9,
        phase_model=phase,
    )
    assert result.determination_status is DeterminationStatus.UNKNOWN
    assert result.diagnostic_reason is DiagnosticReason.CONFLICTING_EVIDENCE


@pytest.mark.parametrize(
    ("reason", "template", "recovery", "families", "ready"),
    [
        (DiagnosticReason.RECOVERY, "COMPATIBLE", True, 2, False),
        (DiagnosticReason.INCOMPATIBLE_TEMPLATE, "INCOMPATIBLE", False, 2, False),
        (DiagnosticReason.ONLY_ONE_FAMILY, "CHECKING", False, 1, False),
        (DiagnosticReason.INSUFFICIENT_EVENTS, "CHECKING", False, 2, False),
    ],
)
def test_realtime_diagnostic_reasons(reason, template, recovery, families, ready):
    result = build_realtime_observability(
        _events(12 if reason is not DiagnosticReason.INSUFFICIENT_EVENTS else 4),
        cycle_confidence=0.9,
        synchronization_confidence=0.9,
        phase_confidence=0.9,
        synchronization_ready=ready,
        observed_family_count=families,
        template_compatibility=template,
        recovery=recovery,
    )
    assert result.diagnostic_reason is reason


def test_realtime_known_status():
    result = build_realtime_observability(
        _events(),
        cycle_confidence=0.9,
        synchronization_confidence=0.9,
        phase_confidence=0.9,
        synchronization_ready=True,
        observed_family_count=2,
        template_compatibility="COMPATIBLE",
    )
    assert result.determination_status is DeterminationStatus.KNOWN


def test_no_evidence_is_insufficient_data_and_never_red():
    result = build_realtime_observability(
        [],
        cycle_confidence=0.0,
        synchronization_confidence=0.0,
        phase_confidence=0.0,
        synchronization_ready=False,
        observed_family_count=0,
        template_compatibility="CHECKING",
    )
    assert result.determination_status is DeterminationStatus.INSUFFICIENT_DATA
    assert result.diagnostic_reason is DiagnosticReason.NO_EVIDENCE


def test_serialization_uses_explicit_status_and_reason():
    result = ObservabilitySnapshot(
        determination_status=DeterminationStatus.UNKNOWN,
        diagnostic_reason=DiagnosticReason.RECOVERY,
        cycle_confidence=0.2,
        synchronization_confidence=0.3,
        phase_confidence=0.4,
        movement_confidence=0.5,
        traffic_evidence_confidence=0.6,
        observability_confidence=0.2,
    )
    payload = result.to_dict()
    assert payload["determination_status"] == "UNKNOWN"
    assert payload["diagnostic_reason"] == "RECOVERY"


def test_batch_reconstruction_snapshot_contains_observability():
    from app.core.reconstruction import reconstruct_event_sessions

    result = reconstruct_event_sessions(_events(12))
    assert result
    snapshot = result[0].observability
    assert snapshot is not None
    assert snapshot.determination_status in {
        DeterminationStatus.KNOWN,
        DeterminationStatus.UNKNOWN,
    }



def test_traffic_observability_classifies_synthetic_density_levels():
    assert (
        TrafficObservabilityModel().observe(
            timestamp_ms=12_000,
            events=_events(6),
            determination_status=DeterminationStatus.KNOWN,
        ).level
        is TrafficObservabilityLevel.HIGH
    )
    assert (
        TrafficObservabilityModel().observe(
            timestamp_ms=12_000,
            events=_events(2),
            determination_status=DeterminationStatus.KNOWN,
        ).level
        is TrafficObservabilityLevel.DEGRADED
    )
    assert (
        TrafficObservabilityModel().observe(
            timestamp_ms=12_000,
            events=_events(1),
            determination_status=DeterminationStatus.KNOWN,
        ).level
        is TrafficObservabilityLevel.SPARSE
    )
    assert (
        TrafficObservabilityModel().observe(
            timestamp_ms=12_000,
            events=[],
            determination_status=DeterminationStatus.INSUFFICIENT_DATA,
        ).level
        is TrafficObservabilityLevel.INSUFFICIENT_DATA
    )


def test_sparse_traffic_caps_known_determination_without_using_clock_time():
    model = TrafficObservabilityModel()
    snapshot = model.observe(
        timestamp_ms=23 * 60 * 60 * 1000,
        events=[_event("N", 23 * 60 * 60 * 1000)],
        determination_status=DeterminationStatus.KNOWN,
    )
    assert snapshot.level is TrafficObservabilityLevel.SPARSE
    assert snapshot.determination_status is DeterminationStatus.KNOWN
    assert snapshot.diagnostic_reason is None
    assert snapshot.unknown_rate == 0.0
    assert snapshot.determined_rate == 1.0


def test_day_and_night_are_classified_by_evidence_density_not_hour():
    day = TrafficObservabilityModel().observe(
        timestamp_ms=8 * 60 * 60 * 1000,
        events=_events(6),
        determination_status=DeterminationStatus.KNOWN,
    )
    night = TrafficObservabilityModel().observe(
        timestamp_ms=23 * 60 * 60 * 1000,
        events=_events(1),
        determination_status=DeterminationStatus.KNOWN,
    )
    assert day.level is TrafficObservabilityLevel.HIGH
    assert night.level is TrafficObservabilityLevel.SPARSE
    assert day.determination_status is DeterminationStatus.KNOWN
    assert night.determination_status is DeterminationStatus.KNOWN


def test_traffic_observability_rolls_determination_metrics():
    model = TrafficObservabilityModel()
    model.observe(
        timestamp_ms=0,
        events=_events(6),
        determination_status=DeterminationStatus.KNOWN,
    )
    model.observe(
        timestamp_ms=4_000,
        events=_events(1),
        determination_status=DeterminationStatus.UNKNOWN,
    )
    model.observe(
        timestamp_ms=8_000,
        events=_events(1),
        determination_status=DeterminationStatus.UNKNOWN,
    )
    snapshot = model.observe(
        timestamp_ms=12_000,
        events=_events(6),
        determination_status=DeterminationStatus.KNOWN,
    )
    assert snapshot.determined_rate == 0.5
    assert snapshot.unknown_rate == 0.5
    assert snapshot.longest_unknown_interval_seconds == 8.0
    assert snapshot.evidence_density == 0.5
    assert snapshot.sample_count == 4


def test_serialization_contains_nested_traffic_observability():
    traffic = TrafficObservabilityModel().observe(
        timestamp_ms=12_000,
        events=_events(1),
        determination_status=DeterminationStatus.KNOWN,
    )
    result = ObservabilitySnapshot(
        determination_status=DeterminationStatus.UNKNOWN,
        diagnostic_reason=None,
        cycle_confidence=0.2,
        synchronization_confidence=0.3,
        phase_confidence=0.4,
        movement_confidence=0.5,
        traffic_evidence_confidence=0.6,
        observability_confidence=0.2,
        traffic_observability=traffic,
    )
    payload = result.to_dict()
    assert payload["traffic_observability"]["level"] == "SPARSE"
    assert payload["traffic_observability"]["determined_rate"] == 1.0
