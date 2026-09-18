from __future__ import annotations

from types import SimpleNamespace

from app.core import playback
from app.core.event_phase_discovery import EventPhase, EventPhaseDiscoveryResult
from app.core.models import EventType, TrajectoryEvent
from app.core.signal_state_estimator import ApproachState, SignalState, SignalStateResult


class FakeCandidate:
    def to_dict(self):
        return {"period_seconds": 20.0, "strength": 0.8}


class FakeCycleEstimate:
    cycle_seconds = 20.0
    confidence = 0.8
    candidate_periods = [FakeCandidate()]


class FakeCycle:
    estimate = FakeCycleEstimate()


def fake_phase_model():
    return EventPhaseDiscoveryResult(
        cycle_seconds=20.0,
        bin_seconds=2.0,
        phases=(
            EventPhase(1, 0.0, 10.0, ("N", "S"), 0.8, 10, 1, ("N", "S")),
            EventPhase(2, 10.0, 20.0, ("E", "W"), 0.8, 10, 1, ("E", "W")),
        ),
        profiles=(),
        cycle_coverage=1.0,
        overlap=0.0,
        supporting_event_count=20,
        contradictory_event_count=2,
        origin_timestamp_ms=1000,
    )


class FakeEstimator:
    def __init__(self, phase_model, **kwargs):
        assert phase_model.cycle_seconds == 20.0
        assert kwargs["yellow_duration_seconds"] == 2.0
        assert kwargs["event_origin_ms"] == 1000

    def estimate(self, timestamp_s, events):
        return SignalStateResult(
            timestamp_s=timestamp_s,
            cycle_phase_s=timestamp_s % 20.0,
            phase_id=1 if timestamp_s < 10 else 2,
            transition=False,
            phase_confidence=0.8,
            approaches=tuple(
                ApproachState(
                    approach=approach,
                    state=SignalState.GREEN if approach in ("N", "S") else SignalState.RED,
                    confidence=0.8,
                    phase_id=1,
                    evidence_weight=1.0,
                )
                for approach in ("N", "S", "E", "W")
            ),
        )


def test_playback_samples_fixed_timeline(monkeypatch, tmp_path):
    path = tmp_path / "sample.json"
    path.write_text("[]", encoding="utf-8")
    events = (
        TrajectoryEvent(EventType.RELEASE, 1000, "N", "N->S", 1.0, "HIGH"),
        TrajectoryEvent(EventType.RELEASE, 2750, "E", "E->W", 1.0, "HIGH"),
    )
    reconstruction = SimpleNamespace(
        trajectories=(object(), object()),
        events=events,
        cycle=FakeCycle(),
        phase_model=fake_phase_model(),
        origin_timestamp_ms=1000,
    )
    monkeypatch.setattr(playback, "reconstruct_file", lambda _path: reconstruction)
    monkeypatch.setattr(playback, "SignalStateEstimator", FakeEstimator)

    payload = playback.build_playback_payload(path)

    assert payload["source"]["cars_used"] == 2
    assert [item["timestamp_ms"] for item in payload["timeline"]] == [
        1000,
        1500,
        2000,
        2500,
        2750,
    ]
    assert [item["timestamp_s"] for item in payload["timeline"]] == [
        0.0,
        0.5,
        1.0,
        1.5,
        1.75,
    ]
    assert payload["ground_truth"] == "UNAVAILABLE"
    assert payload["model"] == "event_based_inference"
