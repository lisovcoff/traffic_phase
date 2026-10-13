from __future__ import annotations

import json
import pytest

from app.core.offline_benchmark import (
    evaluate_prediction, match_boundaries, state_at, validate_annotation,
)
from scripts.offline_benchmark import infer_to_file, run_benchmark, DEFAULT_CONFIG


def annotation(times=(0, 50000, 100000, 150000, 200000), labels=("A", "B", "A", "B", "A"), start=0):
    return validate_annotation({"start_ms": start, "marks": [
        {"timestamp_ms": t, "kind": z, "offset_s": (t - start) / 1000}
        for t, z in zip(times, labels)]})


def prediction(rows=None, period=100, k=2):
    rows = rows if rows is not None else [[0, 50, 0], [50, 100, 1], [100, 150, 0], [150, 200, 1]]
    return {"schedule_base_timestamp_ms": 0,
            "schedule": {"phase_count": k, "period_s": period,
                         "raw_hsmm_segments": rows, "baseline_segments": rows}}


@pytest.mark.parametrize("labels", [("A", "A"), ("A", "B")])
def test_identical_timestamps_rejected_even_for_equal_labels(labels):
    result = annotation((1000, 1000), labels)
    assert not result["valid"]
    assert any("duplicate_timestamp" in e for e in result["errors"])


def test_unsorted_and_inconsistent_offsets_rejected_without_sorting():
    result = validate_annotation({"start_ms": 0, "marks": [
        {"timestamp_ms": 2000, "kind": "A", "offset_s": 2},
        {"timestamp_ms": 1000, "kind": "B", "offset_s": 99}]})
    assert not result["valid"]
    assert any("timestamps_not_strictly" in e for e in result["errors"])
    assert any("offset_inconsistent" in e for e in result["errors"])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "1000", -1, 1.5])
def test_invalid_timestamp_types_rejected(value):
    result = validate_annotation({"start_ms": 0, "marks": [{"timestamp_ms": value, "kind": "A"}]})
    assert not result["valid"]


def test_unknown_initial_phase_does_not_extend_truth_to_recording_start():
    truth = annotation((20000, 50000, 100000), ("A", "B", "A"))
    assert truth["known_range_ms"] == [20000, 100000]
    assert "unknown_initial_phase_before_first_mark" in truth["warnings"]
    report = evaluate_prediction(prediction(), truth)
    assert report["histories"]["baseline_segments"]["coverage"]["truth_duration_s"] == 80


def test_missing_terminal_boundary_excludes_last_phase_tail():
    truth = annotation((0, 50000, 100000), ("A", "B", "A"))
    assert "missing_terminal_boundary_for_last_phase" in truth["warnings"]
    hist = evaluate_prediction(prediction(), truth)["histories"]["baseline_segments"]
    assert hist["phase_agreement_diagnostic"]["total_grid_points"] == 100
    assert hist["boundaries"]["recall"]["n_observations"] == 1


def test_boundary_across_cycle_seam_uses_absolute_time_not_modulo():
    truth = annotation((90000, 100000, 120000), ("A", "B", "A"))
    pred = prediction([[90, 100.5, 0], [100.5, 120, 1]])
    boundary = evaluate_prediction(pred, truth)["histories"]["raw_hsmm_segments"]["boundaries"]
    assert boundary["mae_s"]["value"] == .5
    assert boundary["recall"]["value"] == 1
    assert match_boundaries([100000], [0], 2) == []


def test_matching_is_one_to_one_and_maximizes_cardinality():
    assert len(match_boundaries([1000, 3000], [2000], 2)) == 1
    pairs = match_boundaries([1000, 3000], [0, 2000], 2)
    assert len(pairs) == 2
    assert {p["predicted_ms"] for p in pairs} == {0, 2000}


def test_skipped_phase_produces_miss_and_cardinality_mismatch():
    truth = annotation((0, 30000, 60000, 100000), ("A", "B", "C", "A"))
    result = evaluate_prediction(prediction([[0, 60, 0], [60, 100, 1]], k=2), truth)
    assert result["phase_count_match"]["value"] is False
    hist = result["histories"]["raw_hsmm_segments"]
    assert hist["boundaries"]["recall"]["value"] == .5
    assert hist["boundaries"]["missed_truth_ms"] == [30000]
    assert hist["phase_agreement_diagnostic"]["reason"] == "unequal_phase_cardinality"


