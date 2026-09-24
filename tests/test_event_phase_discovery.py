from __future__ import annotations

import numpy as np
import pytest

from app.core.intersection_topology import (
    IntersectionTopology,
    SignalFamily,
)
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
    assert 0.90 <= result.cycle_coverage < 1.0
    assert result.boundary_recovered_fraction == 0.0
    assert result.boundary_suggested_fraction > 0.0
    assert result.boundary_recovery_applied is False
    assert result.boundary_recoveries

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
    # Boundary suggestions are diagnostic only; the authoritative phase
    # interval remains limited by direct recurring evidence.
    assert 34.0 <= _phase_duration(ew, 100.0) <= 56.0


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



def _stage_c1_candidate(
    *,
    approach,
    movement,
    start,
    end,
    repeatability=1.0,
    stability=0.95,
    events=120,
    cycles=20,
    score=0.9,
):
    return MovementActivationCandidate(
        approach=approach,
        movement=movement,
        phase_start=start,
        phase_end=end,
        repeatability=repeatability,
        stability=stability,
        usable_event_count=events,
        observed_cycle_count=cycles,
        score=score,
    )


def test_degenerate_full_cycle_movement_candidate_is_never_promoted():
    discovery = EventPhaseDiscovery()
    phases = (
        EventPhase(
            1,
            4.0,
            44.0,
            ("E", "W"),
            0.98,
            400,
            5,
            ("E", "W"),
        ),
        EventPhase(
            2,
            46.0,
            114.0,
            ("N", "S"),
            0.99,
            500,
            5,
            ("N", "S"),
        ),
    )
    candidate = _stage_c1_candidate(
        approach="W",
        movement="W->_S",
        start=0.0,
        end=0.0,
        repeatability=1.0,
        stability=1.0,
        events=61,
        cycles=10,
        score=1.0,
    )

    promoted = discovery._promote_movement_candidates(
        (candidate,),
        phases,
        cycle_seconds=120.0,
    )

    assert promoted == []


def test_chicherina_density_windows_inside_main_green_are_not_promoted():
    discovery = EventPhaseDiscovery()
    phases = (
        EventPhase(
            1,
            72.0,
            114.0,
            ("E", "W"),
            0.97,
            900,
            8,
            ("E", "W"),
        ),
        EventPhase(
            2,
            116.0,
            64.0,
            ("N", "S"),
            0.99,
            1200,
            8,
            ("N", "S"),
        ),
    )
    candidates = (
        _stage_c1_candidate(
            approach="E",
            movement="E->_W",
            start=66.0,
            end=96.0,
            repeatability=0.9677,
            stability=0.9211,
            events=355,
            cycles=30,
            score=0.9,
        ),
        _stage_c1_candidate(
            approach="W",
            movement="W->_E",
            start=64.0,
            end=82.0,
            repeatability=1.0,
            stability=0.935,
            events=200,
            cycles=30,
            score=0.9,
        ),
    )
    before = tuple(
        (
            phase.phase_start,
            phase.phase_end,
            phase.active_approaches,
        )
        for phase in phases
    )

    promoted = discovery._promote_movement_candidates(
        candidates,
        phases,
        cycle_seconds=120.0,
    )

    assert promoted == []
    assert tuple(
        (
            phase.phase_start,
            phase.phase_end,
            phase.active_approaches,
        )
        for phase in phases
    ) == before


def test_lenina_sverdlovsky_strong_distinct_boundaries_stay_promoted():
    discovery = EventPhaseDiscovery()
    phases = (
        EventPhase(
            1,
            32.0,
            50.0,
            ("N",),
            0.9091,
            484,
            34,
            ("N",),
        ),
        EventPhase(
            2,
            50.0,
            80.0,
            ("N", "S"),
            0.9694,
            1604,
            6,
            ("N", "S"),
        ),
        EventPhase(
            3,
            86.0,
            24.0,
            ("E", "W"),
            0.9783,
            1351,
            30,
            ("E", "W"),
        ),
    )
    candidates = (
        _stage_c1_candidate(
            approach="N",
            movement="N->_E",
            start=30.0,
            end=54.0,
            repeatability=1.0,
            stability=0.9711,
            events=242,
            cycles=36,
            score=0.8351,
        ),
        _stage_c1_candidate(
            approach="E",
            movement="E->_N",
            start=32.0,
            end=54.0,
            repeatability=0.8919,
            stability=0.9461,
            events=167,
            cycles=33,
            score=0.7588,
        ),
        _stage_c1_candidate(
            approach="E",
            movement="E->_E",
            start=98.0,
            end=18.0,
            repeatability=0.4595,
            stability=0.875,
            events=24,
            cycles=17,
            score=0.476,
        ),
    )

    promoted = discovery._promote_movement_candidates(
        candidates,
        phases,
        cycle_seconds=100.0,
    )

    assert {
        stage.movement
        for stage in promoted
    } == {
        "N->_E",
        "E->_N",
    }



