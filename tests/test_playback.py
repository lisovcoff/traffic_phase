from __future__ import annotations

import json
from pathlib import Path

from app.core import playback
from app.core.phase_discovery import PhaseDiscoveryResult
from app.core.signal_state_estimator import SignalStateResult


class FakeCandidate:
    def to_dict(self):
        return {"period_seconds": 20.0, "strength": 0.8}


class FakeCycle:
    cycle_seconds = 20.0
    confidence = 0.8
    candidate_periods = [FakeCandidate()]


class FakeCycleEstimator:
    def estimate(self, signal, *, sampling_seconds):
        assert sampling_seconds == 2.0
        assert len(signal) >= 2
        return FakeCycle()


class FakePhaseDiscovery:
    def __init__(self, **kwargs):
        assert kwargs["bin_seconds"] == 2.0

    def discover(self, frame, *, cycle_seconds):
        assert cycle_seconds == 20.0
        return PhaseDiscoveryResult(
            cycle_seconds=20.0,
            bin_seconds=2.0,
            phases=(),
            profiles=(),
            similarities={},
        )


class FakeEstimator:
    def __init__(self, phase_model, **kwargs):
        assert phase_model.cycle_seconds == 20.0
        assert kwargs["yellow_duration_seconds"] == 2.0

    def estimate_playback(self, path: Path, timestamps_s):
        assert path.exists()
        results = []
        for timestamp_s in timestamps_s:
            results.append(
                SignalStateResult(
                    timestamp_s=timestamp_s,
                    cycle_phase_s=timestamp_s % 20.0,
                    phase_id=None,
                    transition=True,
                    phase_confidence=0.0,
                    approaches=(),
                )
            )
        return results


def test_playback_preserves_observed_millis(tmp_path, monkeypatch):
    source = [
        {
            "id": 1,
            "millis": 1000,
            "zone_in": "N",
            "zone_out": "S",
            "category_name": "car",
            "stay_duration_millis": 5000,
            "move_duration_millis": 1000,
            "speed": 1.0,
        },
        {
            "id": 2,
            "millis": 2750,
            "zone_in": "E",
            "zone_out": "W",
            "category_name": "car",
            "stay_duration_millis": 7000,
            "move_duration_millis": 1000,
            "speed": 1.0,
        },
        {
            "id": 3,
            "millis": 6000,
            "zone_in": "S",
            "zone_out": "N",
            "category_name": "truck",
            "stay_duration_millis": 9000,
        },
    ]
    path = tmp_path / "sample.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    monkeypatch.setattr(playback, "CycleEstimator", FakeCycleEstimator)
    monkeypatch.setattr(playback, "PhaseDiscovery", FakePhaseDiscovery)
    monkeypatch.setattr(playback, "SignalStateEstimator", FakeEstimator)

    payload = playback.build_playback_payload(path)

    assert payload["source"]["cars_used"] == 2
    assert [item["timestamp_ms"] for item in payload["timeline"]] == [1000, 2750]
    assert [item["timestamp_s"] for item in payload["timeline"]] == [0.0, 1.75]
    assert [item["timestamp_ms"] for item in payload["diagnostics"]] == [1000, 2750]
