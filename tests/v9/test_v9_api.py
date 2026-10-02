from __future__ import annotations

import asyncio
from io import BytesIO

import pytest
from fastapi import UploadFile
from fastapi import HTTPException

from app.api import v9


def _model() -> dict[str, object]:
    return {
        "analysis_base_timestamp_ms": 0,
        "schedule": {
            "period_s": 100.0,
            "phase_count": 1,
            "baseline_segments": [[0.0, 100.0, 0]],
            "stream_activity_by_phase": [
                {
                    "stream": "N→S",
                    "event_probability_by_phase": {
                        "PHASE_A": 0.9,
                    },
                }
            ],
        },
        "physical_signal_plan": {
            "enabled": True,
            "mapping": {"PHASE_A": "NS_THROUGH"},
            "phases": [
                {
                    "name": "NS_THROUGH",
                    "green_movements": ["N→S"],
                    "additional_movements": ["W→N"],
                }
            ],
        },
    }


def test_runtime_registry_keeps_realtime_state() -> None:
    registry = v9.V9RuntimeRegistry(max_models=4, max_streams=4)
    model = _model()
    model_id = registry.register_model(model)

    tracker, effective_id, _ = registry.get_or_create_session(
        "stream-a",
        model_id=model_id,
        model=None,
        lookback_s=60.0,
    )
    tracker.observe(1_000, "N→S")
    first = tracker.infer(1_000)

    same_tracker, same_id, _ = registry.get_or_create_session(
        "stream-a",
        model_id=model_id,
        model=None,
        lookback_s=60.0,
    )
    same_tracker.observe(2_000, "N→S")
    second = same_tracker.infer(2_000)

    assert same_tracker is tracker
    assert effective_id == same_id == model_id
    assert first["recent_event_count"] == 1
    assert second["recent_event_count"] == 2


def test_v9_realtime_uses_model_id_and_physical_mapping() -> None:
    v9.runtime_registry.clear()
    model_id = v9.runtime_registry.register_model(_model())
    stream_id = "api-v9-test"

    first = v9.v9_realtime(
        v9.RealtimeRequest(
            model_id=model_id,
            stream_id=stream_id,
            event={
                "timestamp_ms": 1_000,
                "stream": "N→S",
            },
        )
    )
    second = v9.v9_realtime(
        v9.RealtimeRequest(
            model_id=model_id,
            stream_id=stream_id,
            event={
                "timestamp_ms": 2_000,
                "stream": "N→S",
            },
        )
    )

    assert first["model_id"] == model_id
    assert first["stream_id"] == stream_id
    assert first["snapshot"]["physical_phase"] == "NS_THROUGH"
    assert first["snapshot"]["physical_green_movements"] == ["N→S"]
    assert first["snapshot"]["physical_additional_movements"] == ["W→N"]
    assert second["snapshot"]["recent_event_count"] == 2

    v9.runtime_registry.reset_stream(stream_id)
    reset = v9.v9_realtime(
        v9.RealtimeRequest(
            model_id=model_id,
            stream_id=stream_id,
            event={
                "timestamp_ms": 3_000,
                "stream": "N→S",
            },
        )
    )
    assert reset["snapshot"]["recent_event_count"] == 1


def test_v9_realtime_rejects_unknown_model_id() -> None:
    v9.runtime_registry.clear()
    with pytest.raises(HTTPException) as excinfo:
        v9.v9_realtime(
            v9.RealtimeRequest(
                model_id="v9_missing",
                stream_id="missing-model",
                event={
                    "timestamp_ms": 1_000,
                    "stream": "N→S",
                },
            )
        )
    assert excinfo.value.status_code == 404


def test_v9_analyze_registers_model_and_returns_model_id(monkeypatch: pytest.MonkeyPatch) -> None:
    v9.runtime_registry.clear()
    expected = _model()

    def fake_discover_path(source, *, dt):
        assert source.name == "input.json"
        assert dt == 1.0
        return expected.copy()

    monkeypatch.setattr(v9, "discover_path", fake_discover_path)

    upload = UploadFile(
        file=BytesIO(b"{}"),
        filename="input.json",
    )
    result = asyncio.run(v9.v9_analyze(upload, 1.0))

    model_id = result["api"]["model_id"]
    assert isinstance(model_id, str)
    assert model_id.startswith("v9_")
    assert v9.runtime_registry.get_model(model_id)["schedule"]["period_s"] == 100.0