def test_raw_axis_prior_restores_temporally_misplaced_main_movement():
    cycle = 120.0
    events = []
    for repeat in range(12):
        base = repeat * cycle
        for offset in (18.0, 30.0, 42.0, 54.0):
            events.extend(
                (
                    _event(
                        EventType.RELEASE,
                        base + offset,
                        "N",
                        movement="N->_S",
                    ),
                    _event(
                        EventType.RELEASE,
                        base + offset + 2.0,
                        "S",
                        movement="S->_N",
                    ),
                )
            )
        for offset in (76.0, 88.0, 100.0, 112.0):
            events.extend(
                (
                    _event(
                        EventType.RELEASE,
                        base + offset,
                        "E",
                        movement="E->_W",
                    ),
                    _event(
                        EventType.RELEASE,
                        base + offset + 2.0,
                        "W",
                        movement="W->_E",
                    ),
                )
            )
        # Strong, narrow secondary horizontal movements occur during NS.
        for offset in (34.0, 38.0, 42.0):
            events.extend(
                (
                    _event(
                        EventType.RELEASE,
                        base + offset,
                        "E",
                        movement="E->_N",
                    ),
                    _event(
                        EventType.RELEASE,
                        base + offset + 1.0,
                        "W",
                        movement="W->_S",
                    ),
                )
            )

    class MisplaceHorizontalMain(EventPhaseDiscovery):
        def _select_main_movement_events(
            self,
            selected,
            *,
            cycle_seconds,
            origin_timestamp_ms,
        ):
            _main, candidates = super()._select_main_movement_events(
                selected,
                cycle_seconds=cycle_seconds,
                origin_timestamp_ms=origin_timestamp_ms,
            )
            main = [
                event
                for event in selected
                if (
                    event.approach in {"N", "S"}
                    or event.movement in {"E->_N", "W->_S"}
                )
            ]
            return main, candidates

    result = MisplaceHorizontalMain().discover(
        events,
        cycle_seconds=cycle,
    )

    active_sets = {
        phase.active_approaches
        for phase in result.phases
    }
    assert ("N", "S") in active_sets
    assert ("E", "W") in active_sets
    assert result.cycle_coverage >= 0.70


def test_near_full_cycle_movement_candidate_stays_diagnostic():
    discovery = EventPhaseDiscovery()
    phases = (
        EventPhase(
            1,
            10.0,
            55.0,
            ("N", "S"),
            0.95,
            500,
            5,
            ("N", "S"),
        ),
        EventPhase(
            2,
            65.0,
            115.0,
            ("E", "W"),
            0.95,
            500,
            5,
            ("E", "W"),
        ),
    )
    candidate = _stage_c1_candidate(
        approach="S",
        movement="S->_W",
        start=20.0,
        end=110.0,
        repeatability=0.99,
        stability=0.95,
        events=400,
        cycles=80,
        score=0.95,
    )

    promoted = discovery._promote_movement_candidates(
        (candidate,),
        phases,
        cycle_seconds=120.0,
    )

    assert promoted == []



