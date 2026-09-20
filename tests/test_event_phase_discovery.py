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
