from __future__ import annotations

from app.core.v10.automatic_physical import infer_physical_signal_plan


def _plan(
    *,
    period: float,
    durations: dict[str, float],
    segments: list[list[float | int]],
    activity: list[dict[str, object]],
    analysis_base: float = 1_000.0,
    recording_start: float = 1_000.0,
) -> dict[str, object]:
    names = [f"PHASE_{chr(ord('A') + i)}" for i in range(len(durations))]
    return {
        "analysis_base_timestamp_ms": analysis_base,
        "recording_start_timestamp_ms": recording_start,
        "event_base_timestamp_ms": analysis_base,
        "schedule": {
            "phase_names": names,
            "phase_count": len(names),
            "period_s": period,
            "baseline_duration_targets_s": durations,
            "baseline_segments": segments,
            "stream_activity_by_phase": activity,
        },
    }


def _signatures(plan: dict[str, object]) -> set[frozenset[str]]:
    return {
        frozenset(item["green_movements"])
        for item in plan["phases"]
    }


def test_known_good_lenina_2025_keeps_both_turn_sections() -> None:
    names = ["PHASE_A", "PHASE_B", "PHASE_C"]
    result = _plan(
        period=99.84281321021679,
        durations={
            "PHASE_A": 19.224747,
            "PHASE_B": 33.338292,
            "PHASE_C": 47.279774,
        },
        segments=[
            [0.0, 34.488775, 2],
            [34.488775, 53.713522, 0],
            [53.713522, 87.051814, 1],
        ],
        activity=[
            {"stream": "S->N", "event_probability_by_phase": {names[0]: 0.01, names[1]: 0.53376, names[2]: 0.05110}},
            {"stream": "N->S", "event_probability_by_phase": {names[0]: 0.45369, names[1]: 0.24346, names[2]: 0.01068}},
            {"stream": "W->E", "event_probability_by_phase": {names[0]: 0.01, names[1]: 0.01, names[2]: 0.18389}},
            {"stream": "E->W", "event_probability_by_phase": {names[0]: 0.01, names[1]: 0.01, names[2]: 0.16195}},
            {"stream": "W->S", "event_probability_by_phase": {names[0]: 0.01, names[1]: 0.01, names[2]: 0.07592}},
            {"stream": "N->E", "event_probability_by_phase": {names[0]: 0.10926, names[1]: 0.01646, names[2]: 0.01}},
            {"stream": "E->N", "event_probability_by_phase": {names[0]: 0.09479, names[1]: 0.01, names[2]: 0.01}},
            {"stream": "S->E", "event_probability_by_phase": {names[0]: 0.01, names[1]: 0.02068, names[2]: 0.01}},
        ],
    )
    plan = infer_physical_signal_plan(result)
    assert _signatures(plan) == {
        frozenset({"N->S", "N->E", "E->N"}),
        frozenset({"N->S", "S->N"}),
        frozenset({"E->W", "W->E"}),
    }
    assert plan["topology"]["N"]["arrows"] == ["N->E"]
    assert plan["topology"]["E"]["arrows"] == ["E->N"]


def test_real_27_02_profile_does_not_invent_arrows() -> None:
    result = _plan(
        period=99.94684405367033,
        durations={"PHASE_A": 50.37978731678868, "PHASE_B": 20.3512590382049, "PHASE_C": 29.215797698676624},
        segments=[
            [0.0, 8.469354696672433, 2],
            [8.469354696672433, 58.84914201346116, 0],
            [58.84914201346116, 79.200401051666, 1],
            [79.200401051666, 99.94684405367033, 2],
        ],
        activity=[
            {"stream": "S->N", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.01, "PHASE_C": 0.33070501685142517}},
            {"stream": "E->W", "event_probability_by_phase": {"PHASE_A": 0.13586054742336273, "PHASE_B": 0.01, "PHASE_C": 0.01}},
            {"stream": "N->S", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.1608635038137436, "PHASE_C": 0.01}},
            {"stream": "N->E", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.10376044362783432, "PHASE_C": 0.01}},
            {"stream": "E->N", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.07172702252864838, "PHASE_C": 0.01}},
            {"stream": "W->E", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.01, "PHASE_C": 0.01}},
            {"stream": "S->E", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.01, "PHASE_C": 0.03849721699953079}},
        ],
    )
    plan = infer_physical_signal_plan(result)
    assert _signatures(plan) == {
        frozenset({"E->W", "W->E"}),
        frozenset({"N->S", "S->N"}),
    }
    assert all(not value["arrows"] for value in plan["topology"].values())


