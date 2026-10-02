from __future__ import annotations

from scripts.v9_offline_visualizer import render_html


def _result() -> dict[str, object]:
    return {
        "trajectory_count": 100,
        "event_count": 100,
        "movement_stream_count": 4,
        "recording_duration_s": 100.0,
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
        },
    }


def test_offline_visualizer_contains_v9_model_and_state_labels():
    html = render_html(
        _result(),
        yellow_duration_seconds=3.0,
        red_yellow_duration_seconds=2.0,
        activity_threshold=0.05,
    )
    assert "V9 — офлайн-реконструкция светофора" in html
    assert "GREEN" in html
    assert "YELLOW" in html
    assert "RED" in html
    assert "MODELLED_TRANSITION" in html
    assert '"stream":"N->S"' in html
    assert 'function movementLabel(value)' in html
    assert 'RU[a]||a' in html
