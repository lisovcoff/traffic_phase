import json

import pytest

from app.core.temporal_evidence import EvidenceUnavailable, TemporalEvent
from app.core.v9.model import discover_records


@pytest.mark.parametrize("radius", [1300, 3000, None])
def test_vehicle_radius_does_not_bound_signal_switch(radius):
    event = TemporalEvent(5000, "RELEASE", "N->S", 1, "proxy", .65, "MEDIUM", radius,
                          {"observation_interval_ms": [4900, 5000], "verified_stop_line": False})
    result = json.loads(json.dumps(event.to_dict()))
    assert result["uncertainty"]["vehicle_event"]["sampling_interval_width_ms"] == 100
    assert result["uncertainty"]["vehicle_event"]["heuristic_localization_radius_ms"] == radius
    assert result["uncertainty"]["vehicle_event"]["statistical_error_bound"] is False
    assert result["uncertainty"]["event_to_signal_switch"]["uncertainty_ms"] is None
    assert result["uncertainty"]["event_to_signal_switch"]["status"] == "UNKNOWN"


def test_no_permission_has_structured_unknown_without_phase_fitting(monkeypatch):
    import app.core.v9.model as model
    def forbidden_fit(*args, **kwargs):
        pytest.fail("phase fitting must not run without permission evidence")
    monkeypatch.setattr(model, "discover_phase_count", forbidden_fit)
    with pytest.raises(EvidenceUnavailable) as caught:
        discover_records([{"id": 1, "zone_in": "N", "zone_out": "S",
                           "detections": [{"millis": 1000, "zone": "N", "speed": 10}]}])
    result = caught.value.to_dict()
    assert result["status"] == "unavailable"
    assert result["state"] == "UNKNOWN"
    assert result["reason_code"] == "NO_PERMISSION_EVIDENCE"
    assert result["phase_count"] is None and result["schedule"] is None


def test_no_demand_has_separate_machine_code():
    with pytest.raises(EvidenceUnavailable) as caught:
        discover_records([])
    assert caught.value.to_dict()["reason_code"] == "NO_TRAJECTORY_RECORDS"
    assert isinstance(caught.value, ValueError)
