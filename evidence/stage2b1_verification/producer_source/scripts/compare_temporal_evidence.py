"""Compare frozen 2A and 2B.1 artifacts without fitting or changing evaluation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_prediction(folder, row):
    path = folder / row["prediction_file"]
    if sha(path) != row["prediction_sha256_before_evaluation"]:
        raise ValueError(f"prediction hash mismatch: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def event_summary(prediction):
    extraction = prediction.get("event_extraction", {})
    quality = extraction.get("quality_diagnostics")
    if quality is not None:
        return {k: quality[k] for k in (
            "event_type_counts", "event_method_counts", "total_events",
            "weak_or_unknown_uncertainty_events", "weak_or_unknown_uncertainty_percent",
            "selected_event_count", "selected_weak_or_unknown_uncertainty_percent",
            "selection_by_movement", "track_quality_counts")}
    # Legacy extractor emits an entry for each usable track and no STOP/crossing
    # events. Missing confidence/uncertainty cannot be reconstructed from counts.
    count = prediction.get("event_count", 0)
    release = extraction.get("release_evidence_count", 0)
    return {"event_type_counts": {"ENTRY": count, "RELEASE": release, "STOP": 0,
                                  "CROSSING": 0, "CROSSING_PROXY": 0},
            "event_method_counts": {"legacy_main_view": extraction.get("methods", {}),
                                     "legacy_release_view": extraction.get("release_evidence_methods", {})},
            "total_events": count + release,
            "weak_or_unknown_uncertainty_events": None,
            "weak_or_unknown_uncertainty_percent": None,
            "weak_percentage_reason": "legacy_packed_streams_lost_per_event_quality_and_uncertainty",
            "interpretation": "counts_of_emitted_legacy_views_NOT_counts_of_true_vehicle_events"}


def compare(before_path, after_path):
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = json.loads(after_path.read_text(encoding="utf-8"))
    if before["config_sha256"] != after["config_sha256"] or before["config"] != after["config"]:
        raise ValueError("benchmark configuration changed")
    old_rows = {r["source_name"]: r for r in before["rows"]}
    if set(old_rows) != {r["source_name"] for r in after["rows"]}:
        raise ValueError("source set changed")
    result = {"before_report_sha256": sha(before_path), "after_report_sha256": sha(after_path),
              "before_code_commit": before["code"]["git_commit"],
              "after_code_commit": after["code"]["git_commit"],
              "same_config_sha256": before["config_sha256"], "rows": [],
              "interpretation": "one_development_regression_cycle; NOT independent lamp accuracy",
              "evidence_policy_change": "legacy global entry/release gate -> permission proxy per movement"}
    for new in after["rows"]:
        old = old_rows[new["source_name"]]
        for key in ("source_sha256", "annotation_sha256"):
            if old.get(key) != new.get(key):
                raise ValueError(f"input changed: {new['source_name']}/{key}")
        row = {"source": new["source_name"], "source_sha256": new["source_sha256"],
               "annotation_sha256": new["annotation_sha256"],
               "before_status": old["status"], "after_status": new["status"]}
        for label, entry, folder in (("before", old, before_path.parent), ("after", new, after_path.parent)):
            if entry["status"] != "ok":
                row[label] = {"status": "unavailable", "reason": entry.get("reason")}
                continue
            prediction = load_prediction(folder, entry)
            row[label] = {"K": entry["metrics"]["phase_count_match"],
                          "V10_plan_K": entry["metrics"]["physical_plan_phase_count"],
                          "period_error_s": entry["metrics"]["period_absolute_error_s"],
                          "inference_runtime_s": entry["inference_runtime_s"],
                          "events": event_summary(prediction),
                          "histories": {name: {"coverage": hist["coverage"],
                                               "precision": hist["boundaries"]["precision"],
                                               "recall": hist["boundaries"]["recall"],
                                               "nearest_boundary_mae_s": hist["boundaries"]["nearest_truth_boundary_mae_s_diagnostic"]}
                                        for name, hist in entry["metrics"]["histories"].items()}}
        result["rows"].append(row)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.before, args.after)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