def test_boundary_recovery_fills_only_reliable_cross_family_gap():
    discovery = EventPhaseDiscovery()
    n_bins = 50
    stages = [
        ("N", "S") if index < 20
        else ()
        if index < 28
        else ("E", "W")
        for index in range(n_bins)
    ]
    coarse_axes = {
        "NS": np.asarray(
            [index < 24 for index in range(n_bins)],
            dtype=bool,
        ),
        "EW": np.asarray(
            [index >= 24 for index in range(n_bins)],
            dtype=bool,
        ),
    }
    raw_counts = np.zeros((12, 4, n_bins), dtype=int)
    for cycle in range(12):
        raw_counts[cycle, 0, 5] = 1
        raw_counts[cycle, 1, 10] = 1
        raw_counts[cycle, 2, 35] = 1
        raw_counts[cycle, 3, 40] = 1

    recovered, diagnostics, fraction = (
        discovery._recover_boundary_gaps(
            stages,
            coarse_axes=coarse_axes,
            raw_counts=raw_counts,
            observed_mask=np.ones(12, dtype=bool),
            movement_candidates=(),
            cycle_seconds=100.0,
        )
    )

    assert all(recovered)
    assert recovered[20:24] == [("N", "S")] * 4
    assert recovered[24:28] == [("E", "W")] * 4
    assert len(diagnostics) == 2
    assert fraction == 0.16


def test_boundary_recovery_preserves_internal_staggered_gap():
    discovery = EventPhaseDiscovery()
    n_bins = 50
    stages = [
        ("N",) if index < 10
        else ()
        if index < 14
        else ("N", "S")
        if index < 25
        else ("E", "W")
        for index in range(n_bins)
    ]
    coarse_axes = {
        "NS": np.asarray(
            [index < 25 for index in range(n_bins)],
            dtype=bool,
        ),
        "EW": np.asarray(
            [index >= 25 for index in range(n_bins)],
            dtype=bool,
        ),
    }
    raw_counts = np.ones((12, 4, n_bins), dtype=int)

    recovered, diagnostics, fraction = (
        discovery._recover_boundary_gaps(
            stages,
            coarse_axes=coarse_axes,
            raw_counts=raw_counts,
            observed_mask=np.ones(12, dtype=bool),
            movement_candidates=(),
            cycle_seconds=100.0,
        )
    )

    assert recovered[10:14] == [()] * 4
    assert diagnostics == []
    assert fraction == 0.0


def test_boundary_recovery_does_not_hide_distinct_movement_candidate():
    discovery = EventPhaseDiscovery()
    n_bins = 50
    stages = [
        ("N", "S") if index < 20
        else ()
        if index < 28
        else ("E", "W")
        for index in range(n_bins)
    ]
    coarse_axes = {
        "NS": np.asarray(
            [index < 24 for index in range(n_bins)],
            dtype=bool,
        ),
        "EW": np.asarray(
            [index >= 24 for index in range(n_bins)],
            dtype=bool,
        ),
    }
    raw_counts = np.ones((12, 4, n_bins), dtype=int)
    candidate = MovementActivationCandidate(
        approach="E",
        movement="E->_N",
        phase_start=42.0,
        phase_end=50.0,
        repeatability=0.9,
        stability=0.9,
        usable_event_count=80,
        observed_cycle_count=12,
        score=0.9,
    )

    recovered, diagnostics, fraction = (
        discovery._recover_boundary_gaps(
            stages,
            coarse_axes=coarse_axes,
            raw_counts=raw_counts,
            observed_mask=np.ones(12, dtype=bool),
            movement_candidates=(candidate,),
            cycle_seconds=100.0,
        )
    )

    assert recovered[20:28] == [()] * 8
    assert diagnostics == []
    assert fraction == 0.0



def _residual_movement_events(
    *,
    cycles: int = 20,
    movement_cycles: int = 16,
    conflicting_cycles: int = 0,
):
    events = []
    for cycle_index in range(movement_cycles):
        base_ms = cycle_index * 100_000
        for offset_s in (44.0, 48.0, 52.0):
            events.append(
                TrajectoryEvent(
                    event_type=EventType.RELEASE,
                    timestamp_ms=base_ms + int(offset_s * 1000),
                    approach="N",
                    movement="N->_E",
                    confidence=0.95,
                    quality="HIGH",
                )
            )
    for cycle_index in range(conflicting_cycles):
        base_ms = cycle_index * 100_000
        events.append(
            TrajectoryEvent(
                event_type=EventType.RELEASE,
                timestamp_ms=base_ms + 46_000,
                approach="E",
                movement="E->_W",
                confidence=0.95,
                quality="HIGH",
            )
        )
    return events


