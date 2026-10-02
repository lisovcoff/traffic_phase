from __future__ import annotations

import itertools

from app.core.v10.automatic_physical import infer_physical_signal_plan
from app.core.v10.semantic_mapping import (
    PhaseSpec,
    build_phase_specs_from_signal_plan_dict,
    map_v9_to_physical,
    signal_state_at,
)


LENINA_PHASES = (
    PhaseSpec("A", frozenset({"N->S", "N->E", "E->N"}), 31.0),
    PhaseSpec("B", frozenset({"N->S", "S->N"}), 47.0),
    PhaseSpec(
        "C",
        frozenset({"E->W", "W->E", "W->N"}),
        21.0,
        frozenset({"W->N"}),
    ),
)

LENINA_ACTIVITY = [
    ("N->S", {"PHASE_A": 0.45, "PHASE_B": 0.24, "PHASE_C": 0.01}),
    ("S->N", {"PHASE_A": 0.02, "PHASE_B": 0.53, "PHASE_C": 0.05}),
    ("E->W", {"PHASE_A": 0.02, "PHASE_B": 0.01, "PHASE_C": 0.16}),
    ("W->E", {"PHASE_A": 0.01, "PHASE_B": 0.01, "PHASE_C": 0.18}),
    ("N->E", {"PHASE_A": 0.11, "PHASE_B": 0.02, "PHASE_C": 0.01}),
    ("E->N", {"PHASE_A": 0.09, "PHASE_B": 0.01, "PHASE_C": 0.01}),
]


def _lenina_result(perm: tuple[int, int, int]) -> dict[str, object]:
    names = ["PHASE_A", "PHASE_B", "PHASE_C"]
    physical_order = ("C", "A", "B")
    old_to_new = {index: perm[index] for index in range(3)}
    new_names = [names[old] for old in perm]

    duration_by_physical = {"A": 31.0, "B": 47.0, "C": 21.0}
    durations = {
        new_names[i]: duration_by_physical[physical_order[i]]
        for i in range(3)
    }

    segments = []
    cursor = 0.0
    for old_index, physical in enumerate(physical_order):
        new_index = old_to_new[old_index]
        duration = duration_by_physical[physical]
        segments.append([cursor, cursor + duration, new_index])
        cursor += duration

    physical_activity = {
        "C": {"E->W": 0.16, "W->E": 0.18, "N->S": 0.01},
        "A": {"N->S": 0.45, "N->E": 0.11, "E->N": 0.09},
        "B": {"N->S": 0.24, "S->N": 0.53},
    }
    movements = sorted(set().union(*(values.keys() for values in physical_activity.values())))
    activity = []
    for movement in movements:
        row = {"stream": movement, "event_probability_by_phase": {}}
        for old_index, physical in enumerate(physical_order):
            row["event_probability_by_phase"][new_names[old_index]] = physical_activity[physical].get(movement, 0.01)
        activity.append(row)

    return {
        "schedule": {
            "phase_names": new_names,
            "phase_count": 3,
            "period_s": 99.0,
            "baseline_duration_targets_s": durations,
            "baseline_segments": segments,
            "stream_activity_by_phase": activity,
        }
    }


def test_lenina_mapping_survives_all_anonymous_relabels() -> None:
    for perm in itertools.permutations(range(3)):
        result = _lenina_result(perm)
        mapped = map_v9_to_physical(result, LENINA_PHASES, duration_weight=0.95)
        expected = {
            result["schedule"]["phase_names"][0]: "C",
            result["schedule"]["phase_names"][1]: "A",
            result["schedule"]["phase_names"][2]: "B",
        }
        assert mapped.mapping == expected


def test_four_phase_equal_duration_uses_movement_signature() -> None:
    physical = (
        PhaseSpec("P1_NS_LEFT", frozenset({"N->E", "S->W"}), 25.0),
        PhaseSpec("P2_NS_THROUGH", frozenset({"N->S", "S->N"}), 25.0),
        PhaseSpec("P3_EW_LEFT", frozenset({"E->S", "W->N"}), 25.0),
        PhaseSpec("P4_EW_THROUGH", frozenset({"E->W", "W->E"}), 25.0),
    )
    phases = [
        physical[2],
        physical[0],
        physical[3],
        physical[1],
    ]
    names = ["PHASE_A", "PHASE_B", "PHASE_C", "PHASE_D"]
    activity = []
    for movement in sorted(set().union(*(phase.green_movements for phase in physical))):
        values = {}
        for index, name in enumerate(names):
            values[name] = 0.90 if movement in phases[index].green_movements else 0.01
        activity.append({"stream": movement, "event_probability_by_phase": values})

    result = {
        "schedule": {
            "phase_names": names,
            "phase_count": 4,
            "period_s": 100.0,
            "baseline_duration_targets_s": {name: 25.0 for name in names},
            "baseline_segments": [
                [0.0, 25.0, 0], [25.0, 50.0, 1],
                [50.0, 75.0, 2], [75.0, 100.0, 3],
            ],
            "stream_activity_by_phase": activity,
        }
    }
    mapped = map_v9_to_physical(result, physical, duration_weight=0.0)
    assert mapped.mapping == {
        "PHASE_A": "P3_EW_LEFT",
        "PHASE_B": "P1_NS_LEFT",
        "PHASE_C": "P4_EW_THROUGH",
        "PHASE_D": "P2_NS_THROUGH",
    }