def test_real_05_10_profile_does_not_invent_arrows() -> None:
    result = _plan(
        period=99.87838859459997,
        durations={"PHASE_A": 32.4002925493908, "PHASE_B": 33.334452446835485, "PHASE_C": 34.14364359837367},
        segments=[
            [0.0, 24.847770271250585, 0],
            [24.847770271250585, 58.18222271808613, 1],
            [58.18222271808613, 92.32586631645977, 2],
        ],
        activity=[
            {"stream": "W->E", "event_probability_by_phase": {"PHASE_A": 0.29194915294647217, "PHASE_B": 0.034583333879709244, "PHASE_C": 0.01}},
            {"stream": "N->S", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.01, "PHASE_C": 0.13788869976997375}},
            {"stream": "E->W", "event_probability_by_phase": {"PHASE_A": 0.0478813573718071, "PHASE_B": 0.06791666895151138, "PHASE_C": 0.01}},
            {"stream": "E->S", "event_probability_by_phase": {"PHASE_A": 0.012288135476410389, "PHASE_B": 0.094583332538604, "PHASE_C": 0.01}},
            {"stream": "S->N", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.01, "PHASE_C": 0.01}},
            {"stream": "W->N", "event_probability_by_phase": {"PHASE_A": 0.06398305296897888, "PHASE_B": 0.0637499988079071, "PHASE_C": 0.01595744676887989}},
            {"stream": "W->S", "event_probability_by_phase": {"PHASE_A": 0.05211864411830902, "PHASE_B": 0.017916666343808174, "PHASE_C": 0.01}},
            {"stream": "N->W", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.01, "PHASE_C": 0.04950900003314018}},
        ],
    )
    plan = infer_physical_signal_plan(result)
    assert _signatures(plan) == {
        frozenset({"E->W", "W->E"}),
        frozenset({"N->S", "S->N"}),
    }
    assert all(not value["arrows"] for value in plan["topology"].values())


def test_real_chicherina_19_04_profile_does_not_invent_arrows() -> None:
    result = _plan(
        period=120.07415029970787,
        durations={"PHASE_A": 59.99075608870157, "PHASE_B": 60.08339421100629},
        segments=[
            [0.0, 22.72482248741154, 1],
            [22.72482248741154, 82.71557857611309, 0],
            [82.71557857611309, 120.07415029970787, 1],
        ],
        activity=[
            {"stream": "N->S", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.19818581640720367}},
            {"stream": "W->N", "event_probability_by_phase": {"PHASE_A": 0.15395401418209076, "PHASE_B": 0.012369433417916298}},
            {"stream": "E->N", "event_probability_by_phase": {"PHASE_A": 0.12983734905719757, "PHASE_B": 0.01}},
            {"stream": "S->W", "event_probability_by_phase": {"PHASE_A": 0.046270329505205154, "PHASE_B": 0.04535458981990814}},
            {"stream": "E->S", "event_probability_by_phase": {"PHASE_A": 0.11413348466157913, "PHASE_B": 0.01}},
            {"stream": "E->W", "event_probability_by_phase": {"PHASE_A": 0.10347728431224823, "PHASE_B": 0.01}},
            {"stream": "N->W", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.08768554031848907}},
            {"stream": "N->E", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.07394172251224518}},
            {"stream": "S->N", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.0415063239634037}},
            {"stream": "W->E", "event_probability_by_phase": {"PHASE_A": 0.028883904218673706, "PHASE_B": 0.01}},
            {"stream": "S->E", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.017866959795355797}},
        ],
    )
    plan = infer_physical_signal_plan(result)
    assert _signatures(plan) == {
        frozenset({"E->W", "W->E"}),
        frozenset({"N->S", "S->N"}),
    }
    assert all(not value["arrows"] for value in plan["topology"].values())


def test_v10_time_offset_does_not_apply_hardcoded_two_second_shift() -> None:
    result = _plan(
        period=100.0,
        durations={"PHASE_A": 50.0, "PHASE_B": 50.0},
        segments=[[0.0, 50.0, 0], [50.0, 100.0, 1]],
        activity=[
            {"stream": "E->W", "event_probability_by_phase": {"PHASE_A": 0.9, "PHASE_B": 0.01}},
            {"stream": "N->S", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.9}},
        ],
        analysis_base=3_612_806.0,
        recording_start=3_600_000.0,
    )
    plan = infer_physical_signal_plan(result)
    assert plan["time_offset_s"] == 12.806
    assert plan["timing"]["phase_anchor_model_s"] == 12.806
    assert plan["timing"]["phase_anchor_physical_s"] == 12.806
    assert plan["timing"]["startup_lost_s"] == 0.0
