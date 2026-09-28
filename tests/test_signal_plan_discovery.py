from __future__ import annotations

import random

from app.core.models import EventType, TrajectoryEvent
from app.core.signal_plan_discovery import SignalPlanDiscovery


def _events() -> list[TrajectoryEvent]:
    rng = random.Random(42)
    schedule = {
        "E->W": (0.0, 30.0, 4),
        "W->E": (0.0, 30.0, 3),
        "N->S": (30.0, 80.0, 6),
        "N->E": (30.0, 50.0, 3),
        "E->N": (30.0, 50.0, 3),
        "S->N": (50.0, 80.0, 5),
    }
    events: list[TrajectoryEvent] = []
    for cycle in range(12):
        base = 100_000 + int(cycle * 80_000)
        for movement, (start, end, count) in schedule.items():
            approach, _ = movement.split("->", 1)
            for _ in range(count):
                timestamp_ms = base + int(
                    rng.uniform(start + 1.0, end - 1.0) * 1000
                )
                events.append(
                    TrajectoryEvent(
                        event_type=EventType.RELEASE,
                        timestamp_ms=timestamp_ms,
                        approach=approach,
                        movement=movement,
                        confidence=0.95,
                        quality="HIGH",
                    )
                )
    return sorted(events, key=lambda item: item.timestamp_ms)


def test_discovers_eighty_second_cycle_and_extra_sections() -> None:
    plan = SignalPlanDiscovery(
        bin_seconds=2.0,
        min_cycle_seconds=20.0,
        max_cycle_seconds=140.0,
        min_movement_events=6,
    ).discover(_events())

    assert 76.0 <= plan.cycle_seconds <= 84.0

    by_approach = {}
    for head in plan.signal_heads:
        by_approach.setdefault(head.approach, []).append(head)

    assert len(by_approach["N"]) == 2
    assert len(by_approach["E"]) == 2
    assert len(by_approach["S"]) == 1
    assert len(by_approach["W"]) == 1

    n_additional = [
        head for head in by_approach["N"] if head.additional
    ]
    e_additional = [
        head for head in by_approach["E"] if head.additional
    ]
    assert n_additional and n_additional[0].movement_ids == ("N->E",)
    assert e_additional and e_additional[0].movement_ids == ("E->N",)

    stages = list(plan.stages)
    assert len(stages) == 3
    assert stages[0].phase_start <= 4.0
    assert 26.0 <= stages[0].phase_end <= 34.0
    assert 26.0 <= stages[1].phase_start <= 34.0
    assert 46.0 <= stages[1].phase_end <= 54.0
    assert 46.0 <= stages[2].phase_start <= 54.0
    assert 76.0 <= stages[2].phase_end <= 84.0


def test_intersection_config_is_derived_from_plan() -> None:
    plan = SignalPlanDiscovery(
        bin_seconds=2.0,
        min_cycle_seconds=20.0,
        max_cycle_seconds=140.0,
        min_movement_events=6,
    ).discover(_events())

    config = plan.to_intersection_config()

    assert {head.id for head in config.signal_heads} == {
        "N_MAIN",
        "N_ADD_1",
        "S_MAIN",
        "E_MAIN",
        "E_ADD_1",
        "W_MAIN",
    }
    assert config.signal_head("E_ADD_1").additional is True
    assert config.signal_head("E_ADD_1").movement_ids == ("E->N",)
