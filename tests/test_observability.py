from __future__ import annotations

from types import SimpleNamespace

from app.core.archive_analysis import (
    _axis_state,
    _phase_coverage_gaps,
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



def test_phase_coverage_gaps_reports_uncovered_cycle_interval():
    model = SimpleNamespace(
        cycle_seconds=100.0,
        phases=(
            SimpleNamespace(phase_start=30.0, phase_end=50.0),
            SimpleNamespace(phase_start=50.0, phase_end=84.0),
            SimpleNamespace(phase_start=84.0, phase_end=22.0),
        ),
    )

    assert _phase_coverage_gaps(model) == [
        {
            "start_s": 22.0,
            "end_s": 30.0,
            "duration_s": 8.0,
        }
    ]


def test_unknown_reason_breakdown_tracks_uncovered_phase_time():
    timeline = [
        {
            "timestamp_ms": 0,
            "states": {
                "N": "UNKNOWN",
                "S": "UNKNOWN",
                "E": "UNKNOWN",
                "W": "UNKNOWN",
            },
            "unknown_reason": "uncovered_phase",
        },
        {
            "timestamp_ms": 8_000,
            "states": {
                "N": "GREEN",
                "S": "RED",
                "E": "RED",
                "W": "RED",
            },
            "unknown_reason": None,
        },
        {
            "timestamp_ms": 100_000,
            "states": {
                "N": "GREEN",
                "S": "RED",
                "E": "RED",
                "W": "RED",
            },
            "unknown_reason": None,
        },
    ]

    metrics = _timeline_unknown_metrics(timeline)

    assert metrics["overall_rate"] == 0.08
    assert metrics["reason_rate"]["uncovered_phase"] == 0.08
    assert metrics["reason_seconds"]["uncovered_phase"] == 8.0