def test_residual_substage_can_promote_when_whole_candidate_is_too_weak():
    discovery = EventPhaseDiscovery()
    phases = (
        EventPhase(
            1,
            0.0,
            40.0,
            ("N",),
            0.95,
            500,
            5,
            ("N",),
        ),
        EventPhase(
            2,
            60.0,
            100.0,
            ("E", "W"),
            0.95,
            500,
            5,
            ("E", "W"),
        ),
    )
    candidate = MovementActivationCandidate(
        approach="N",
        movement="N->_E",
        phase_start=20.0,
        phase_end=60.0,
        repeatability=0.60,
        stability=0.70,
        usable_event_count=80,
        observed_cycle_count=20,
        score=0.64,
    )

    promoted, decisions = (
        discovery._promote_movement_candidates_with_decisions(
            (candidate,),
            phases,
            cycle_seconds=100.0,
            events=_residual_movement_events(),
            origin_timestamp_ms=0,
        )
    )

    assert len(promoted) == 1
    stage = promoted[0]
    assert stage.movement == "N->_E"
    assert stage.phase_start == 40.0
    assert stage.phase_end == 60.0
    assert stage.repeatability >= 0.75
    assert stage.stability >= 0.85
    assert stage.supporting_event_count >= 40

    decision = decisions[0]
    assert decision.promoted is True
    assert decision.promotion_mode == "residual"
    assert decision.reason == "residual_promoted"
    assert decision.residual_start == 40.0
    assert decision.residual_end == 60.0
    assert decision.residual_repeatability == 0.8
    assert decision.conflicting_event_ratio == 0.0


def test_residual_substage_is_rejected_when_conflicting_flow_is_present():
    discovery = EventPhaseDiscovery()
    phases = (
        EventPhase(
            1,
            0.0,
            40.0,
            ("N",),
            0.95,
            500,
            5,
            ("N",),
        ),
        EventPhase(
            2,
            60.0,
            100.0,
            ("E", "W"),
            0.95,
            500,
            5,
            ("E", "W"),
        ),
    )
    candidate = MovementActivationCandidate(
        approach="N",
        movement="N->_E",
        phase_start=20.0,
        phase_end=60.0,
        repeatability=0.60,
        stability=0.70,
        usable_event_count=80,
        observed_cycle_count=20,
        score=0.64,
    )

    promoted, decisions = (
        discovery._promote_movement_candidates_with_decisions(
            (candidate,),
            phases,
            cycle_seconds=100.0,
            events=_residual_movement_events(
                conflicting_cycles=16,
            ),
            origin_timestamp_ms=0,
        )
    )

    assert promoted == []
    decision = decisions[0]
    assert decision.promoted is False
    assert decision.reason == "conflicting_flow_present"
    assert decision.conflicting_event_count == 16
    assert decision.conflicting_cycle_count == 16
    assert decision.conflicting_event_ratio > 0.20


def test_discovery_exposes_movement_stage_decisions():
    result = EventPhaseDiscovery().discover(
        _movement_cluster_regression_events(),
        cycle_seconds=100.0,
    )

    assert result.movement_stage_decisions
    assert {
        item.movement
        for item in result.movement_stage_decisions
    } >= {
        item.movement
        for item in result.distinct_movement_candidates
    }
    assert all(
        item.reason
        for item in result.movement_stage_decisions
    )


def _movement_case_events(
    *,
    cycle=100.0,
    repeats=12,
    through_window=(50.0, 70.0),
    secondary_window=None,
    secondary_movement=None,
    secondary_repeats=None,
):
    events = []
    for repeat in range(repeats):
        base = repeat * cycle
        for offset in np.arange(through_window[0], through_window[1], 4.0):
            events.extend((
                _event(EventType.RELEASE, base + float(offset), "N", movement="N->_S"),
                _event(EventType.RELEASE, base + float(offset), "S", movement="S->_N"),
            ))
        if secondary_window and secondary_movement:
            sec_repeats = repeats if secondary_repeats is None else secondary_repeats
            if repeat >= sec_repeats:
                continue
            approach = secondary_movement.split("->", 1)[0]
            for offset in np.arange(secondary_window[0], secondary_window[1], 4.0):
                events.append(
                    _event(EventType.RELEASE, base + float(offset), approach, movement=secondary_movement)
                )
    return events


