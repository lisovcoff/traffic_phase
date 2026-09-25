from __future__ import annotations

from app.core.event_phase_discovery import EventPhase, EventPhaseDiscoveryResult
from app.core.intersection_config import IntersectionConfig, Movement, SignalHead
from app.core.intersection_topology import SignalFamily
from app.core.models import EventType, MovementEvidenceQuality, TrajectoryEvent
from app.core.observability import DiagnosticReason, DeterminationStatus
from app.core.signal_state_estimator import (
    DEFAULT_RED_YELLOW_DURATION_SECONDS,
    DEFAULT_YELLOW_DURATION_SECONDS,
    SignalState,
    SignalStateEstimator,
)


def event(kind, t, approach, movement=None, confidence=1.0, movement_quality=MovementEvidenceQuality.VALID):
    return TrajectoryEvent(
        event_type=kind,
        timestamp_ms=int(t * 1000),
        approach=approach,
        movement=movement or f"{approach}->x",
        confidence=confidence,
        quality="HIGH",
        movement_quality=movement_quality,
    )


def model(gapped=False):
    phases = (
        EventPhase(1, 0.0, 40.0, ("N", "S"), 0.9, 20, 1, ("N", "S")),
        EventPhase(2, 50.0, 90.0, ("E", "W"), 0.9, 20, 1, ("E", "W")),
    )
    # The gapped fixture above is intentionally replaced below for clarity.
    if not gapped:
        phases = (
            EventPhase(1, 0.0, 40.0, ("N", "S"), 0.9, 20, 1, ("N", "S")),
            EventPhase(2, 40.0, 100.0, ("E", "W"), 0.9, 20, 1, ("E", "W")),
        )
    return EventPhaseDiscoveryResult(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=phases,
        profiles=(),
        cycle_coverage=0.8 if gapped else 1.0,
        overlap=0.0,
        supporting_event_count=40,
        contradictory_event_count=1,
    )


def states(result):
    return {
        (item.signal_head_id or item.approach): item
        for item in result.approaches
    }


def test_green_requires_phase_and_movement_evidence():
    result = SignalStateEstimator(model()).estimate(
        20.0,
        [event(EventType.RELEASE, 10, "N")],
    )
    n = states(result)["N_MAIN"]
    assert n.state is SignalState.GREEN
    assert n.determination_status is DeterminationStatus.KNOWN
    assert n.phase_confidence > 0
    assert n.traffic_evidence_confidence > 0


def test_no_cars_is_unknown_not_red_or_green():
    result = SignalStateEstimator(model()).estimate(20.0, [])
    assert all(item.state is SignalState.UNKNOWN for item in result.approaches)
    assert all(
        item.diagnostic_reason is DiagnosticReason.NO_EVIDENCE
        for item in result.approaches
    )


def test_stop_approach_and_silence_never_create_red():
    events = [
        TrajectoryEvent(EventType.STOP, 10_000, "N", "N->x", 1.0, "HIGH"),
        TrajectoryEvent(EventType.APPROACH, 11_000, "N", "N->x", 1.0, "HIGH"),
    ]
    result = SignalStateEstimator(model()).estimate(20.0, events)
    assert all(item.state is SignalState.UNKNOWN for item in result.approaches)


def test_false_crossing_without_release_does_not_establish_green():
    result = SignalStateEstimator(model()).estimate(
        20.0,
        [
            event(EventType.CROSSING, 10, "N"),
            event(EventType.CROSSING, 11, "N"),
        ],
    )
    n = states(result)["N_MAIN"]
    assert n.state is SignalState.UNKNOWN
    assert n.diagnostic_reason is DiagnosticReason.INSUFFICIENT_EVENTS


def test_two_conflicting_machines_can_become_unknown_after_persistence():
    result = SignalStateEstimator(model()).estimate(
        20.0,
        [
            event(EventType.RELEASE, 10, "N"),
            event(EventType.RELEASE, 15, "E"),
            event(EventType.RELEASE, 19, "E"),
        ],
    )
    n = states(result)["N_MAIN"]
    assert n.state is SignalState.UNKNOWN
    assert n.diagnostic_reason is DiagnosticReason.CONFLICTING_EVIDENCE


def test_temporary_single_conflict_is_hysteretic():
    result = SignalStateEstimator(model()).estimate(
        20.0,
        [
            event(EventType.RELEASE, 5, "N"),
            event(EventType.RELEASE, 15, "N"),
            event(EventType.RELEASE, 19, "E"),
        ],
    )
    n = states(result)["N_MAIN"]
    assert n.state is SignalState.GREEN
    assert n.contradictory_event_count == 1
    assert n.probability <= 0.55


def test_delayed_and_out_of_order_events_are_deterministic():
    events = [
        event(EventType.RELEASE, 15, "N"),
        event(EventType.RELEASE, 5, "N"),
        event(EventType.RELEASE, 10, "N"),
        event(EventType.RELEASE, 25, "N"),
    ]
    estimator = SignalStateEstimator(model())
    forward = estimator.estimate(20.0, events)
    reversed_result = estimator.estimate(20.0, list(reversed(events)))
    assert forward.to_dict() == reversed_result.to_dict()
    assert states(forward)["N_MAIN"].state is SignalState.GREEN


