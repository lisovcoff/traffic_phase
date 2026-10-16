from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from app.core.temporal_evidence import TemporalEvent, adapt_trajectory_event
from app.core.v9.events import extract_timing_streams, load_event_streams, _track_event_view
from app.core.v9.model import _choose_phase_evidence, discover_records
from app.core.v9.vehicle_evidence import extract_vehicle_evidence, select_permission_events


def track(*, stopped=False, movement="N->_S", ident=1):
    origin, target = movement.split("->")
    return {"id": ident, "zone_in": origin, "zone_out": target,
            "stay_duration_millis": 6000 if stopped else 0,
            "detections": [{"millis": 100000 + t * 1000,
                            "zone": origin if t < 8 else target,
                            "speed": 0 if stopped and t < 6 else 10}
                           for t in range(12)]}


def events(record):
    return extract_vehicle_evidence(record)[0]


def test_nonstopping_car_has_demand_and_zone_proxy_not_release_or_true_crossing():
    values = events(track())
    assert [e.event_type for e in values] == ["ENTRY", "CROSSING_PROXY"]
    assert values[0].provenance["role"] == "demand_only"
    assert values[1].temporal_uncertainty_ms is None
    assert values[1].provenance["observation_interval_ms"] == [107000, 108000]
    assert values[1].provenance["sampling_uncertainty_ms"] == 1000


def test_stationary_car_and_restart_do_not_imply_stop_line_or_lamp_color():
    values = events(track(stopped=True))
    assert {e.event_type for e in values} == {"ENTRY", "STOP", "RELEASE", "CROSSING_PROXY"}
    release = next(e for e in values if e.event_type == "RELEASE")
    assert release.timestamp_ms == 106000
    assert release.temporal_uncertainty_ms >= 1000
    assert release.provenance["proxy"]
    stop = next(e for e in values if e.event_type == "STOP")
    assert stop.provenance["stop_location"] == "unknown_relative_to_stop_line"
    assert all(not e.provenance["signal_state_observed"] for e in values)


def test_queue_discharge_observation_can_lag_configured_green_without_backdating():
    # External test scenario has green at 103s; vehicle starts at 106s.
    release = next(e for e in events(track(stopped=True)) if e.event_type == "RELEASE")
    assert release.timestamp_ms - 103000 == 3000
    assert "green_timestamp_ms" not in release.provenance
    assert release.evidence_quality == "MEDIUM"


@pytest.mark.parametrize("cause", ["permissive_turn", "accident_cleared_under_unchanged_signal"])
def test_indistinguishable_restart_does_not_invent_green_or_cause(cause):
    record = track(stopped=True, movement="N->_E")
    record["scenario_note"] = cause
    values = events(record)
    assert next(e for e in values if e.event_type == "RELEASE").movement == "N->E"
    assert all("cause" not in e.provenance and not e.provenance["signal_state_observed"] for e in values)
    assert {e.event_type for e in values} <= {"ENTRY", "STOP", "RELEASE", "CROSSING_PROXY"}


def test_sparse_metadata_without_observed_restart_is_not_confident_release():
    record = track(stopped=True)
    record["detections"] = [record["detections"][0], record["detections"][-1]]
    # Existing V9 returns True for insufficient speed support, hence 0.9 release.
    assert _track_event_view(record)[2][4] == .9
    assert not any(e.event_type == "RELEASE" for e in events(record))
    assert select_permission_events(events(record))[0] == []  # 11s gap also rejects zone proxy.


def test_missing_detections_do_not_bridge_gap_into_restart_or_crossing():
    record = track(stopped=True)
    record["detections"] = [d for d in record["detections"] if d["millis"] not in {104000, 105000, 106000, 107000}]
    values = events(record)
    assert not any(e.event_type == "RELEASE" for e in values)
    assert all(e.event_type != "CROSSING" for e in values)
    assert select_permission_events(values)[0] == []


def test_duplicate_detections_and_tracks_are_counted_once_and_audited():
    record = track(stopped=True)
    record["detections"].insert(2, copy.deepcopy(record["detections"][1]))
    bundle = extract_timing_streams([record, copy.deepcopy(record)])
    assert bundle[9] == 1
    assert bundle.diagnostics["track_quality_counts"]["duplicate_tracks"] == 1
    assert bundle.diagnostics["track_quality_counts"]["duplicate_detections"] == 1
    assert bundle.diagnostics["event_type_counts"]["ENTRY"] == 1


def test_missing_ids_with_same_start_do_not_collapse_different_tracks():
    a, b = track(ident=None), track(ident=None)
    b["detections"][-1]["millis"] += 1000
    assert extract_timing_streams([a, b])[9] == 2


def test_conflicting_duplicate_timestamp_is_not_arbitrarily_chosen():
    record = track()
    altered = copy.deepcopy(record["detections"][5])
    altered["speed"] = 999
    record["detections"].append(altered)
    bundle = extract_timing_streams([record])
    assert bundle.diagnostics["track_quality_counts"]["conflicting_timestamps"] == 1
    assert not bundle.permission_streams
    assert all(e.evidence_quality == "LOW" for e in bundle.temporal_events)


