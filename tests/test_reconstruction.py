from __future__ import annotations

from types import SimpleNamespace

from app.core.event_phase_discovery import EventPhaseDiscoveryResult
from app.core.models import Detection, EventType, Trajectory, TrajectoryEvent
from app.core.reconstruction import (
    BatchReconstruction,
    batch_model_quality,
    DEFAULT_SESSION_GAP_SECONDS,
    reconstruct_event_sessions,
    _raw_axis_signature,
    split_event_session_into_regimes,
    split_events_into_sessions,
    split_trajectories_into_sessions,
)


def test_batch_reconstruction_to_dict_exposes_origin_and_models():
    cycle = type("Cycle", (), {"to_dict": lambda self: {"estimated_cycle": 100.0}})()
    phase = EventPhaseDiscoveryResult(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=(),
        profiles=(),
        cycle_coverage=0.0,
        overlap=0.0,
        supporting_event_count=0,
        contradictory_event_count=0,
        origin_timestamp_ms=1234,
    )
    reconstruction = BatchReconstruction(
        trajectories=(),
        events=(),
        cycle=cycle,
        phase_model=phase,
        origin_timestamp_ms=1234,
    )
    data = reconstruction.to_dict()
    assert data["origin_timestamp_ms"] == 1234
    assert data["phase_model"]["origin_timestamp_ms"] == 1234


def _event(event_type, timestamp_ms, approach):
    return TrajectoryEvent(
        event_type=event_type,
        timestamp_ms=int(timestamp_ms),
        approach=approach,
        movement=f"{approach}->x",
        confidence=1.0,
        quality="HIGH",
    )


def _synthetic_events(
    period_s,
    *,
    cycles=10,
    origin_ms=0,
):
    events = []
    offsets = (
        (0.10, "N"),
        (0.25, "S"),
        (0.60, "E"),
        (0.75, "W"),
    )
    for cycle in range(cycles):
        base_ms = origin_ms + int(cycle * period_s * 1000.0)
        for fraction, approach in offsets:
            timestamp_ms = base_ms + int(period_s * fraction * 1000.0)
            events.append(
                _event(EventType.RELEASE, timestamp_ms, approach)
            )
            events.append(
                _event(EventType.CROSSING, timestamp_ms + 1000, approach)
            )
    return events


def _trajectory(vehicle_id, start_ms, end_ms):
    return Trajectory(
        vehicle_id=vehicle_id,
        timestamp_ms=end_ms,
        zone_in="N",
        zone_out="_S",
        movement="N->_S",
        speed=None,
        wait_s=0.0,
        move_s=0.0,
        distance=None,
        detections=(
            Detection(start_ms, 55.0, 61.0),
            Detection(end_ms, 55.0001, 61.0),
        ),
    )


def test_one_continuous_event_session_is_not_split():
    events = _synthetic_events(100.0, cycles=3)

    sessions = split_events_into_sessions(events)

    assert len(sessions) == 1
    assert len(sessions[0]) == len(events)


def test_trajectory_gap_over_thirty_minutes_starts_new_session():
    first = _trajectory(1, 0, 10_000)
    second = _trajectory(
        2,
        int((DEFAULT_SESSION_GAP_SECONDS + 20.0) * 1000),
        int((DEFAULT_SESSION_GAP_SECONDS + 30.0) * 1000),
    )

    sessions = split_trajectories_into_sessions([first, second])

    assert len(sessions) == 2
    assert sessions[0][0].vehicle_id == 1
    assert sessions[1][0].vehicle_id == 2


def test_gap_below_threshold_stays_in_same_session():
    events = [
        _event(EventType.RELEASE, 0, "N"),
        _event(
            EventType.RELEASE,
            int((DEFAULT_SESSION_GAP_SECONDS - 1.0) * 1000),
            "S",
        ),
    ]

    sessions = split_events_into_sessions(events)

    assert len(sessions) == 1


def test_session_split_sorts_unordered_input():
    events = [
        _event(EventType.RELEASE, 7_200_000, "E"),
        _event(EventType.RELEASE, 1_000, "N"),
        _event(EventType.RELEASE, 2_000, "S"),
        _event(EventType.RELEASE, 7_201_000, "W"),
    ]

    sessions = split_events_into_sessions(events)

    assert len(sessions) == 2
    assert sessions[0][0].timestamp_ms == 1_000
    assert sessions[0][-1].timestamp_ms == 2_000
    assert sessions[1][0].timestamp_ms == 7_200_000


def test_sessions_reconstruct_different_cycle_patterns_independently():
    first_events = _synthetic_events(
        100.0,
        cycles=10,
        origin_ms=0,
    )
    second_events = _synthetic_events(
        120.0,
        cycles=10,
        origin_ms=7_200_000,
    )
    events = list(reversed(first_events + second_events))

    results = reconstruct_event_sessions(events)

    assert len(results) == 2
    assert all(result.status == "ok" for result in results)
    assert 92.0 <= results[0].cycle.estimate.cycle_seconds <= 108.0
    assert 112.0 <= results[1].cycle.estimate.cycle_seconds <= 128.0
    assert results[0].phase_model.origin_timestamp_ms < (
        results[1].phase_model.origin_timestamp_ms
    )
    assert results[0].end_timestamp_ms < results[1].start_timestamp_ms
    assert all(0.0 <= result.confidence <= 1.0 for result in results)


