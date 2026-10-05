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



def _two_phase_27_02_profile() -> dict[str, object]:
    return {
        "schedule": {
            "phase_names": ["PHASE_A", "PHASE_B", "PHASE_C"],
            "phase_count": 3,
            "period_s": 99.94684405367033,
            "baseline_duration_targets_s": {
                "PHASE_A": 50.37978731678868,
                "PHASE_B": 20.3512590382049,
                "PHASE_C": 29.215797698676624,
            },
            "baseline_segments": [
                [0.0, 8.469354696672433, 2],
                [8.469354696672433, 58.84914201346116, 0],
                [58.84914201346116, 79.200401051666, 1],
                [79.200401051666, 99.94684405367033, 2],
            ],
            "stream_activity_by_phase": [
                {"stream": "S->N", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.01, "PHASE_C": 0.33070501685142517}},
                {"stream": "E->W", "event_probability_by_phase": {"PHASE_A": 0.13586054742336273, "PHASE_B": 0.01, "PHASE_C": 0.01}},
                {"stream": "N->S", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.1608635038137436, "PHASE_C": 0.01}},
                {"stream": "N->E", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.10376044362783432, "PHASE_C": 0.01}},
                {"stream": "E->N", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.07172702252864838, "PHASE_C": 0.01}},
                {"stream": "W->E", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.01, "PHASE_C": 0.01}},
            ],
        }
    }


def _two_phase_05_10_profile() -> dict[str, object]:
    return {
        "schedule": {
            "phase_names": ["PHASE_A", "PHASE_B", "PHASE_C"],
            "phase_count": 3,
            "period_s": 99.87838859459997,
            "baseline_duration_targets_s": {
                "PHASE_A": 32.4002925493908,
                "PHASE_B": 33.334452446835485,
                "PHASE_C": 34.14364359837367,
            },
            "baseline_segments": [
                [0.0, 24.847770271250585, 0],
                [24.847770271250585, 58.18222271808613, 1],
                [58.18222271808613, 92.32586631645977, 2],
            ],
            "stream_activity_by_phase": [
                {"stream": "W->E", "event_probability_by_phase": {"PHASE_A": 0.29194915294647217, "PHASE_B": 0.034583333879709244, "PHASE_C": 0.01}},
                {"stream": "N->S", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.01, "PHASE_C": 0.13788869976997375}},
                {"stream": "E->W", "event_probability_by_phase": {"PHASE_A": 0.0478813573718071, "PHASE_B": 0.06791666895151138, "PHASE_C": 0.01}},
                {"stream": "E->S", "event_probability_by_phase": {"PHASE_A": 0.012288135476410389, "PHASE_B": 0.094583332538604, "PHASE_C": 0.01}},
                {"stream": "S->N", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.01, "PHASE_C": 0.01}},
            ],
        }
    }


def test_automatic_physical_plan_keeps_two_phase_27_02_as_ns_ew() -> None:
    plan = infer_physical_signal_plan(_two_phase_27_02_profile())
    assert plan["inference"]["physical_phase_count"] == 2
    assert plan["mapping"] == {
        "PHASE_A": "EW_THROUGH",
        "PHASE_B": "NS_THROUGH",
        "PHASE_C": "NS_THROUGH",
    }
    assert plan["topology"]["E"]["arrows"] == []
    assert all(not phase["additional_movements"] for phase in plan["phases"])


def test_automatic_physical_plan_keeps_two_phase_05_10_as_ns_ew() -> None:
    plan = infer_physical_signal_plan(_two_phase_05_10_profile())
    assert plan["inference"]["physical_phase_count"] == 2
    assert plan["mapping"] == {
        "PHASE_A": "EW_THROUGH",
        "PHASE_B": "EW_THROUGH",
        "PHASE_C": "NS_THROUGH",
    }
    assert plan["topology"]["E"]["arrows"] == []
    assert all(not phase["additional_movements"] for phase in plan["phases"])