def test_delayed_future_event_is_ignored():
    result = SignalStateEstimator(model()).estimate(
        20.0,
        [event(EventType.RELEASE, 30, "N")],
    )
    n = states(result)["N_MAIN"]
    assert n.state is SignalState.UNKNOWN
    assert n.diagnostic_reason is DiagnosticReason.NO_EVIDENCE


def test_sparse_night_traffic_stays_unknown_without_current_evidence():
    result = SignalStateEstimator(model()).estimate(20.0, [])
    n = states(result)["N_MAIN"]
    assert n.diagnostic_reason is DiagnosticReason.NO_EVIDENCE


def test_low_phase_confidence_is_unknown():
    low = EventPhaseDiscoveryResult(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=(EventPhase(1, 0, 40, ("N",), 0.1, 20, 0, ("N",)),),
        profiles=(),
        cycle_coverage=1.0,
        overlap=0.0,
        supporting_event_count=20,
        contradictory_event_count=0,
    )
    n = states(
        SignalStateEstimator(low).estimate(
            20.0, [event(EventType.RELEASE, 10, "N")]
        )
    )["N_MAIN"]
    assert n.state is SignalState.UNKNOWN
    assert n.diagnostic_reason is DiagnosticReason.LOW_PHASE_CONFIDENCE


def test_yellow_and_red_yellow_require_movement_evidence():
    estimator = SignalStateEstimator(model())
    yellow = states(
        estimator.estimate(
            37.0,
            [event(EventType.RELEASE, 30, "N"), event(EventType.RELEASE, 35, "N")],
        )
    )
    red_yellow = states(
        estimator.estimate(
            40.0,
            [event(EventType.RELEASE, 34, "E"), event(EventType.RELEASE, 39, "E")],
        )
    )
    assert DEFAULT_YELLOW_DURATION_SECONDS == 3.0
    assert DEFAULT_RED_YELLOW_DURATION_SECONDS == 2.0
    assert yellow["N_MAIN"].state is SignalState.YELLOW
    assert red_yellow["E_MAIN"].state is SignalState.RED_YELLOW


def test_inactive_section_red_requires_positive_conflicting_flow():
    result = states(
        SignalStateEstimator(model()).estimate(
            45.0,
            [event(EventType.RELEASE, 35, "E"), event(EventType.RELEASE, 42, "E")],
        )
    )
    assert result["E_MAIN"].state is SignalState.GREEN
    assert result["N_MAIN"].state is SignalState.RED


def test_phase_gap_is_unknown():
    result = SignalStateEstimator(model(gapped=True)).estimate(
        45.0,
        [event(EventType.RELEASE, 35, "N")],
    )
    assert all(item.state is SignalState.UNKNOWN for item in result.approaches)


def test_probability_changes_with_event_confidence():
    high = SignalStateEstimator(model()).estimate(
        20, [event(EventType.RELEASE, 10, "N", confidence=1.0)]
    )
    low = SignalStateEstimator(model()).estimate(
        20, [event(EventType.RELEASE, 10, "N", confidence=0.1)]
    )
    assert states(high)["N_MAIN"].state is SignalState.GREEN
    assert states(low)["N_MAIN"].state is SignalState.GREEN
    assert states(high)["N_MAIN"].probability > states(low)["N_MAIN"].probability


def test_explicit_origin_is_respected():
    estimator = SignalStateEstimator(model(), event_origin_ms=1_000_000)
    result = estimator.estimate(
        20,
        [event(EventType.RELEASE, 1_010, "N")],
    )
    assert states(result)["N_MAIN"].supporting_event_count == 1


def test_complex_topology_determines_each_signal_section_independently():
    config = IntersectionConfig(
        intersection_id="complex",
        families=(
            SignalFamily("NS", ("N", "S")),
            SignalFamily("EW", ("E", "W")),
        ),
        movements=(
            Movement("N->S", "N", "S", "through"),
            Movement("N->E", "N", "E", "left"),
            Movement("S->N", "S", "N", "through"),
            Movement("S->W", "S", "W", "left"),
            Movement("E->W", "E", "W", "through"),
            Movement("W->E", "W", "E", "through"),
        ),
        signal_heads=(
            SignalHead("N_MAIN", "N", ("N->S",)),
            SignalHead("N_LEFT", "N", ("N->E",), additional=True, arrows=("left",)),
            SignalHead("S_MAIN", "S", ("S->N",)),
            SignalHead("S_LEFT", "S", ("S->W",), additional=True, arrows=("left",)),
            SignalHead("E_MAIN", "E", ("E->W",)),
            SignalHead("W_MAIN", "W", ("W->E",)),
        ),
        family_conflicts=(("NS", "EW"),),
    )
    result = SignalStateEstimator(
        model(),
        intersection_config=config,
    ).estimate(
        20,
        [
            event(EventType.RELEASE, 5, "N", "N->S"),
            event(EventType.RELEASE, 15, "N", "N->S"),
        ],
    )
    current = states(result)
    assert current["N_MAIN"].state is SignalState.GREEN
    assert current["N_LEFT"].state is SignalState.UNKNOWN
    assert current["N_LEFT"].diagnostic_reason is DiagnosticReason.NO_EVIDENCE
    assert current["S_MAIN"].state is SignalState.UNKNOWN
