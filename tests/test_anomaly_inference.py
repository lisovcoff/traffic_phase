from __future__ import annotations

from app.core.anomaly_inference import AnomalyAwareSignalInference, TrafficCondition
from app.core.anomaly_profile import TrafficBaselineProfile
from app.core.event_phase_discovery import EventPhase, EventPhaseDiscoveryResult
from app.core.models import EventType, TrajectoryEvent
from app.core.signal_state_estimator import SignalState, SignalStateEstimator
from app.core.observability import (
    DeterminationStatus,
    TrafficObservabilityLevel,
    TrafficObservabilityModel,
)


def event(kind, t, approach):
    return TrajectoryEvent(
        event_type=kind,
        timestamp_ms=int(t * 1000),
        approach=approach,
        movement=f"{approach}->x",
        confidence=1.0,
        quality="HIGH",
    )


def model():
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


def baseline():
    events = []
    for t in range(0, 120, 2):
        for approach in ("N", "S", "E", "W"):
            events.append(event(EventType.APPROACH, t, approach))
            events.append(event(EventType.RELEASE, t + 0.2, approach))
    return TrafficBaselineProfile.from_events(events, window_seconds=12.0)


def test_baseline_profile_round_trips():
    profile = baseline()
    assert TrafficBaselineProfile.from_dict(profile.to_dict()) == profile


def test_red_silence_does_not_force_red_again():
    phase = model()
    events = []
    for timestamp in (8, 10, 12, 14):
        for approach in ("N", "S"):
            events.append(event(EventType.APPROACH, timestamp, approach))
            events.append(event(EventType.RELEASE, timestamp + 0.2, approach))
        for approach in ("E", "W"):
            events.append(event(EventType.APPROACH, timestamp, approach))
    result = SignalStateEstimator(phase).estimate(20.0, events)
    aware = AnomalyAwareSignalInference(phase, baseline()).estimate(
        result, events, current_time_s=20.0, recent_window_s=12.0
    )
    assert aware.indicators.condition in {
        TrafficCondition.NORMAL_PHASE,
        TrafficCondition.EXPECTED_RED_SILENCE,
    }
    assert aware.signal.approaches[0].state == SignalState.GREEN


def test_missing_expected_release_reduces_confidence_without_red():
    phase = model()
    events = [event(EventType.APPROACH, 10, "N")]
    result = SignalStateEstimator(phase).estimate(20.0, events)
    aware = AnomalyAwareSignalInference(phase, baseline()).estimate(
        result, events, current_time_s=20.0, recent_window_s=12.0
    )
    assert aware.indicators.missing_expected_release > 0
    assert aware.signal.approaches[0].state != SignalState.RED


def test_conflicting_flow_is_not_reinterpreted_as_red():
    phase = model()
    events = [
        event(EventType.RELEASE, 10, "N"),
        event(EventType.RELEASE, 11, "N"),
        event(EventType.RELEASE, 12, "E"),
        event(EventType.RELEASE, 13, "E"),
        event(EventType.RELEASE, 14, "E"),
    ]
    result = SignalStateEstimator(phase).estimate(20.0, events)
    aware = AnomalyAwareSignalInference(phase, baseline()).estimate(
        result, events, current_time_s=20.0, recent_window_s=12.0
    )
    assert aware.indicators.unexpected_conflicting_flow > 0
    assert aware.signal.phase_id == result.phase_id
    assert aware.signal.approaches[0].state != SignalState.RED


def test_insufficient_data_produces_unknown():
    phase = model()
    events = [event(EventType.RELEASE, 20, "N")]
    result = SignalStateEstimator(phase).estimate(20.0, events)
    weak = baseline()
    weak = TrafficBaselineProfile(
        **{
            **weak.to_dict(),
            "total_flow_median": 100.0,
            "baseline_windows": 100,
        }
    )
    aware = AnomalyAwareSignalInference(phase, weak).estimate(
        result, events, current_time_s=20.0, recent_window_s=12.0
    )
    assert aware.indicators.condition == TrafficCondition.INSUFFICIENT_DATA
    assert all(item.state == SignalState.UNKNOWN for item in aware.signal.approaches)



def test_anomaly_insufficient_data_composes_with_sparse_observability():
    phase = model()
    events = [event(EventType.RELEASE, 20, "N")]
    result = SignalStateEstimator(phase).estimate(20.0, events)
    weak = baseline()
    weak = TrafficBaselineProfile(
        **{
            **weak.to_dict(),
            "total_flow_median": 100.0,
            "baseline_windows": 100,
        }
    )
    aware = AnomalyAwareSignalInference(phase, weak).estimate(
        result, events, current_time_s=20.0, recent_window_s=12.0
    )
    traffic = TrafficObservabilityModel().observe(
        timestamp_ms=20_000,
        events=events,
        determination_status=DeterminationStatus.UNKNOWN,
    )
    assert aware.indicators.condition == TrafficCondition.INSUFFICIENT_DATA
    assert traffic.level is TrafficObservabilityLevel.SPARSE
    assert traffic.determination_status is DeterminationStatus.UNKNOWN
    assert all(
        item.state is SignalState.UNKNOWN
        for item in aware.signal.approaches
    )