def test_automatic_physical_plan_recovers_weak_selective_phase_and_heads() -> None:
    result = {
        "analysis_base_timestamp_ms": 1100.0,
        "recording_start_timestamp_ms": 1000.0,
        "schedule": {
            "phase_names": ["PHASE_A", "PHASE_B", "PHASE_C"],
            "phase_count": 3,
            "period_s": 100.0,
            "baseline_duration_targets_s": {
                "PHASE_A": 20.0,
                "PHASE_B": 30.0,
                "PHASE_C": 50.0,
            },
            "baseline_segments": [
                [0.0, 20.0, 2],
                [20.0, 50.0, 0],
                [50.0, 100.0, 1],
            ],
            "stream_activity_by_phase": [
                {
                    "stream": "E->W",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.037,
                    },
                },
                {
                    "stream": "W->E",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "N->S",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.173,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "N->E",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.059,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "E->N",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.031,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "S->N",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.255,
                        "PHASE_C": 0.01,
                    },
                },
            ],
        },
    }

    plan = infer_physical_signal_plan(result)

    assert plan["enabled"] is True
    assert plan["time_offset_s"] == 0.1
    assert plan["timing"]["phase_anchor_model_s"] == 0.1
    assert plan["timing"]["phase_anchor_physical_s"] == 0.1
    assert plan["timing"]["startup_lost_s"] == 0.0

    by_name = {phase["name"]: phase for phase in plan["phases"]}
    assert set(by_name["EW_THROUGH"]["green_movements"]) == {
        "E->W",
        "W->E",
    }
    assert set(by_name["NS_TURN"]["green_movements"]) == {
        "N->S",
        "N->E",
        "E->N",
    }

    ew_heads = by_name["EW_THROUGH"]["heads"]
    assert ew_heads["E"]["main"] == "GREEN"
    assert ew_heads["W"]["main"] == "GREEN"

    turn_heads = by_name["NS_TURN"]["heads"]
    assert turn_heads["N"]["main"] == "GREEN"
    assert turn_heads["N"]["arrows"]["N->E"] == "GREEN"
    assert turn_heads["E"]["arrows"]["E->N"] == "GREEN"


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


def test_automatic_physical_plan_restores_shared_ns_straight_when_v9_splits_it() -> None:
    # Reproduces the visual failure: V9 attributes S->N to the NS-through
    # phase while N->S is strongest in the separate NS-turn phase. The
    # physical NS-through signal must still open both straight approaches.
    names = ["PHASE_A", "PHASE_B", "PHASE_C"]
    result = {
        "schedule": {
            "phase_names": names,
            "phase_count": 3,
            "period_s": 79.9,
            "baseline_duration_targets_s": {
                "PHASE_A": 8.8,
                "PHASE_B": 50.1,
                "PHASE_C": 21.0,
            },
            "baseline_segments": [
                [0.0, 8.8, 0],
                [8.8, 58.9, 1],
                [58.9, 79.9, 2],
            ],
            "stream_activity_by_phase": [
                {
                    "stream": "N->S",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.02,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.24,
                    },
                },
                {
                    "stream": "S->N",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.53,
                        "PHASE_B": 0.05,
                        "PHASE_C": 0.02,
                    },
                },
                {
                    "stream": "E->W",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.16,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "W->E",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.18,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "N->E",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.11,
                    },
                },
                {
                    "stream": "E->N",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.09,
                    },
                },
            ],
        }
    }

    plan = infer_physical_signal_plan(result)
    by_name = {phase["name"]: phase for phase in plan["phases"]}

    assert plan["mapping"] == {
        "PHASE_A": "NS_THROUGH",
        "PHASE_B": "EW_THROUGH",
        "PHASE_C": "NS_TURN",
    }
    assert set(by_name["NS_THROUGH"]["green_movements"]) == {
        "N->S",
        "S->N",
    }
    assert set(by_name["NS_TURN"]["green_movements"]) == {
        "N->S",
        "N->E",
        "E->N",
    }


