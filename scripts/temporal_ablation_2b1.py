"""Four predeclared evidence interventions; immutable inputs; no production edits."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import hashlib
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/stage2b1_ablation"
SOURCE = ROOT.parent / "data/ручная разметка/6_2025_2_14_20.json"
REFERENCE = ROOT / "benchmarks/stage2b1_20261013/predictions/6_2025_2_14_20_v9.json"
BASE_SHA = "afcfaa2b38e106201d7e819570425acfc4c5487f"
ENV = {"PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
REPRO_FIELDS = ["schedule", "phase_model_selection", "period_inference", "physical_signal_plan",
                "analysis_base_timestamp_ms", "event_base_timestamp_ms", "schedule_base_timestamp_ms",
                "recording_start_timestamp_ms", "recording_duration_s", "anomaly_detection"]


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")


def digest(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save(name, obj):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation forbids overwriting inputs, ledger or predictions.
    with path.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")


def load(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


@contextmanager
def deny_annotation_reads():
    original = Path.open
    def guarded(path, *args, **kwargs):
        if "manual_marks" in path.name or "annotation" in path.name:
            raise AssertionError("annotation access before sealed predictions")
        return original(path, *args, **kwargs)
    with patch.object(Path, "open", guarded):
        yield


def drop_sparse(events):
    removed = [e for e in events if e["movement"] == "S->N"]
    assert len(removed) == 1 and removed[0]["event_type"] == "RELEASE"
    return [e for e in events if e["movement"] != "S->N"], removed


def substitute_movement(events, replacement, movement="E->W"):
    assert replacement and all(e["movement"] == movement and e["event_type"] == "RELEASE" for e in replacement)
    return sorted([e for e in events if e["movement"] != movement] + replacement,
                  key=lambda e: (e["timestamp_ms"], e["movement"]))


def bound_image_call(solver, detections, entry, target, norm):
    upper = next((d["millis"] for d in detections if norm(d.get("zone")) == target), detections[-1]["millis"])
    return solver(detections, entry, upper)


def composition(events):
    result = {}
    for m in sorted({e["movement"] for e in events}):
        es = [e for e in events if e["movement"] == m]
        result[m] = {"count": len(es), "types": dict(Counter(e["event_type"] for e in es)),
                     "methods": dict(Counter(e["evidence_method"] for e in es)),
                     "range_ms": [min(e["timestamp_ms"] for e in es), max(e["timestamp_ms"] for e in es)],
                     "canonical_event_sha256": digest(es)}
    return result


def by_movement(events, anchor):
    from array import array
    values = defaultdict(list)
    for event in events:
        values[event["movement"]].append((event["timestamp_ms"] - anchor) / 1000)
    return {m: array("d", sorted(ts)) for m, ts in values.items()}


def prepare():
    if (OUT / "manifest.json").exists():
        raise RuntimeError("experiment already sealed; no repeat preparation")
    from app.core.v9 import events as ev, vehicle_evidence as ve, model
    from app.core.v9.primitives import norm_zone
    from app.core.v9.fit import discover_phase_count
    ref = json.loads(REFERENCE.read_text(encoding="utf-8"))
    es = ref["event_extraction"]["temporal_events"]
    a = [es[i] for i in ref["event_extraction"]["quality_diagnostics"]["selected_event_indices"]]
    b, removed = drop_sparse(a)
    legacy_ew = []
    image_solver, extractor = ev._kinematic_release_candidate, ve.extract_vehicle_evidence
    image_calls = []
    def extract_c(track, *, source_name="records"):
        target = norm_zone(track.get("zone_out"))
        def old_upper(ds, entry, supplied_upper):
            chosen_upper = next((d["millis"] for d in ds if norm_zone(d.get("zone")) == target), ds[-1]["millis"])
            image_calls.append({"track_id": track.get("id"), "from_upper_ms": supplied_upper,
                                "to_upper_ms": chosen_upper, "changed": chosen_upper != supplied_upper})
            return image_solver(ds, entry, chosen_upper)
        # Same producer extractor, guards, dedup and selection; only image upper changes.
        with patch.object(ev, "_kinematic_release_candidate", old_upper):
            result = extractor(track, source_name=source_name)
        if norm_zone(track.get("zone_in")) == "E" and target == "W":
            view = ev._track_event_view(track)
            if view and view[2] is not None:
                ts, movement, ident, method, confidence = view[2]
                legacy_ew.append({"timestamp_ms": ts, "movement": movement, "source_track_id": ident,
                    "event_type": "RELEASE", "evidence_method": method, "confidence": confidence,
                    "evidence_quality": "LOW", "temporal_uncertainty_ms": None,
                    "provenance": {"source": SOURCE.name, "diagnostic_origin": "legacy_v9_EW_timestamps_only",
                                   "signal_state_observed": False, "verified_stop_line": False,
                                   "uncertainty_reason": "legacy_timestamp_quality_not_reconstructed"}})
        return result
    with patch.object(ve, "extract_vehicle_evidence", extract_c):
        c_bundle = ev.load_event_streams(SOURCE)
    c = [c_bundle.temporal_events[i].to_dict() for i in c_bundle.diagnostics["selected_event_indices"]]
    # Non-release raw events must be byte-semantic equal to the saved control.
    nonrelease_a = [e for e in es if e["event_type"] != "RELEASE"]
    nonrelease_c = [e.to_dict() for e in c_bundle.temporal_events if e.event_type != "RELEASE"]
    assert nonrelease_a == nonrelease_c
    assert len(legacy_ew) == 8  # Saved 2A per-movement diagnostic, independent of phase labels.
    d = substitute_movement(a, legacy_ew)
    anchor = ref["schedule_base_timestamp_ms"]
    assert anchor == ref["analysis_base_timestamp_ms"] == ref["event_base_timestamp_ms"]
    entries = [e for e in es if e["event_type"] == "ENTRY"]
    extent = max((e["timestamp_ms"] - anchor) / 1000 for e in entries + a)
    assert extent < 7200 and ref.get("regime_detection", {}).get("method") == "global_fallback"
    common = {"anchor_ms": anchor, "recording_start_ms": ref["recording_start_timestamp_ms"],
              "period_s": ref["period_inference"]["period_s"], "period_info": ref["period_inference"],
              "extent_s": extent, "dt_s": 1.0, "seed": 0, "entries": entries,
              "trajectory_count": ref["trajectory_count"], "event_count": ref["event_count"],
              "methods": ref["event_extraction"]["methods"], "input": ref["input"],
              "source_files": ref["archive"]["source_files"]}
    save("common.json", common)
    variants = {"A": a, "B": b, "C": c, "D": d}
    for name, values in variants.items():
        assert all(0 <= (e["timestamp_ms"] - anchor) / 1000 <= extent for e in values)
        save("events_" + name + ".json", values)
    descriptions = {
        "A": "saved permission_per_stream selected evidence; control",
        "B": "A minus the single S->N selected RELEASE; removes one occupancy dimension",
        "C": "same producer guards/selection with first outgoing image upper; induced per-movement fallback retained",
        "D": "A with legacy selected RELEASE timestamps for E->W only; legacy reliability is not interpreted by frozen model"}
    model_sources = ["app/core/v9/model.py", "app/core/v9/fit.py", "app/core/v9/decoder.py",
                     "app/core/v9/primitives.py", "app/core/v9/events.py", "app/core/v9/vehicle_evidence.py",
                     "app/core/v10/automatic_physical.py", "app/core/v10/semantic_mapping.py",
                     "app/core/temporal_evidence.py", "app/core/offline_benchmark.py"]
    hashes = {}
    for path in model_sources:
        expected = subprocess.check_output(["git", "show", BASE_SHA + ":" + path], cwd=ROOT)
        actual = (ROOT / path).read_bytes()
        assert actual.replace(b"\r\n", b"\n") == expected.replace(b"\r\n", b"\n")
        hashes[path] = hashlib.sha256(expected).hexdigest()
    manifest = {"base_branch": "fix/stage2b1-temporal-evidence-20261013", "base_head_sha": BASE_SHA,
                "runner_head_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "runner_sha256": file_sha(Path(__file__)), "production_git_blob_hashes": hashes,
                "source": str(SOURCE), "source_sha256": file_sha(SOURCE),
                "reference_prediction_sha256": file_sha(REFERENCE), "common_sha256": file_sha(OUT / "common.json"),
                "fixed_config": {k: common[k] for k in ("anchor_ms", "recording_start_ms", "period_s", "extent_s", "dt_s", "seed")},
                "model_defaults": str(inspect.signature(discover_phase_count)), "environment": ENV,
                "packages": {n: importlib.metadata.version(n) for n in ("numpy", "scipy", "scikit-learn")},
                "python": sys.version, "reproduction_fields": REPRO_FIELDS, "reproduction_numeric_rule": "exact JSON values",
                "max_fitting_invocations": 4, "timeout_per_variant_s": 90,
                "annotations_access": "evaluate command only, after all prediction hashes sealed",
                "boundary_tolerance_s": 2.0,
                "extent_adapter": "same occupancy extent, K recording_end_s and baseline extent for all variants; functions otherwise delegated unchanged",
                "variants": {n: {"description": descriptions[n], "events_sha256": file_sha(OUT / ("events_" + n + ".json")),
                                  "composition": composition(v), "count": len(v), "dimension": len({e['movement'] for e in v})}
                             for n, v in variants.items()}}
    save("intervention_provenance.json", {"B_removed": removed, "C_image_calls": image_calls,
                                         "C_nonrelease_raw_events_equal_control": True,
                                         "C_selection_by_movement": c_bundle.diagnostics["selection_by_movement"],
                                         "D_legacy_EW": legacy_ew, "D_unchanged_other_movements": True})
    save("manifest.json", manifest)
    save("manifest_seal.json", {"sha256": file_sha(OUT / "manifest.json"), "no_fitting_yet": True})
    print("Manifest sealed before fitting", {n: manifest["variants"][n]["count"] for n in variants}, flush=True)


def verify_seal():
    assert file_sha(OUT / "manifest.json") == load("manifest_seal.json")["sha256"]
    m = load("manifest.json")
    assert file_sha(OUT / "common.json") == m["common_sha256"]
    for n, v in m["variants"].items():
        assert file_sha(OUT / ("events_" + n + ".json")) == v["events_sha256"]
    return m


def fit(name):
    m = verify_seal()
    save("attempt_" + name + ".json", {"variant": name, "fitting_attempt": 1,
                                        "manifest_sha256": file_sha(OUT / "manifest.json")})
    import numpy as np
    from app.core.v9 import model
    from app.core.temporal_evidence import TemporalEvent
    common, es = load("common.json"), load("events_" + name + ".json")
    permission = by_movement(es, common["anchor_ms"])
    entries = by_movement(common["entries"], common["anchor_ms"])
    occupancy_fn, count_fn, baseline_fn = model.build_occupancy_matrix, model.discover_phase_count, model.periodic_baseline_from_segments
    count_diagnostics = {}
    def occupancy(streams, extent, *, dt):
        assert dt == common["dt_s"]
        return occupancy_fn(streams, common["extent_s"], dt=dt)
    def phase_count(x, streams, period, **kwargs):
        assert period == common["period_s"]
        kwargs["recording_end_s"] = common["extent_s"]
        result = count_fn(x, streams, period, **kwargs)
        count_diagnostics.update({"occupancy_shape": list(x.shape), "candidates": result[1],
                                  "raw_selected_k": result[0], "common_extent_s": common["extent_s"]})
        return result
    def baseline(segments, period, extent):
        return baseline_fn(segments, period, common["extent_s"])
    started = time.perf_counter()
    np.random.seed(common["seed"])
    with patch.object(model, "infer_period", return_value=(common["period_s"], common["period_info"])), \
         patch.object(model, "build_occupancy_matrix", occupancy), \
         patch.object(model, "discover_phase_count", phase_count), \
         patch.object(model, "periodic_baseline_from_segments", baseline):
        result = model._discover_from_stream_views(entries, entries, common["methods"],
            dict(Counter(e["evidence_method"] for e in es)), release_streams=permission,
            permission_streams=permission, temporal_events=[TemporalEvent(**e) for e in es],
            evidence_diagnostics={"diagnostic_selected_only_sidecar": True, "variant": name},
            input_name=common["input"], dt=common["dt_s"], recording_start_ms=common["recording_start_ms"],
            analysis_base_ms=common["anchor_ms"], trajectory_count=common["trajectory_count"],
            event_count=common["event_count"], source_files=common["source_files"], evidence_policy="permission_per_stream")
    save("predictions/" + name + ".json", result)
    save("fit_" + name + ".json", {"runtime_s": time.perf_counter() - started,
                                    "prediction_sha256": file_sha(OUT / "predictions" / (name + ".json")),
                                    "input_event_sha256": m["variants"][name]["events_sha256"], **count_diagnostics})
    verify_seal()
    print(name, "K", result["schedule"]["phase_count"], flush=True)


def run():
    m = verify_seal()
    if any(OUT.glob("attempt_*.json")):
        raise RuntimeError("attempt already exists; retries forbidden")
    for name in "ABCD":
        if name != "A" and not load("control_reproduction.json")["exact_match"]:
            raise RuntimeError("control not reproduced")
        cmd = [sys.executable, "-m", "scripts.temporal_ablation_2b1", "fit", "--variant", name]
        path = OUT / "logs" / (name + ".log")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as f:
            result = subprocess.run(cmd, cwd=ROOT, env={**os.environ, **ENV}, stdout=f, stderr=subprocess.STDOUT,
                                    timeout=m["timeout_per_variant_s"])
        if result.returncode:
            save("STOP.json", {"reason": "fitting_failed", "variant": name, "exit_code": result.returncode})
            raise SystemExit(result.returncode)
        if name == "A":
            ref = json.loads(REFERENCE.read_text(encoding="utf-8"))
            actual = load("predictions/A.json")
            fields = {k: actual.get(k) == ref.get(k) for k in REPRO_FIELDS}
            save("control_reproduction.json", {"exact_match": all(fields.values()), "fields": fields,
                                               "compared_model_outputs_not_invocation_metadata": True})
            if not all(fields.values()):
                save("STOP.json", {"reason": "unexplained_control_mismatch", "fields": fields})
                raise SystemExit(1)
        print("fixed prediction", name, flush=True)
    save("predictions_seal.json", {n: file_sha(OUT / "predictions" / (n + ".json")) for n in "ABCD"})


def evaluate():
    # The sole annotation-reading phase begins only after all predictions sealed.
    m = verify_seal()
    seal = load("predictions_seal.json")
    assert set(seal) == set("ABCD") and load("control_reproduction.json")["exact_match"]
    for n, expected in seal.items():
        assert file_sha(OUT / "predictions" / (n + ".json")) == expected
    save("evaluation_attempt.json", {"attempt": 1, "predictions_seal_sha256": file_sha(OUT / "predictions_seal.json")})
    from app.core.offline_benchmark import evaluate_prediction, validate_annotation
    annotation_path = SOURCE.with_name(SOURCE.name + "_manual_marks.json")
    annotation = validate_annotation(json.loads(annotation_path.read_text(encoding="utf-8")))
    output = {"annotation_sha256": file_sha(annotation_path), "manifest_sha256": file_sha(OUT / "manifest.json"),
              "boundary_tolerance_s": m["boundary_tolerance_s"], "rows": {}}
    for name in "ABCD":
        output["rows"][name] = evaluate_prediction(load("predictions/" + name + ".json"), annotation,
                                                   tolerance_s=m["boundary_tolerance_s"])
    save("evaluation.json", output)
    assert all(file_sha(OUT / "predictions" / (n + ".json")) == expected for n, expected in seal.items())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=["prepare", "run", "fit", "evaluate"])
    parser.add_argument("--variant", choices=list("ABCD"))
    args = parser.parse_args()
    for k, v in ENV.items():
        os.environ[k] = v
    if args.task == "evaluate":
        evaluate()
    else:
        with deny_annotation_reads():
            if args.task == "fit":
                if args.variant is None:
                    parser.error("--variant required")
                fit(args.variant)
            else:
                globals()[args.task]()


if __name__ == "__main__":
    main()
