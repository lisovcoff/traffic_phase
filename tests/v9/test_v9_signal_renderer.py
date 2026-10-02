from __future__ import annotations

from app.core.v9.signal_renderer import signal_state_at


def _result() -> dict[str, object]:
    return {
        "schedule": {
            "period_s": 100.0,
            "phase_count": 2,
            "phase_names": ["PHASE_A", "PHASE_B"],
            "baseline_segments": [
                [0.0, 50.0, 0],
                [50.0, 100.0, 1],
            ],
            "stream_activity_by_phase": [
                {
                    "stream": "N->S",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.90,
                        "PHASE_B": 0.01,
                    },
                },
                {
                    "stream": "S->N",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.90,
                        "PHASE_B": 0.01,
                    },
                },
                {
                    "stream": "E->W",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.90,
                    },
                },
                {
                    "stream": "W->E",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.01,
                        "PHASE_B": 0.90,
                    },
                },
            ],
        }
    }


def _states(snapshot: dict[str, object]) -> dict[str, str]:
    return {
        str(item["movement"]): str(item["state"])
        for item in snapshot["streams"]  # type: ignore[index]
    }


def test_green_and_red_are_phase_activity_states():
    states = _states(signal_state_at(_result(), 25.0))
    assert states == {
        "N->S": "GREEN",
        "S->N": "GREEN",
        "E->W": "RED",
        "W->E": "RED",
    }


def test_yellow_is_only_a_modelled_end_transition():
    states = _states(signal_state_at(_result(), 48.0))
    assert states["N->S"] == "YELLOW"
    assert states["S->N"] == "YELLOW"
    assert states["E->W"] == "RED"


def test_red_yellow_precedes_new_green_phase():
    states = _states(signal_state_at(_result(), 51.0))
    assert states["N->S"] == "RED"
    assert states["E->W"] == "RED_YELLOW"
    assert states["W->E"] == "RED_YELLOW"


def test_transition_semantics_are_explicit():
    snapshot = signal_state_at(_result(), 48.0)
    assert snapshot["transition"] is True
    assert all(
        item["source"] == "MODELLED_TRANSITION"
        for item in snapshot["streams"]
        if item["state"] == "YELLOW"
    )