def test_physical_state_does_not_leak_ns_through_into_lenina_c() -> None:
    result = _lenina_result((0, 1, 2))
    mapped = map_v9_to_physical(result, LENINA_PHASES, duration_weight=0.95)
    state = signal_state_at(result, 60.0, LENINA_PHASES, mapped.mapping)
    assert state["phase"] == "B"
    assert "N->S" in state["green_movements"]

    state_c = signal_state_at(result, 10.0, LENINA_PHASES, mapped.mapping)
    assert state_c["phase"] == "C"
    assert "N->S" not in state_c["green_movements"]
    assert "W->N" in state_c["green_movements"]


def test_signal_plan_dict_becomes_physical_catalog() -> None:
    plan = {
        "cycle_seconds": 100.0,
        "stages": [
            {
                "stage_id": 1,
                "phase_start": 0.0,
                "phase_end": 30.0,
                "active_movements": ["N->S", "S->N"],
            },
            {
                "stage_id": 2,
                "phase_start": 30.0,
                "phase_end": 100.0,
                "active_movements": ["E->W", "W->E"],
            },
        ],
    }
    specs = build_phase_specs_from_signal_plan_dict(plan)
    assert [spec.name for spec in specs] == ["STAGE_1", "STAGE_2"]
    assert specs[0].duration_s == 30.0
    assert specs[1].green_movements == frozenset({"E->W", "W->E"})


def test_automatic_physical_plan_preserves_shared_straight_movement() -> None:
    result = _lenina_result((0, 1, 2))
    plan = infer_physical_signal_plan(result)

    assert plan["enabled"] is True
    assert plan["mapping"] == {
        "PHASE_A": "EW_THROUGH",
        "PHASE_B": "NS_TURN",
        "PHASE_C": "NS_THROUGH",
    }

    by_name = {phase["name"]: phase for phase in plan["phases"]}
    assert set(by_name["NS_TURN"]["green_movements"]) == {
        "N->S", "N->E", "E->N"
    }
    assert set(by_name["NS_TURN"]["additional_movements"]) == {
        "N->E", "E->N"
    }
    assert set(by_name["NS_THROUGH"]["green_movements"]) == {
        "N->S", "S->N"
    }
    assert by_name["NS_THROUGH"]["additional_movements"] == []

    # The supplied Lenina V9 activity table has no W->N stream evidence.
    # Automatic inference must not manufacture an unseen movement.
    assert "W->N" not in plan["topology"]["W"]["arrows"]
    assert plan["inference"]["unobserved_movements_are_not_invented"] is True
    assert [
        (row["name"], row["phase_start"], row["phase_end"])
        for row in plan["stages"]
    ] == [
        ("EW_THROUGH", 0.0, 21.0),
        ("NS_TURN", 21.0, 52.0),
        ("NS_THROUGH", 52.0, 99.0),
    ]


def test_automatic_physical_plan_handles_turn_only_four_phase_catalog() -> None:
    names = ["PHASE_A", "PHASE_B", "PHASE_C", "PHASE_D"]
    physical = [
        ("NS_LEFT", {"N->E", "S->W"}, 18.0),
        ("NS_THROUGH", {"N->S", "S->N"}, 32.0),
        ("EW_LEFT", {"E->S", "W->N"}, 18.0),
        ("EW_THROUGH", {"E->W", "W->E"}, 32.0),
    ]
    order = [2, 0, 3, 1]
    activity = []
    movements = sorted(set().union(*(items for _, items, _ in physical)))
    for movement in movements:
        activity.append(
            {
                "stream": movement,
                "event_probability_by_phase": {
                    name: (0.9 if movement in physical[order[index]][1] else 0.01)
                    for index, name in enumerate(names)
                },
            }
        )

    durations = {
        names[index]: physical[order[index]][2]
        for index in range(4)
    }
    result = {
        "schedule": {
            "phase_names": names,
            "phase_count": 4,
            "period_s": 100.0,
            "baseline_duration_targets_s": durations,
            "baseline_segments": [
                [0.0, 18.0, 0],
                [18.0, 36.0, 1],
                [36.0, 68.0, 2],
                [68.0, 100.0, 3],
            ],
            "stream_activity_by_phase": activity,
        }
    }

    plan = infer_physical_signal_plan(result)

    assert {
        phase["name"]: set(phase["green_movements"])
        for phase in plan["phases"]
    } == {
        "EW_TURN": {"E->S", "W->N"},
        "NS_TURN": {"N->E", "S->W"},
        "EW_THROUGH": {"E->W", "W->E"},
        "NS_THROUGH": {"N->S", "S->N"},
    }


def test_automatic_physical_plan_rejects_noncompass_streams() -> None:
    result = {
        "schedule": {
            "phase_names": ["PHASE_A", "PHASE_B"],
            "phase_count": 2,
            "period_s": 80.0,
            "baseline_duration_targets_s": {
                "PHASE_A": 40.0,
                "PHASE_B": 40.0,
            },
            "stream_activity_by_phase": [
                {
                    "stream": "foo->bar",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.9,
                        "PHASE_B": 0.01,
                    },
                }
            ],
            "baseline_segments": [
                [0.0, 40.0, 0],
                [40.0, 80.0, 1],
            ],
        }
    }

    try:
        infer_physical_signal_plan(result)
    except ValueError as exc:
        assert "canonical N/S/E/W" in str(exc)
    else:
        raise AssertionError("non-compass movement must not become physical")
