from __future__ import annotations

from app.core.archive_analysis import (
    _axis_state,
    _timeline_unknown_metrics,
)


def test_mixed_axis_is_not_reported_as_unknown():
    assert _axis_state(
        {"N": "GREEN", "S": "RED"},
        ("N", "S"),
    ) == "MIXED"


def test_batch_unknown_metrics_are_per_approach_and_time_weighted():
    timeline = [
        {
            "timestamp_ms": 0,
            "states": {
                "N": "UNKNOWN",
                "S": "RED",
                "E": "GREEN",
                "W": "GREEN",
            },
        },
        {
            "timestamp_ms": 5_000,
            "states": {
                "N": "GREEN",
                "S": "RED",
                "E": "GREEN",
                "W": "GREEN",
            },
        },
        {
            "timestamp_ms": 10_000,
            "states": {
                "N": "GREEN",
                "S": "RED",
                "E": "GREEN",
                "W": "GREEN",
            },
        },
    ]

    metrics = _timeline_unknown_metrics(timeline)

    assert metrics["overall_rate"] == 0.125
    assert metrics["per_approach_rate"]["N"] == 0.5
    assert metrics["per_approach_rate"]["S"] == 0.0
    assert metrics["longest_unknown_s"]["N"] == 5.0
    assert metrics["meets_target"] is False


def test_batch_unknown_target_is_strictly_below_one_percent():
    timeline = [
        {
            "timestamp_ms": 0,
            "states": {
                "N": "GREEN",
                "S": "RED",
                "E": "GREEN",
                "W": "RED",
            },
        },
        {
            "timestamp_ms": 10_000,
            "states": {
                "N": "GREEN",
                "S": "RED",
                "E": "GREEN",
                "W": "RED",
            },
        },
    ]

    metrics = _timeline_unknown_metrics(timeline)

    assert metrics["overall_rate"] == 0.0
    assert metrics["target_rate"] == 0.01
    assert metrics["meets_target"] is True
