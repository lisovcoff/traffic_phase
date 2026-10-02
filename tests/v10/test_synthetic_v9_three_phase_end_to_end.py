from __future__ import annotations

from dataclasses import dataclass

from app.core.v9.model import discover_records
from scripts.v9_spatial_visualizer import _physical_visual_model, render_html


BASE_MS = 1_700_000_000_000
CYCLE_S = 100.0
PHASES = (
    ("EW_THROUGH", 0.0, 35.0, (("E", "W", 12), ("W", "E", 12))),
    ("NS_THROUGH", 35.0, 70.0, (("N", "S", 12), ("S", "N", 12))),
    (
        "NS_TURN",
        70.0,
        100.0,
        (("N", "S", 10), ("N", "E", 8), ("E", "N", 8)),
    ),
)


@dataclass(frozen=True)
class SyntheticTruth:
    name: str
    start_s: float
    end_s: float
    movements: tuple[str, ...]


def _synthetic_truth() -> tuple[SyntheticTruth, ...]:
    return tuple(
        SyntheticTruth(
            name=name,
            start_s=start_s,
            end_s=end_s,
            movements=tuple(
                f"{source}->{target}" for source, target, _ in streams
            ),
        )
        for name, start_s, end_s, streams in PHASES
    )


def _make_tracks(minutes: int = 60) -> list[dict]:
    cycles = int(minutes * 60 / CYCLE_S)
    tracks: list[dict] = []
    identifier = 0

    for cycle in range(cycles):
        cycle_start = cycle * CYCLE_S
        for _phase_name, phase_start, phase_end, streams in PHASES:
            for source, target, count in streams:
                usable = phase_end - phase_start - 3.0
                for index in range(count):
                    fraction = (index + 1) / (count + 1)
                    event_s = (
                        cycle_start
                        + phase_start
                        + 1.0
                        + fraction * usable
                    )
                    millis = int(round(BASE_MS + event_s * 1000.0))
                    identifier += 1
                    tracks.append(
                        {
                            "id": f"synthetic-{identifier}",
                            "category_name": "car",
                            "zone_in": source,
                            "zone_out": target,
                            "detections": [
                                {"millis": millis, "zone": source},
                                {"millis": millis + 1000, "zone": target},
                            ],
                        }
                    )

    return tracks


def _phase_by_signature(result: dict) -> dict[str, str]:
    rows = result["schedule"]["stream_activity_by_phase"]
    phase_names = result["schedule"]["phase_names"]
    signatures: dict[str, set[str]] = {
        name: set() for name in phase_names
    }

    for row in rows:
        stream = row["stream"]
        values = row["event_probability_by_phase"]
        peak = max(float(value) for value in values.values())
        for phase in phase_names:
            value = float(values.get(phase, 0.0))
            if value >= 0.50 * peak:
                signatures[phase].add(stream)

    expected = {
        "EW_THROUGH": {"E->W", "W->E"},
        "NS_THROUGH": {"N->S", "S->N"},
        "NS_TURN": {"N->S", "N->E", "E->N"},
    }
    remaining = set(expected)
    mapping: dict[str, str] = {}

    for phase in phase_names:
        candidates = [
            name
            for name in remaining
            if signatures[phase] & expected[name]
        ]
        assert candidates, (
            f"V9 phase {phase} has no recognizable synthetic signature: "
            f"{sorted(signatures[phase])}"
        )
        best = max(
            candidates,
            key=lambda name: len(signatures[phase] & expected[name]),
        )
        mapping[phase] = best
        remaining.remove(best)

    assert not remaining, (
        f"V9 failed to expose all synthetic phases: {sorted(remaining)}"
    )
    return mapping


def _head_states(physical: dict, time_s: float) -> dict[str, dict[str, object]]:
    period = float(physical["cycle_seconds"])
    position = time_s % period
    active = next(
        stage
        for stage in physical["stages"]
        if float(stage["phase_start"]) <= position < float(stage["phase_end"])
    )
    green = set(active["active_movements"])

    result: dict[str, dict[str, object]] = {}
    opposite = {"N": "S", "S": "N", "E": "W", "W": "E"}

    for approach, target in opposite.items():
        main = f"{approach}->{target}"
        result[approach] = {
            "main": "GREEN" if main in green else "RED",
            "arrows": sorted(
                movement
                for movement in green
                if movement.startswith(f"{approach}->")
                and movement != main
            ),
        }
    return result


def test_sixty_minute_three_phase_pipeline_from_truth_to_renderer() -> None:
    truth = _synthetic_truth()
    assert len(truth) == 3
    assert len(_make_tracks(minutes=60)) == 2664

    tracks = _make_tracks(minutes=60)
    result = discover_records(
        tracks,
        input_name="synthetic_60min_three_phase",
        dt=1.0,
    )

    assert result["phase_model_selection"]["selected_phase_count"] == 3

    semantic_mapping = _phase_by_signature(result)
    assert set(semantic_mapping.values()) == {
        "EW_THROUGH",
        "NS_THROUGH",
        "NS_TURN",
    }

    physical = result["physical_signal_plan"]
    assert physical["enabled"] is True
    by_name = {phase["name"]: phase for phase in physical["phases"]}

    expected_green = {
        "EW_THROUGH": {"E->W", "W->E"},
        "NS_THROUGH": {"N->S", "S->N"},
        "NS_TURN": {"N->S", "N->E", "E->N"},
    }
    for physical_name, expected in expected_green.items():
        assert set(by_name[physical_name]["green_movements"]) == expected

    assert physical["topology"]["N"]["main"] == "N->S"
    assert physical["topology"]["S"]["main"] == "S->N"
    assert physical["topology"]["E"]["main"] == "E->W"
    assert physical["topology"]["W"]["main"] == "W->E"
    assert physical["topology"]["N"]["arrows"] == ["N->E"]
    assert physical["topology"]["E"]["arrows"] == ["E->N"]

    visual = _physical_visual_model(result, physical)
    assert visual["topology"] == physical["topology"]
    for stage in physical["stages"]:
        heads = stage["heads"]
        assert set(heads) == {"N", "S", "E", "W"}
        for approach in ("N", "S", "E", "W"):
            assert set(heads[approach]) == {"main", "arrows"}
            assert all(
                state == "GREEN"
                for state in heads[approach]["arrows"].values()
            )


    ew = _head_states(physical, 10.0)
    ns = _head_states(physical, 45.0)
    turn = _head_states(physical, 80.0)

    assert ew["E"]["main"] == "GREEN"
    assert ew["W"]["main"] == "GREEN"
    assert ew["N"]["main"] == "RED"
    assert ew["S"]["main"] == "RED"

    assert ns["N"]["main"] == "GREEN"
    assert ns["S"]["main"] == "GREEN"
    assert ns["E"]["main"] == "RED"
    assert ns["W"]["main"] == "RED"

    assert turn["N"]["main"] == "GREEN"
    assert turn["N"]["arrows"] == ["N->E"]
    assert turn["E"]["main"] == "RED"
    assert turn["E"]["arrows"] == ["E->N"]
    assert turn["S"]["main"] == "RED"
    assert turn["W"]["main"] == "RED"

    html = render_html(
        result,
        {},
        [],
        physical_plan=physical,
    )
    assert "const PHYSICAL = " in html
    assert '"N-\\u003eE"' in html
    assert '"E-\\u003eN"' in html
    assert 'const ACTIVE_APPROACHES = PHYSICAL.enabled' in html
    assert '"heads":{"N":{"main":"RED"' in html