def test_movement_primary_through_only_preserves_default_ns_output():
    result = EventPhaseDiscovery().discover(_movement_case_events(), cycle_seconds=100.0)
    assert {phase.active_approaches for phase in result.phases} == {("N", "S")}
    assert result.movement_stages == ()


def test_protected_turn_becomes_a_secondary_movement_stage():
    result = EventPhaseDiscovery().discover(
        _movement_case_events(secondary_window=(28.0, 44.0), secondary_movement="N->_E"),
        cycle_seconds=100.0,
    )
    assert any(stage.movement == "N->_E" for stage in result.movement_stages)


def test_permissive_turn_can_activate_with_through_without_widening_phase():
    result = EventPhaseDiscovery().discover(
        _movement_case_events(secondary_window=(52.0, 68.0), secondary_movement="N->_E"),
        cycle_seconds=100.0,
    )
    n_s_stages = [phase for phase in result.phases if phase.active_approaches == ("N", "S")]
    assert n_s_stages
    assert max(_phase_duration(item, 100.0) for item in n_s_stages) <= 24.0
    assert result.movement_stages == ()


def test_multiple_compatible_movements_activate_in_same_primary_phase():
    events = _movement_case_events(secondary_window=(52.0, 68.0), secondary_movement="N->_E")
    events.extend(_movement_case_events(secondary_window=(52.0, 68.0), secondary_movement="N->_W"))
    discovery = EventPhaseDiscovery()
    selected, _candidates = discovery._select_main_movement_events(
        discovery._selected_events(events),
        cycle_seconds=100.0,
        origin_timestamp_ms=min(event.timestamp_ms for event in events),
    )
    assert {"N->_S", "N->_E", "N->_W"} <= {
        event.movement for event in selected if event.approach == "N"
    }


def test_sparse_movement_remains_unknown_and_does_not_create_stage():
    result = EventPhaseDiscovery().discover(
        _movement_case_events(
            secondary_window=(28.0, 44.0),
            secondary_movement="N->_E",
            secondary_repeats=3,
        ),
        cycle_seconds=100.0,
    )
    assert all(stage.movement != "N->_E" for stage in result.movement_stages)
    assert all(candidate.movement != "N->_E" for candidate in result.distinct_movement_candidates)


def test_conflicting_movements_do_not_overlap_as_allowed_stages():
    topology = IntersectionTopology(
        families=(
            SignalFamily("NS", ("N", "S")),
            SignalFamily("EW", ("E", "W")),
        ),
        family_conflicts=(("NS", "EW"),),
        movement_conflicts=(("N->_E", "E->_N"),),
    )
    phases = (
        EventPhase(1, 0.0, 30.0, ("N",), 0.95, 100, 1, ("N",)),
        EventPhase(2, 70.0, 100.0, ("E",), 0.95, 100, 1, ("E",)),
    )
    candidates = (
        MovementActivationCandidate("N", "N->_E", 40.0, 60.0, 0.95, 0.95, 80, 12, 0.9),
        MovementActivationCandidate("E", "E->_N", 40.0, 60.0, 0.94, 0.94, 80, 12, 0.89),
    )
    promoted = EventPhaseDiscovery(topology=topology)._promote_movement_candidates(
        candidates,
        phases,
        cycle_seconds=100.0,
    )
    assert len(promoted) == 1


def test_missing_movement_cannot_become_primary_phase_evidence():
    events = _movement_case_events()
    for repeat in range(12):
        events.append(
            TrajectoryEvent(
                event_type=EventType.RELEASE,
                timestamp_ms=int((repeat * 100.0 + 30.0) * 1000),
                approach="N",
                movement="",
                confidence=1.0,
                quality="HIGH",
            )
        )
    result = EventPhaseDiscovery().discover(events, cycle_seconds=100.0)
    assert {phase.active_approaches for phase in result.phases} == {("N", "S")}
    assert all(candidate.movement != "N->UNKNOWN" for candidate in result.distinct_movement_candidates)
