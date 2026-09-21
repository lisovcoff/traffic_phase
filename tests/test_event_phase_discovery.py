from __future__ import annotations

import pytest

from app.core.event_phase_discovery import EventPhaseDiscovery, PhaseGroup
from app.core.models import EventType, TrajectoryEvent


def _event(event_type, timestamp_s, approach, confidence=1.0):
    return TrajectoryEvent(
        event_type=event_type,
        timestamp_ms=int(timestamp_s * 1000),
        approach=approach,
        movement=f"{approach}->x",
        confidence=confidence,
        quality="HIGH",
    )


def _events(cycle=120.0, repeats=6):
    result = []
    for repeat in range(repeats):
        base = repeat * cycle
        for offset, approach in (
            (10, "N"),
            (20, "S"),
            (70, "E"),
            (80, "W"),
        ):
            result.extend(
                (
                    _event(EventType.RELEASE, base + offset, approach),
                    _event(EventType.CROSSING, base + offset + 1, approach),
                )
            )
    return result


def test_event_model_discovers_two_opposing_green_intervals():
    result = EventPhaseDiscovery().discover(_events(), cycle_seconds=120.0)
    assert len(result.phases) == 2
    assert {phase.active_approaches for phase in result.phases} == {
        ("N", "S"),
        ("E", "W"),
    }
    assert result.cycle_coverage == 1.0
    assert result.overlap == 0.0
    assert all(0.0 <= phase.confidence <= 1.0 for phase in result.phases)


def test_support_and_contradiction_are_real_event_counts():
    # Put recurring E/W evidence directly inside the otherwise strong NS
    # interval. The optimizer should retain NS there, so those events are
    # counted as contradictory evidence for the NS phase.
    events = _events()
    for repeat in range(6):
        base = repeat * 120.0
        events.extend(
            (
                _event(EventType.CROSSING, base + 20.0, "E"),
                _event(EventType.RELEASE, base + 21.0, "E"),
            )
        )
    result = EventPhaseDiscovery().discover(events, cycle_seconds=120.0)
    assert sum(phase.supporting_event_count for phase in result.phases) > 0
    assert sum(phase.contradictory_event_count for phase in result.phases) > 0


def test_boundary_bins_do_not_overlap():
    result = EventPhaseDiscovery().discover(_events(repeats=5), cycle_seconds=120.0)
    covered = set()
    for phase in result.phases:
        start = int(phase.phase_start / 2)
        end = int(phase.phase_end / 2)
        indices = (
            set(range(start, end))
            if start < end
            else set(range(start, 60)) | set(range(0, end))
        )
        assert not covered.intersection(indices)
        covered.update(indices)
    assert len(covered) == 60


def test_stop_and_approach_events_do_not_create_phase_evidence():
    with pytest.raises(ValueError, match="no usable RELEASE/CROSSING events"):
        EventPhaseDiscovery().discover(
            [
                _event(EventType.APPROACH, 10, "N"),
                _event(EventType.STOP, 20, "N"),
            ],
            cycle_seconds=120.0,
        )


def test_low_confidence_events_can_be_filtered():
    events = _events(repeats=4)
    events.append(_event(EventType.RELEASE, 30.0, "E", confidence=0.1))
    result = EventPhaseDiscovery(min_event_confidence=0.5).discover(
        events,
        cycle_seconds=120.0,
    )
    assert result.phases


def test_empty_absolute_cycles_do_not_zero_median_phase_profile():
    # This models a daytime-only archive with a long gap between observed
    # periods.  Empty absolute cycles must not be interpreted as zero evidence
    # for every phase, otherwise their majority makes the complete median
    # profile zero and the phase optimizer falls back to its first 8-second
    # interval.
    events = []
    for repeat in (0, 1, 100, 101):
        base = repeat * 120.0
        for offset, approach in (
            (10, "N"),
            (20, "S"),
            (70, "E"),
            (80, "W"),
        ):
            events.extend(
                (
                    _event(EventType.RELEASE, base + offset, approach),
                    _event(EventType.CROSSING, base + offset + 1, approach),
                )
            )

    result = EventPhaseDiscovery().discover(events, cycle_seconds=120.0)
    profiles = {profile.group: profile for profile in result.profiles}

    assert profiles["NS"].cycle_count == 4
    assert profiles["NS"].values[5] > 0.0
    assert profiles["EW"].values[35] > 0.0
    phases = {
        phase.active_approaches: phase
        for phase in result.phases
    }
    assert phases[("N", "S")].phase_end != 8.0
    assert phases[("E", "W")].phase_start != 8.0


def test_phase_groups_are_extensible():
    discovery = EventPhaseDiscovery(
        groups=(
            PhaseGroup("NS", ("N", "S")),
            PhaseGroup("EW", ("E", "W")),
            PhaseGroup("TURN", ("T",)),
        )
    )
    assert [group.name for group in discovery.groups] == ["NS", "EW", "TURN"]


def _phase_duration(phase, cycle_seconds=120.0):
    duration = (phase.phase_end - phase.phase_start) % cycle_seconds
    return duration if duration > 0 else cycle_seconds