def test_automatic_physical_plan_recovers_weak_reciprocal_turn():
    result = {
        "schedule": {
            "phase_names": ["PHASE_A", "PHASE_B", "PHASE_C"],
            "phase_count": 3,
            "period_s": 120.0,
            "baseline_duration_targets_s": {
                "PHASE_A": 50.0,
                "PHASE_B": 25.0,
                "PHASE_C": 45.0,
            },
            "baseline_segments": [
                [0.0, 50.0, 0],
                [50.0, 75.0, 1],
                [75.0, 120.0, 2],
            ],
            "stream_activity_by_phase": [
                {
                    "stream": "N->S",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.24,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "S->N",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.53,
                    },
                },
                {
                    "stream": "E->W",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.16,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "W->E",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.18,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "N->E",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.12,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "E->N",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.06,
                        "PHASE_C": 0.01,
                    },
                },
            ],
        }
    }

    plan = infer_physical_signal_plan(result)
    by_name = {phase["name"]: phase for phase in plan["phases"]}

    assert plan["mapping"]["PHASE_B"] == "NS_TURN"
    assert set(by_name["NS_TURN"]["green_movements"]) == {
        "N->E",
        "E->N",
        "N->S",
    }
    assert set(by_name["NS_TURN"]["additional_movements"]) == {
        "N->E",
        "E->N",
    }


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


def test_automatic_physical_plan_merges_adjacent_stages_by_head_configuration() -> None:
    names = ["PHASE_A", "PHASE_B", "PHASE_C"]
    result = {
        "schedule": {
            "phase_names": names,
            "phase_count": 3,
            "period_s": 100.0,
            "baseline_duration_targets_s": {
                "PHASE_A": 20.0,
                "PHASE_B": 20.0,
                "PHASE_C": 60.0,
            },
            "baseline_segments": [
                [0.0, 20.0, 0],
                [20.0, 40.0, 1],
                [40.0, 100.0, 2],
            ],
            "stream_activity_by_phase": [
                {
                    "stream": "N->S",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.90,
                        "PHASE_B": 0.88,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "S->N",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.90,
                        "PHASE_B": 0.88,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "E->W",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.90,
                    },
                },
                {
                    "stream": "W->E",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.90,
                    },
                },
            ],
        }
    }

    plan = infer_physical_signal_plan(result)

    assert plan["inference"]["physical_phase_count"] == 2
    assert [
        (stage["name"], stage["phase_start"], stage["phase_end"])
        for stage in plan["stages"]
    ] == [
        ("NS_THROUGH", 0.0, 40.0),
        ("EW_THROUGH", 40.0, 100.0),
    ]
    assert plan["stages"][0]["heads"]["N"]["main"] == "GREEN"
    assert plan["stages"][0]["heads"]["E"]["main"] == "RED"
    assert plan["stages"][1]["heads"]["N"]["main"] == "RED"
    assert plan["stages"][1]["heads"]["E"]["main"] == "GREEN"



def test_automatic_physical_plan_keeps_directional_ns_split_distinct() -> None:
    names = ["PHASE_A", "PHASE_B", "PHASE_C"]
    result = {
        "schedule": {
            "phase_names": names,
            "phase_count": 3,
            "period_s": 100.0,
            "baseline_duration_targets_s": {
                "PHASE_A": 30.0,
                "PHASE_B": 30.0,
                "PHASE_C": 40.0,
            },
            "baseline_segments": [
                [0.0, 30.0, 0],
                [30.0, 60.0, 1],
                [60.0, 100.0, 2],
            ],
            "stream_activity_by_phase": [
                {
                    "stream": "E->W",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.20,
                    },
                },
                {
                    "stream": "W->E",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.20,
                    },
                },
                {
                    "stream": "N->S",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.20,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "S->N",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.20,
                        "PHASE_C": 0.01,
                    },
                },
            ],
        }
    }

    plan = infer_physical_signal_plan(result)
    by_name = {phase["name"]: phase for phase in plan["phases"]}

    assert plan["mapping"] == {
        "PHASE_A": "NS_THROUGH",
        "PHASE_B": "NS_THROUGH_2",
        "PHASE_C": "EW_THROUGH",
    }
    assert by_name["NS_THROUGH"]["heads"]["N"]["main"] == "GREEN"
    assert by_name["NS_THROUGH"]["heads"]["S"]["main"] == "RED"
    assert by_name["NS_THROUGH_2"]["heads"]["N"]["main"] == "RED"
    assert by_name["NS_THROUGH_2"]["heads"]["S"]["main"] == "GREEN"