def test_extended_phase_is_measured_as_timing_error_not_overwritten_by_baseline():
    # Phase A held 10s longer; no assumption that it proves an observed GREEN.
    truth = annotation((0, 60000, 100000), ("A", "B", "A"))
    pred = prediction([[0, 60, 0], [60, 100, 1]])
    pred["schedule"]["baseline_segments"] = [[0, 50, 0], [50, 100, 1]]
    result = evaluate_prediction(pred, truth)
    assert result["histories"]["raw_hsmm_segments"]["boundaries"]["mae_s"]["value"] == 0
    baseline = result["histories"]["baseline_segments"]["boundaries"]
    assert baseline["recall"]["value"] == 0
    assert baseline["mae_s"]["reason"] == "no_matches_within_tolerance"
    assert baseline["nearest_truth_boundary_mae_s_diagnostic"]["value"] == 10


def test_no_vehicle_demand_cannot_be_scored_as_red_or_lamp_accuracy():
    from app.core.v9.signal_renderer import signal_state_at
    pred = prediction()
    pred["schedule"]["stream_activity_by_phase"] = [{"stream": "N->S",
        "event_probability_by_phase": {"PHASE_A": .4, "PHASE_B": 0.0}}]
    # Existing renderer labels no-demand as RED even with zero confidence.
    # This is an intentionally preserved counterexample, not a detector fix.
    lamp_hypothesis = signal_state_at(pred, 70)["streams"][0]
    assert lamp_hypothesis["state"] == "RED"
    assert lamp_hypothesis["confidence"] == 0
    result = evaluate_prediction(pred, annotation())
    assert result["physical_lamp_accuracy"]["value"] is None
    assert "no_independent_per_lamp_truth" in result["physical_lamp_accuracy"]["reason"]
    assert "NOT_physical_lamp_accuracy" in result["histories"]["baseline_segments"]["phase_agreement_diagnostic"]["interpretation"]


def test_gaps_and_outside_history_remain_unknown():
    assert state_at([(10, 20, "A")], 0) is None
    assert state_at([(10, 20, "A")], 20) is None
    result = evaluate_prediction(prediction([[0, 50, 0], [100, 200, 1]]), annotation())
    history = result["histories"]["raw_hsmm_segments"]
    assert history["coverage"]["value"] == .75
    assert history["boundaries"]["recall"]["predicted_boundaries"] == 0


def test_missing_or_invalid_prediction_has_explicit_unavailable_reason():
    result = evaluate_prediction({}, annotation())
    assert result["period_absolute_error_s"]["value"] is None
    assert result["histories"]["raw_hsmm_segments"]["coverage"]["reason"] == "missing_schedule_time_anchor"
    invalid = prediction([[0, 60, 0], [50, 100, 1]])
    assert evaluate_prediction(invalid, annotation())["histories"]["raw_hsmm_segments"]["reason"] == "overlapping_or_unsorted_history"


def test_truth_labels_cannot_be_passed_to_inference_and_predictions_saved_first(tmp_path):
    source = tmp_path / "source.json"
    source.write_text("[]", encoding="utf-8")
    output = tmp_path / "prediction.json"
    calls = []
    def discover(path, **kwargs):
        calls.append((path, kwargs))
        assert kwargs == {"dt": 1.0}
        return prediction()
    infer_to_file(source, output, 1.0, discover=discover)
    saved = output.read_bytes()
    for kinds in (("A", "B", "A", "B", "A"), ("X", "Y", "X", "Y", "X")):
        evaluate_prediction(json.loads(saved), annotation(labels=kinds))
        assert output.read_bytes() == saved
    assert len(calls) == 1
    with pytest.raises(TypeError):
        infer_to_file(source, output, 1.0, marks_path=tmp_path / "test_labels.json")
    labels_path = tmp_path / "source.json_manual_marks.json"
    labels_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        infer_to_file(labels_path, output, 1.0, discover=discover)


def test_unexpected_label_evaluation_in_prediction_rejected(tmp_path):
    source = tmp_path / "source.json"
    source.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="label-based"):
        infer_to_file(source, tmp_path / "pred.json", 1.0, discover=lambda *a, **k: {"evaluation": {}})


def test_missing_source_is_reported_not_fabricated(tmp_path):
    marks = tmp_path / "absent.json_manual_marks.json"
    marks.write_text(json.dumps({"start_ms": 0, "marks": [
        {"timestamp_ms": 0, "kind": "A"}, {"timestamp_ms": 1000, "kind": "B"}]}), encoding="utf-8")
    result = run_benchmark(tmp_path, tmp_path / "out", DEFAULT_CONFIG)
    assert result["rows"][0]["status"] == "missing_trajectory"
    assert result["rows"][0]["metrics"]["n_observations"] == 0
