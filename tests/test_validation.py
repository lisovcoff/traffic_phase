from __future__ import annotations

from app.core.event_phase_discovery import EventPhaseDiscovery
from app.core.models import EventType, TrajectoryEvent
from app.core.validation import ValidationDataset, ValidationRunner, report_markdown


def event(kind, t, approach):
    return TrajectoryEvent(
        event_type=kind,
        timestamp_ms=int(t * 1000),
        approach=approach,
        movement=f"{approach}->x",
        confidence=1.0,
        quality="HIGH",
    )


def synthetic_events():
    events = []
    for cycle in range(4):
        base = cycle * 100.0
        for offset in (5.0, 15.0, 25.0, 35.0):
            events.extend(
                [
                    event(EventType.RELEASE, base + offset, "N"),
                    event(EventType.RELEASE, base + offset, "S"),
                ]
            )
        for offset in (55.0, 65.0, 75.0, 85.0):
            events.extend(
                [
                    event(EventType.RELEASE, base + offset, "E"),
                    event(EventType.RELEASE, base + offset, "W"),
                ]
            )
    return events


def test_validation_runner_exposes_required_metric_groups(monkeypatch, tmp_path):
    import app.core.validation as validation

    events = synthetic_events()
    monkeypatch.setattr(validation, "load_events", lambda _path: events)

    report = ValidationRunner(
        [
            ValidationDataset("reference", str(tmp_path / "ref.json"), "reference"),
            ValidationDataset("scenario", str(tmp_path / "scenario.json"), "accident"),
        ]
    ).run()

    assert report["configuration"]["accuracy_claim"] is False
    item = report["datasets"][0]
    assert {"cycle", "phase", "signal", "realtime"} <= set(item)
    assert "anomaly_mean_score" in item["signal"]
    assert "false_state_switch_rate" in item["signal"]
    assert "batch_realtime_agreement" in item["realtime"]


def test_validation_markdown_is_human_readable():
    report = {
        "reference_pool": {
            "dataset_count": 1,
            "median_period_seconds": 100.0,
            "median_signal_confidence": 0.9,
        },
        "datasets": [],
    }
    markdown = report_markdown(report)
    assert "consistency/behaviour" in markdown
    assert "Realtime agreement" in markdown