def test_automatic_physical_plan_absorbs_empty_phase_and_merges_cycle_boundary() -> None:
    names = ["PHASE_A", "PHASE_B", "PHASE_C"]
    result = {
        "schedule": {
            "phase_names": names,
            "phase_count": 3,
            "period_s": 120.119464,
            "baseline_duration_targets_s": {
                "PHASE_A": 43.183084,
                "PHASE_B": 34.878968,
                "PHASE_C": 42.057412,
            },
            "baseline_segments": [
                [0.0, 38.283030, 0],
                [38.283030, 73.161998, 1],
                [73.161998, 115.219411, 2],
                [115.219411, 120.119464, 0],
            ],
            "stream_activity_by_phase": [
                {
                    "stream": "E->W",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.20,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "W->E",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.20,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "N->S",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.20,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "S->N",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.20,
                        "PHASE_C": 0.01,
                    },
                },
            ],
        }
    }

    plan = infer_physical_signal_plan(result)

    assert plan["mapping"] == {
        "PHASE_A": "EW_THROUGH",
        "PHASE_B": "NS_THROUGH",
        "PHASE_C": "NS_THROUGH",
    }
    assert plan["inference"]["inherited_empty_phases"] == {
        "PHASE_C": "PHASE_B"
    }
    assert len(plan["stages"]) == 2
    assert [
        (stage["name"], stage["phase_start"], stage["phase_end"])
        for stage in plan["stages"]
    ] == [
        ("EW_THROUGH", 0.0, 43.183084),
        ("NS_THROUGH", 43.183084, 120.119464),
    ]
    assert plan["timing"]["cycle_rotation_s"] == 115.219411


def test_automatic_physical_plan_suppresses_discharge_turn_arrows() -> None:
    names = ["PHASE_A", "PHASE_B", "PHASE_C"]
    result = {
        "schedule": {
            "phase_names": names,
            "phase_count": 3,
            "period_s": 120.150651,
            "baseline_duration_targets_s": {
                "PHASE_A": 57.866394,
                "PHASE_B": 7.004673,
                "PHASE_C": 55.279584,
            },
            "baseline_segments": [
                [0.0, 23.681599, 2],
                [23.681599, 81.547993, 0],
                [81.547993, 88.552666, 1],
                [88.552666, 120.150651, 2],
            ],
            "stream_activity_by_phase": [
                {
                    "stream": "N->S",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.690104,
                        "PHASE_C": 0.138292,
                    },
                },
                {
                    "stream": "S->N",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.309896,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "N->E",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.252604,
                        "PHASE_C": 0.071983,
                    },
                },
                {
                    "stream": "N->W",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.242188,
                        "PHASE_C": 0.079152,
                    },
                },
                {
                    "stream": "S->W",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.02,
                        "PHASE_B": 0.091146,
                        "PHASE_C": 0.050478,
                    },
                },
                {
                    "stream": "E->N",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.114853,
                        "PHASE_B": 0.013021,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "W->N",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.144790,
                        "PHASE_B": 0.023438,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "E->W",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.097582,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.01,
                    },
                },
                {
                    "stream": "W->E",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.025619,
                        "PHASE_B": 0.01,
                        "PHASE_C": 0.01,
                    },
                },
            ],
        }
    }

    plan = infer_physical_signal_plan(result)

    assert plan["inference"]["physical_phase_count"] == 2
    assert plan["topology"]["N"]["arrows"] == []
    assert plan["topology"]["S"]["arrows"] == []
    assert plan["inference"]["suppressed_turn_movements_by_phase"]["PHASE_B"] == [
        "N->E",
        "N->W",
        "S->W",
    ]
    assert len(plan["stages"]) == 2
