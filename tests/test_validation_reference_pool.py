from __future__ import annotations

from app.core.models import EventType, TrajectoryEvent
from app.core.validation import ValidationDataset, ValidationRunner


def _event(kind, t, approach):
    return TrajectoryEvent(
        event_type=kind,
        timestamp_ms=int(t * 1000),
        approach=approach,
        movement=f"{approach}->x",
        confidence=1.0,
        quality="HIGH",
    )


def _events(offset_ms=0):
    events = []
    for cycle in range(4):
        base = cycle * 100_000 + offset_ms
        for offset in (5_000, 15_000, 25_000, 35_000):
            events.extend([
                _event(EventType.RELEASE, (base + offset) / 1000.0, "N"),
                _event(EventType.RELEASE, (base + offset) / 1000.0, "S"),
            ])
        for offset in (55_000, 65_000, 75_000, 85_000):
            events.extend([
                _event(EventType.RELEASE, (base + offset) / 1000.0, "E"),
                _event(EventType.RELEASE, (base + offset) / 1000.0, "W"),
            ])
    return events


def test_validation_uses_leave_one_out_reference_error_and_common_pool(monkeypatch, tmp_path):
    import app.core.validation as validation

    mapping = {
        "a.json": _events(10_000_000),
        "b.json": _events(50_000_000),
        "scenario.json": _events(90_000_000),
    }
    monkeypatch.setattr(validation, "load_events", lambda path: mapping[path.name])

    report = ValidationRunner(
        [
            ValidationDataset("reference_a", str(tmp_path / "a.json"), "reference"),
            ValidationDataset("reference_b", str(tmp_path / "b.json"), "reference"),
            ValidationDataset("scenario", str(tmp_path / "scenario.json"), "accident"),
        ]
    ).run()

    assert all(
        item["cycle"]["reference_error_seconds"] == 0.0
        for item in report["datasets"]
    )
    assert report["reference_pool"]["dataset_count"] == 2
    assert report["configuration"]["accuracy_claim"] is False