def test_phase_schedule_is_not_dominated_by_group_traffic_volume():
    # NS intentionally has much higher absolute event volume than EW, while
    # EW still provides recurring evidence in every cycle. Reliability must
    # saturate rather than reintroducing raw traffic-volume dominance.
    events = []
    for repeat in range(8):
        base = repeat * 120.0
        for offset in range(10, 50, 2):
            for _ in range(20):
                events.append(_event(EventType.RELEASE, base + offset, "N"))
        for offset in range(60, 100, 8):
            events.append(_event(EventType.RELEASE, base + offset, "E"))

    result = EventPhaseDiscovery().discover(events, cycle_seconds=120.0)
    profiles = {profile.group: profile for profile in result.profiles}
    durations = [_phase_duration(phase) for phase in result.phases]

    assert len(result.phases) == 2
    assert profiles["NS"].usable_event_count > profiles["EW"].usable_event_count * 20
    assert profiles["NS"].reliability == 1.0
    assert profiles["EW"].reliability == 1.0
    assert min(durations) >= 20.0
    assert max(durations) <= 100.0


def test_sparse_random_second_group_becomes_unknown_not_minimum_phase():
    events = []
    for repeat in range(10):
        base = repeat * 120.0
        for offset in range(10, 50, 4):
            events.append(_event(EventType.RELEASE, base + offset, "N"))

    # Only three isolated EW observations across ten otherwise observed
    # cycles. They must not create an artificial minimum-duration green.
    for timestamp in (67.0, 3 * 120.0 + 83.0, 8 * 120.0 + 71.0):
        events.append(_event(EventType.RELEASE, timestamp, "E"))

    result = EventPhaseDiscovery().discover(events, cycle_seconds=120.0)
    profiles = {profile.group: profile for profile in result.profiles}

    assert profiles["EW"].usable_event_count == 3
    assert profiles["EW"].observed_cycle_count == 3
    assert profiles["EW"].reliability < 0.2
    assert all(
        "E" not in phase.active_approaches
        and "W" not in phase.active_approaches
        for phase in result.phases
    )
    assert result.cycle_coverage < 1.0


def test_symmetric_two_phase_signal_keeps_high_group_reliability():
    result = EventPhaseDiscovery().discover(
        _events(repeats=8),
        cycle_seconds=120.0,
    )
    profiles = {profile.group: profile for profile in result.profiles}

    assert profiles["NS"].reliability == 1.0
    assert profiles["EW"].reliability == 1.0
    assert all(phase.confidence > 0.5 for phase in result.phases)


def test_reliability_ignores_empty_cycles_in_long_gaps():
    events = []
    for repeat in (0, 1, 100, 101):
        base = repeat * 120.0
        for offset, approach in (
            (10, "N"),
            (20, "S"),
            (70, "E"),
            (80, "W"),
        ):
            events.append(_event(EventType.RELEASE, base + offset, approach))

    result = EventPhaseDiscovery().discover(events, cycle_seconds=120.0)
    profiles = {profile.group: profile for profile in result.profiles}

    assert profiles["NS"].cycle_count == 4
    assert profiles["EW"].cycle_count == 4
    assert profiles["NS"].observed_cycle_count == 4
    assert profiles["EW"].observed_cycle_count == 4
    assert profiles["NS"].reliability == 1.0
    assert profiles["EW"].reliability == 1.0



def _staggered_video_like_events(repeats=12):
    result = []
    for repeat in range(repeats):
        base = repeat * 100.0
        for offset in range(2, 50, 4):
            result.append(_event(EventType.RELEASE, base + offset, "N"))
            result.append(_event(EventType.CROSSING, base + offset + 1, "N"))
        for offset in range(22, 50, 4):
            result.append(_event(EventType.RELEASE, base + offset, "S"))
            result.append(_event(EventType.CROSSING, base + offset + 1, "S"))
        for approach in ("E", "W"):
            for offset in range(56, 98, 4):
                result.append(
                    _event(EventType.RELEASE, base + offset, approach)
                )
                result.append(
                    _event(EventType.CROSSING, base + offset + 1, approach)
                )
    return result


def test_discovers_staggered_overlapping_approach_stages():
    result = EventPhaseDiscovery().discover(
        _staggered_video_like_events(),
        cycle_seconds=100.0,
    )

    active_sets = {
        phase.active_approaches
        for phase in result.phases
    }
    assert ("N",) in active_sets
    assert ("N", "S") in active_sets
    assert ("E", "W") in active_sets
    assert result.cycle_coverage < 1.0

    n_only = next(
        phase
        for phase in result.phases
        if phase.active_approaches == ("N",)
    )
    ns = next(
        phase
        for phase in result.phases
        if phase.active_approaches == ("N", "S")
    )
    ew = next(
        phase
        for phase in result.phases
        if phase.active_approaches == ("E", "W")
    )

    assert 14.0 <= _phase_duration(n_only, 100.0) <= 26.0
    assert 20.0 <= _phase_duration(ns, 100.0) <= 36.0
    assert 34.0 <= _phase_duration(ew, 100.0) <= 48.0


def test_simple_sparse_two_phase_case_remains_supported():
    result = EventPhaseDiscovery().discover(
        _events(cycle=120.0, repeats=8),
        cycle_seconds=120.0,
    )

    assert {
        phase.active_approaches
        for phase in result.phases
    } == {
        ("N", "S"),
        ("E", "W"),
    }
    assert result.cycle_coverage == 1.0