@pytest.mark.parametrize("shape", ["single_point", "no_origin", "no_exit", "invalid_time"])
def test_short_truncated_or_invalid_tracks_remain_demand_only(shape):
    record = track()
    if shape == "single_point":
        record["detections"] = record["detections"][:1]
    elif shape == "no_origin":
        record["detections"] = record["detections"][8:]
    elif shape == "no_exit":
        record["detections"] = record["detections"][:8]
    else:
        record["detections"] = [{"millis": float("nan"), "zone": "N"}]
    values = events(record)
    assert not select_permission_events(values)[0]
    assert not any(e.event_type in {"RELEASE", "CROSSING"} for e in values)


def test_absence_of_demand_or_permission_returns_explicit_unknown_not_entry_fallback():
    assert extract_vehicle_evidence({"zone_in": "N", "zone_out": "_S", "detections": []})[0] == []
    chosen, method = _choose_phase_evidence({"N->S": [1, 2]}, {}, 2)
    assert chosen == {} and method == "permission_per_stream"
    with pytest.raises(ValueError, match="demand only.*UNKNOWN"):
        discover_records([{**track(), "detections": track()["detections"][:1]}])


def test_sparse_releases_cannot_globally_switch_other_stream_to_demand():
    a = track(stopped=True, movement="N->_S")
    b = track(movement="E->_W", ident=2)
    bundle = extract_timing_streams([a, b])
    assert bundle.diagnostics["selection_by_movement"] == {
        "E->W": "zone_crossing_proxy", "N->S": "release_proxy"}
    assert list(bundle.permission_streams["N->S"]) == [6]
    assert list(bundle.permission_streams["E->W"]) == [8]
    chosen, _ = _choose_phase_evidence(bundle[0], bundle.permission_streams, bundle[9])
    assert list(chosen["N->S"]) == [6]
    legacy, method = _choose_phase_evidence(bundle[0], bundle[2], bundle[9], evidence_policy="legacy_v9")
    assert method == "mixed_release_or_entry" and list(legacy["N->S"]) == [0]


def test_sidecar_roundtrip_preserves_source_uncertainty_and_selected_identity(tmp_path):
    record = track(stopped=True)
    path = tmp_path / "cars.json"
    path.write_text(json.dumps([record]), encoding="utf-8")
    bundle = load_event_streams(path)
    assert len(bundle) == 10 and type(bundle[0]["N->S"]).__name__ == "array"
    serial = json.loads(json.dumps([e.to_dict() for e in bundle.temporal_events]))
    selected = serial[bundle.diagnostics["selected_event_indices"][0]]
    assert selected["source_track_id"] == 1
    assert selected["provenance"]["source"] == "cars.json"
    assert selected["evidence_method"] == "metadata_dwell_end_restart_supported"
    assert selected["temporal_uncertainty_ms"] == 3000
    assert "NOT_lamp_probability" in selected["provenance"]["confidence_semantics"]
    legacy = load_event_streams(path, evidence_policy="legacy_v9")
    assert len(legacy) == 10 and not hasattr(legacy, "temporal_events")


def test_shared_extractor_crossing_enum_never_implies_verified_stop_line():
    legacy = SimpleNamespace(event_type="CROSSING", timestamp_ms=1000,
                             movement="N->S", confidence=.9, quality="HIGH")
    proxy = adapt_trajectory_event(legacy, source_track_id=1, evidence_method="zone", provenance={})
    assert proxy.event_type == "CROSSING_PROXY" and proxy.temporal_uncertainty_ms is None
    actual = adapt_trajectory_event(legacy, source_track_id=1, evidence_method="configured_geometry",
                                    provenance={"verified_stop_line": True}, temporal_uncertainty_ms=500)
    assert actual.event_type == "CROSSING"
    with pytest.raises(ValueError, match="verified stop-line"):
        TemporalEvent(1000, "CROSSING", "N->S", 1, "unknown", .9, "HIGH", 0, {})


def test_model_receives_lossless_sidecar_before_phase_fit(monkeypatch):
    import app.core.v9.model as model
    received = {}
    def capture(*args, **kwargs):
        received.update(kwargs)
        return {"captured": True}
    monkeypatch.setattr(model, "_discover_from_stream_views", capture)
    result = model.discover_records([track(stopped=True)])
    assert result['captured'] is True
    assert result['input_scope']['source_member'] == 'records'
    assert received["evidence_policy"] == "permission_per_stream"
    assert received["temporal_events"]
    assert list(received["permission_streams"]["N->S"]) == [6]
    selected = received["evidence_diagnostics"]["selected_event_indices"]
    assert received["temporal_events"][selected[0]].evidence_method == "metadata_dwell_end_restart_supported"
