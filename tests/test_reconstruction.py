from __future__ import annotations

from app.core.event_phase_discovery import EventPhaseDiscoveryResult
from app.core.reconstruction import BatchReconstruction


def test_batch_reconstruction_to_dict_exposes_origin_and_models():
    cycle = type("Cycle", (), {"to_dict": lambda self: {"estimated_cycle": 100.0}})()
    phase = EventPhaseDiscoveryResult(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=(),
        profiles=(),
        cycle_coverage=0.0,
        overlap=0.0,
        supporting_event_count=0,
        contradictory_event_count=0,
        origin_timestamp_ms=1234,
    )
    reconstruction = BatchReconstruction(
        trajectories=(),
        events=(),
        cycle=cycle,
        phase_model=phase,
        origin_timestamp_ms=1234,
    )
    data = reconstruction.to_dict()
    assert data["origin_timestamp_ms"] == 1234
    assert data["phase_model"]["origin_timestamp_ms"] == 1234