def test_short_session_returns_insufficient_data_instead_of_raising():
    events = [
        _event(EventType.RELEASE, 0, "N"),
        _event(EventType.CROSSING, 1_000, "N"),
        _event(EventType.RELEASE, 2_000, "S"),
    ]

    results = reconstruct_event_sessions(events)

    assert len(results) == 1
    result = results[0]
    assert result.status == "insufficient_data"
    assert result.confidence == 0.0
    assert result.cycle is None
    assert result.phase_model is None
    assert result.event_count == 3
    assert result.error_reason



def test_long_session_splits_confirmed_100_to_120_second_regime():
    first = _synthetic_events(
        100.0,
        cycles=30,
        origin_ms=0,
    )
    second_origin = 30 * 100 * 1000
    second = _synthetic_events(
        120.0,
        cycles=30,
        origin_ms=second_origin,
    )

    regimes = split_event_session_into_regimes(
        first + second,
        regime_window_seconds=900.0,
        regime_step_seconds=300.0,
        regime_confirmation_windows=2,
        regime_period_tolerance_seconds=6.0,
        regime_min_cycle_confidence=0.3,
    )

    assert len(regimes) == 2
    assert regimes[0].end_timestamp_ms < regimes[1].start_timestamp_ms
    assert regimes[0].rolling_period_seconds is not None
    assert regimes[1].rolling_period_seconds is not None
    assert 92.0 <= regimes[0].rolling_period_seconds <= 108.0
    assert 112.0 <= regimes[1].rolling_period_seconds <= 128.0



def _schedule_events(
    *,
    cycles,
    origin_ms,
    ns_offsets,
    ew_offsets,
    period_s=120.0,
):
    events = []
    for cycle in range(cycles):
        base = origin_ms + int(cycle * period_s * 1000.0)
        for offset in ns_offsets:
            for approach in ("N", "S"):
                timestamp = base + int(offset * 1000.0)
                events.append(
                    _event(EventType.RELEASE, timestamp, approach)
                )
                events.append(
                    _event(EventType.CROSSING, timestamp + 500, approach)
                )
        for offset in ew_offsets:
            for approach in ("E", "W"):
                timestamp = base + int(offset * 1000.0)
                events.append(
                    _event(EventType.RELEASE, timestamp, approach)
                )
                events.append(
                    _event(EventType.CROSSING, timestamp + 500, approach)
                )
    return events


def test_raw_axis_signature_tracks_schedule_without_phase_discovery():
    events = _schedule_events(
        cycles=12,
        origin_ms=0,
        ns_offsets=(10, 20, 30, 40),
        ew_offsets=(60, 70, 80, 90, 100),
    )

    signature = _raw_axis_signature(
        events,
        cycle_seconds=120.0,
        anchor_timestamp_ms=0,
    )

    assert len(signature) == 60
    assert 1 in signature
    assert 2 in signature
    # The early cycle is NS-dominant and the late cycle is EW-dominant.
    assert signature[10] == 1
    assert signature[40] == 2


def test_same_cycle_phase_plan_change_creates_new_regime():
    first = _schedule_events(
        cycles=30,
        origin_ms=0,
        ns_offsets=(10, 20, 30, 40, 50, 60),
        ew_offsets=(75, 85, 95, 105),
    )
    second_origin = 30 * 120 * 1000
    second = _schedule_events(
        cycles=30,
        origin_ms=second_origin,
        ns_offsets=(10, 20, 30, 40),
        ew_offsets=(55, 65, 75, 85, 95, 105),
    )

    regimes = split_event_session_into_regimes(
        first + second,
        regime_window_seconds=900.0,
        regime_step_seconds=300.0,
        regime_confirmation_windows=2,
        regime_period_tolerance_seconds=6.0,
        regime_min_cycle_confidence=0.3,
    )

    assert len(regimes) == 2
    assert regimes[0].end_timestamp_ms < regimes[1].start_timestamp_ms
    assert all(
        regime.rolling_period_seconds is not None
        for regime in regimes
    )
    assert all(
        112.0 <= regime.rolling_period_seconds <= 128.0
        for regime in regimes
    )



def test_batch_model_quality_distinguishes_good_partial_and_insufficient():
    cycle = SimpleNamespace(
        estimate=SimpleNamespace(confidence=0.9)
    )

    def model(coverage, phase_confidence):
        return SimpleNamespace(
            cycle_coverage=coverage,
            phases=(
                SimpleNamespace(confidence=phase_confidence),
                SimpleNamespace(confidence=phase_confidence),
            ),
        )

    assert batch_model_quality(
        cycle,
        model(0.98, 0.9),
    ) == ("GOOD", ())

    partial_quality, partial_reasons = batch_model_quality(
        cycle,
        model(0.80, 0.8),
    )
    assert partial_quality == "PARTIAL"
    assert any(
        reason.startswith("phase_coverage=")
        for reason in partial_reasons
    )

    insufficient_quality, _ = batch_model_quality(
        cycle,
        model(0.55, 0.8),
    )
    assert insufficient_quality == "INSUFFICIENT"
