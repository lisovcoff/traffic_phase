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


def _events(cycle_seconds=100.0, offset_seconds=0.0):
    events = []
    for cycle in range(8):
        base = offset_seconds + cycle * cycle_seconds
        for fraction in (0.10, 0.20, 0.30, 0.40):
            events.extend(
                [
                    _event(
                        EventType.RELEASE,
                        base + cycle_seconds * fraction,
                        "N",
                    ),
                    _event(
                        EventType.RELEASE,
                        base + cycle_seconds * fraction,
                        "S",
                    ),
                ]
            )
        for fraction in (0.60, 0.70, 0.80, 0.90):
            events.extend(
                [
                    _event(
                        EventType.RELEASE,
                        base + cycle_seconds * fraction,
                        "E",
                    ),
                    _event(
                        EventType.RELEASE,
                        base + cycle_seconds * fraction,
                        "W",
                    ),
                ]
            )
    return events


def _dataset(name, path, intersection_id, kind):
    return ValidationDataset(
        name=name,
        path=str(path),
        intersection_id=intersection_id,
        kind=kind,
    )


def test_validation_scopes_reference_periods_and_baselines_by_intersection(
    monkeypatch,
    tmp_path,
):
    import app.core.validation as validation

    mapping = {
        "ref_a.json": _events(100.0, 10_000.0),
        "scenario_a.json": _events(100.0, 20_000.0),
        "ref_b.json": _events(120.0, 30_000.0),
        "scenario_b.json": _events(120.0, 40_000.0),
    }
    monkeypatch.setattr(
        validation,
        "load_events",
        lambda path: mapping[path.name],
    )

    baseline_sources = []
    original_validate_signal = validation.validate_signal

    def tracked_validate_signal(*args, **kwargs):
        baseline = kwargs.get("baseline")
        baseline_sources.append(baseline.source if baseline else None)
        return original_validate_signal(*args, **kwargs)

    monkeypatch.setattr(
        validation,
        "validate_signal",
        tracked_validate_signal,
    )

    report = ValidationRunner(
        [
            _dataset(
                "reference_a",
                tmp_path / "ref_a.json",
                "intersection_a",
                "reference",
            ),
            _dataset(
                "scenario_a",
                tmp_path / "scenario_a.json",
                "intersection_a",
                "accident",
            ),
            _dataset(
                "reference_b",
                tmp_path / "ref_b.json",
                "intersection_b",
                "reference",
            ),
            _dataset(
                "scenario_b",
                tmp_path / "scenario_b.json",
                "intersection_b",
                "lane_closure",
            ),
        ]
    ).run()

    items = {
        item["dataset"]["name"]: item
        for item in report["datasets"]
    }

    assert items["scenario_a"]["reference"]["dataset_names"] == [
        "reference_a"
    ]
    assert items["scenario_b"]["reference"]["dataset_names"] == [
        "reference_b"
    ]
    assert items["scenario_a"]["cycle"]["reference_period_seconds"] == 100.0
    assert items["scenario_b"]["cycle"]["reference_period_seconds"] == 120.0
    assert items["scenario_a"]["cycle"]["reference_error_seconds"] == 0.0
    assert items["scenario_b"]["cycle"]["reference_error_seconds"] == 0.0

    assert report["reference_summary"] == {
        "dataset_count": 2,
        "intersection_count": 2,
    }
    assert report["reference_pools"]["intersection_a"]["dataset_names"] == [
        "reference_a"
    ]
    assert report["reference_pools"]["intersection_b"]["dataset_names"] == [
        "reference_b"
    ]
    assert baseline_sources[:2] == [
        "validation_reference_pool:intersection_a",
        "validation_reference_pool:intersection_a",
    ]
    assert baseline_sources[2:] == [
        "validation_reference_pool:intersection_b",
        "validation_reference_pool:intersection_b",
    ]
