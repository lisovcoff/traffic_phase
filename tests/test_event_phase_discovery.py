from __future__ import annotations

import pytest

from app.core.event_phase_discovery import (
    EventPhase,
    EventPhaseDiscovery,
    MovementActivationCandidate,
    PhaseGroup,
)
from app.core.models import EventType, TrajectoryEvent


def _event(
    event_type,
    timestamp_s,
    approach,
    confidence=1.0,
    movement=None,
):
    return TrajectoryEvent(
        event_type=event_type,
        timestamp_ms=int(timestamp_s * 1000),
        approach=approach,
        movement=movement or f"{approach}->x",
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



def _movement_cluster_regression_events(repeats=12):
    events = []
    for repeat in range(repeats):
        base = repeat * 100.0

        for offset in range(30, 82, 4):
            events.extend(
                (
                    _event(
                        EventType.RELEASE,
                        base + offset,
                        "N",
                        movement="N->_S",
                    ),
                    _event(
                        EventType.CROSSING,
                        base + offset + 1,
                        "N",
                        movement="N->_S",
                    ),
                )
            )

        # Strong recurring N turn substage inside the wider N main
        # approach interval.
        for offset in range(30, 54, 4):
            events.append(
                _event(
                    EventType.RELEASE,
                    base + offset,
                    "N",
                    movement="N->_E",
                )
            )

        for offset in range(50, 84, 4):
            events.extend(
                (
                    _event(
                        EventType.RELEASE,
                        base + offset,
                        "S",
                        movement="S->_N",
                    ),
                    _event(
                        EventType.CROSSING,
                        base + offset + 1,
                        "S",
                        movement="S->_N",
                    ),
                )
            )

        for offset in list(range(82, 100, 4)) + list(range(0, 30, 4)):
            events.extend(
                (
                    _event(
                        EventType.RELEASE,
                        base + offset,
                        "E",
                        movement="E->_W",
                    ),
                    _event(
                        EventType.CROSSING,
                        base + offset + 1,
                        "E",
                        movement="E->_W",
                    ),
                )
            )

        # Strong and recurring, but temporally distinct secondary movement.
        # It must be retained as a candidate without widening main E green.
        for offset in range(34, 50, 4):
            events.append(
                _event(
                    EventType.RELEASE,
                    base + offset,
                    "E",
                    movement="E->_N",
                )
            )

        for offset in list(range(84, 100, 4)) + list(range(0, 30, 4)):
            events.extend(
                (
                    _event(
                        EventType.RELEASE,
                        base + offset,
                        "W",
                        movement="W->_E",
                    ),
                    _event(
                        EventType.CROSSING,
                        base + offset + 1,
                        "W",
                        movement="W->_E",
                    ),
                )
            )
    return events


def test_secondary_movement_does_not_widen_main_approach_activation():
    events = _movement_cluster_regression_events()
    discovery = EventPhaseDiscovery()

    profiles, evidence, counts = discovery.build_profiles(
        events,
        cycle_seconds=100.0,
    )
    masks = discovery._independent_activation_masks(
        evidence,
        counts,
    )
    by_group = {
        group.name: masks[index]
        for index, group in enumerate(discovery.groups)
    }

    e_bins = [
        index * discovery.bin_seconds
        for index, active in enumerate(by_group["E"])
        if active
    ]
    assert e_bins
    # Main E is the wrap-around straight movement. The secondary 34-50 s
    # turn must not extend the E approach mask into the N-only window.
    assert not any(34.0 <= value < 50.0 for value in e_bins)


def test_distinct_secondary_movement_is_preserved_as_candidate():
    result = EventPhaseDiscovery().discover(
        _movement_cluster_regression_events(),
        cycle_seconds=100.0,
    )

    candidate = next(
        item
        for item in result.distinct_movement_candidates
        if item.movement == "E->_N"
    )

    assert candidate.approach == "E"
    assert candidate.repeatability >= 0.9
    assert candidate.stability >= 0.8
    assert 30.0 <= candidate.phase_start <= 38.0
    assert 48.0 <= candidate.phase_end <= 54.0


def test_secondary_turn_no_longer_destroys_n_only_stage():
    result = EventPhaseDiscovery().discover(
        _movement_cluster_regression_events(),
        cycle_seconds=100.0,
    )
    active_sets = {
        phase.active_approaches
        for phase in result.phases
    }

    assert ("N",) in active_sets
    assert ("N", "S") in active_sets
    assert ("E", "W") in active_sets

    n_only = next(
        phase
        for phase in result.phases
        if phase.active_approaches == ("N",)
    )
    assert 12.0 <= _phase_duration(n_only, 100.0) <= 24.0


def test_weak_secondary_movement_does_not_create_candidate():
    events = _movement_cluster_regression_events()
    events.extend(
        (
            _event(
                EventType.CROSSING,
                36.0,
                "E",
                movement="E->_E",
            ),
            _event(
                EventType.CROSSING,
                38.0,
                "E",
                movement="E->_E",
            ),
        )
    )

    result = EventPhaseDiscovery().discover(
        events,
        cycle_seconds=100.0,
    )

    assert all(
        item.movement != "E->_E"
        for item in result.distinct_movement_candidates
    )



def test_strong_distinct_movements_are_promoted_conservatively():
    result = EventPhaseDiscovery().discover(
        _movement_cluster_regression_events(),
        cycle_seconds=100.0,
    )

    promoted = {
        stage.movement: stage
        for stage in result.movement_stages
    }

    assert {"N->_E", "E->_N"} <= set(promoted)
    assert promoted["N->_E"].repeatability >= 0.9
    assert promoted["N->_E"].stability >= 0.85
    assert promoted["N->_E"].supporting_event_count >= 50
    assert promoted["E->_N"].repeatability >= 0.75
    assert promoted["E->_N"].stability >= 0.85
    assert all(stage.confidence >= 0.8 for stage in promoted.values())


def test_weak_real_like_candidate_stays_diagnostic_not_signal_stage():
    discovery = EventPhaseDiscovery()
    phases = (
        EventPhase(
            1,
            32.0,
            50.0,
            ("N",),
            0.9,
            100,
            2,
            ("N",),
        ),
        EventPhase(
            2,
            50.0,
            80.0,
            ("N", "S"),
            0.9,
            100,
            2,
            ("N", "S"),
        ),
        EventPhase(
            3,
            86.0,
            24.0,
            ("E", "W"),
            0.9,
            100,
            2,
            ("E", "W"),
        ),
    )
    weak = MovementActivationCandidate(
        approach="E",
        movement="E->_E",
        phase_start=98.0,
        phase_end=18.0,
        repeatability=0.4595,
        stability=0.875,
        usable_event_count=24,
        observed_cycle_count=17,
        score=0.476,
    )

    promoted = discovery._promote_movement_candidates(
        (weak,),
        phases,
        cycle_seconds=100.0,
    )

    assert promoted == []
    assert weak.movement == "E->_E"


def test_movement_promotion_does_not_change_main_approach_stages():
    result = EventPhaseDiscovery().discover(
        _movement_cluster_regression_events(),
        cycle_seconds=100.0,
    )

    assert {
        phase.active_approaches
        for phase in result.phases
    } == {
        ("N",),
        ("N", "S"),
        ("E", "W"),
    }
    assert result.movement_stages


def test_simple_two_phase_case_has_no_movement_specific_stages():
    result = EventPhaseDiscovery().discover(
        _events(cycle=120.0, repeats=8),
        cycle_seconds=120.0,
    )

    assert result.movement_stages == ()
    assert result.distinct_movement_candidates == ()
