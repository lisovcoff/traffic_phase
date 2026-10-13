"""Evidence-only diagnostics: no annotations, evaluator, or phase fitting."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/stage2b1_verification"
BEFORE = ROOT / "benchmarks/stage2a_20261013/predictions"
AFTER = ROOT / "benchmarks/stage2b1_20261013/predictions"
NAME = "6_2025_2_14_20"
SOURCE = ROOT.parent / "data/ручная разметка" / (NAME + ".json")


def save(name, value):
    p = OUT / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def prediction(folder, name=NAME):
    return json.loads((folder / (name + "_v9.json")).read_text(encoding="utf-8"))


def tests():
    suites = {
        "unit72": ["tests/test_vehicle_temporal_evidence.py", "tests/test_trajectory_events.py",
                   "tests/test_trajectory_geometry.py", "tests/test_offline_benchmark.py"],
        "regression56": ["tests/v9/test_v9_discovery.py", "tests/v9/test_v9_signal_renderer.py",
                         "tests/v9/test_v9_spatial_visualizer.py", "tests/v10/test_v10_semantic_mapping.py",
                         "tests/test_archive_streaming.py", "tests/test_regime_selection.py", "tests/test_signal_state_safety.py"],
    }
    meta = {"code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "historical_logs": False, "interpretation": "verification rerun; original session stdout was not persisted",
            "python": sys.version, "suites": {}}
    for name, files in suites.items():
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "--basetemp=" + str(ROOT.parent / ("diagnostic_" + name)), *files]
        path = OUT / "logs" / (name + ".log")
        path.parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        with path.open("w", encoding="utf-8") as f:
            result = subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, timeout=180)
        meta["suites"][name] = {"command": cmd, "exit_code": result.returncode,
                                "seconds": time.perf_counter() - started, "log_sha256": sha(path)}
        save("logs/commands.json", meta)
        print(name, result.returncode, flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)


def select():
    p = prediction(AFTER)
    ext = p["event_extraction"]
    es = ext["temporal_events"]
    chosen = set(ext["quality_diagnostics"]["selected_event_indices"])
    crosses = {e["provenance"]["track_fingerprint"]: e for e in es if e["event_type"] == "CROSSING_PROXY"}
    groups = defaultdict(list)
    for i in sorted(chosen):
        e = es[i]
        fp = e["provenance"]["track_fingerprint"]
        if e["event_type"] == "RELEASE" and fp in crosses:
            delta = e["timestamp_ms"] - crosses[fp]["timestamp_ms"]
            group = "after_zone_transition" if delta > 0 else "before_or_at_zone_transition"
            groups[group].append({"selected_event_index": i, "event": e, "zone_proxy": crosses[fp],
                                  "delta_ms": delta, "stratum": group})
    samples = []
    for group in sorted(groups):
        samples.extend(sorted(groups[group], key=lambda r: r["event"]["provenance"]["track_fingerprint"])[:4])
    representative = []
    for name in ("17_2025_2_19_10", NAME):
        original = prediction(AFTER, name)
        ext = original["event_extraction"]
        for kind in ("RELEASE", "CROSSING_PROXY"):
            choices = [(i, ext["temporal_events"][i]) for i in ext["quality_diagnostics"]["selected_event_indices"]
                       if ext["temporal_events"][i]["event_type"] == kind]
            if choices:
                i, event = min(choices, key=lambda pair: pair[1]["provenance"]["track_fingerprint"])
                representative.append({"prediction": name, "prediction_sha256": sha(AFTER / (name + "_v9.json")),
                                       "selected_event_index": i, "original_event": event})
    save("sample_selection.json", {"selection_rule": "first_4_lexicographic_track_fingerprints_in_each_provenance_delta_stratum",
                                   "source": str(SOURCE), "prediction_sha256": sha(AFTER / (NAME + "_v9.json")),
                                   "phase_marks_accessed": False, "stratum_population": {g: len(v) for g, v in groups.items()},
                                   "samples": samples})
    save("selected_representatives.json", representative)
    print("selection fixed", len(samples), flush=True)


def finite(v):
    import math
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def summary(values):
    return {"n": len(values), "min": min(values), "median": statistics.median(values), "max": max(values)} if values else {"n": 0}


def analyze():
    from app.core.v9.events import _iter_json_records, _track_event_view, _kinematic_release_candidate
    from app.core.v9.primitives import norm_zone
    from app.core.v9.vehicle_evidence import clean_detections, track_fingerprint, extract_vehicle_evidence
    plan = json.loads((OUT / "sample_selection.json").read_text(encoding="utf-8"))
    wanted = {r["event"]["provenance"]["track_fingerprint"]: r for r in plan["samples"]}
    chosen_ids = {r["event"]["source_track_id"] for r in plan["samples"]}
    legacy = defaultdict(lambda: {"main": [], "release": [], "methods": Counter()})
    samples, counters, seen = [], Counter(), set()
    started = time.perf_counter()
    with SOURCE.open("rb") as stream:
        for track in _iter_json_records(stream):
            counters["scanned_tracks"] += 1
            # Historical tuple dedup exactly reproduces clean-data legacy path.
            ds = [d for d in track.get("detections", []) if isinstance(d, dict) and d.get("millis") is not None]
            ds.sort(key=lambda d: float(d["millis"]))
            key = (track.get("id"), float(ds[0]["millis"]) if ds else None,
                   norm_zone(track.get("zone_in")), norm_zone(track.get("zone_out")))
            if key not in seen:
                seen.add(key)
                view = _track_event_view(track, ds)
                if view:
                    main, _, release = view
                    legacy[main[1]]["main"].append(main[0])
                    legacy[main[1]]["methods"][main[3]] += 1
                    if release:
                        legacy[release[1]]["release"].append(release[0])
            if track.get("id") not in chosen_ids:
                continue
            clean, stats = clean_detections(track)
            fp = track_fingerprint(track, clean)
            if fp not in wanted:
                continue
            chosen = wanted[fp]
            release_ms = chosen["event"]["timestamp_ms"]
            origin = norm_zone(track["zone_in"])
            outgoing = norm_zone(track["zone_out"])
            at_release = min(clean, key=lambda d: abs(d["millis"] - release_ms))
            incoming = next((d["millis"] for d in clean if norm_zone(d.get("zone")) == origin), clean[0]["millis"])
            old_exit = next((d["millis"] for d in clean if norm_zone(d.get("zone")) == outgoing), clean[-1]["millis"])
            old_candidate = _kinematic_release_candidate(clean, incoming, old_exit)
            end_candidate = _kinematic_release_candidate(clean, incoming, clean[-1]["millis"])
            zones = []
            for d in clean:
                z = norm_zone(d.get("zone"))
                if not zones or zones[-1]["zone"] != z:
                    zones.append({"zone": z, "first_ms": d["millis"], "last_ms": d["millis"], "n": 1})
                else:
                    zones[-1]["last_ms"] = d["millis"]
                    zones[-1]["n"] += 1
            before = [d["speed"] for d in clean if release_ms - 3000 <= d["millis"] < release_ms and finite(d.get("speed"))]
            after = [d["speed"] for d in clean if release_ms <= d["millis"] <= release_ms + 3000 and finite(d.get("speed"))]
            coord = {field: summary([d[field] for d in clean if finite(d.get(field))])
                     for field in ("centroid_x", "centroid_y", "lat", "lng", "speed")}
            sample_events, issues = extract_vehicle_evidence(track, source_name=SOURCE.name)
            reproduced = next((e for e in sample_events if e.event_type == "RELEASE"), None)
            assert reproduced is not None and abs(reproduced.timestamp_ms - release_ms) < .001
            samples.append({"track_id": track.get("id"), "fingerprint": fp, "stratum": chosen["stratum"],
                            "selected_event_index": chosen["selected_event_index"], "release_ms": release_ms,
                            "zone_transition_ms": chosen["zone_proxy"]["timestamp_ms"], "delta_ms": chosen["delta_ms"],
                            "zone_nearest_release": at_release.get("zone"), "zone_runs": zones,
                            "n_detections": len(clean), "coordinate_ranges": coord,
                            "raw_speed_before_3s": summary(before), "raw_speed_after_3s": summary(after),
                            "zero_speed_detections": sum(d.get("speed") == 0 for d in clean),
                            "stop_event_emitted": any(e.event_type == "STOP" for e in sample_events),
                            "old_first_outgoing_zone_candidate": old_candidate,
                            "track_end_candidate": end_candidate, "first_outgoing_zone_ms": old_exit,
                            "quality_issues": issues,
                            "units_verified": False, "stop_line_location": "UNKNOWN"})
            # Save only fixed selected raw tracks, not the full source.
            save("tracks/" + fp + ".json", track)
    legacy_summary = {}
    for m, values in sorted(legacy.items()):
        legacy_summary[m] = {"main_count": len(values["main"]), "release_count": len(values["release"]),
                             "main_range_ms": [min(values["main"]), max(values["main"])],
                             "release_range_ms": [min(values["release"]), max(values["release"])] if values["release"] else None,
                             "main_methods": dict(values["methods"])}
    p = prediction(AFTER)
    ext = p["event_extraction"]
    selected = [ext["temporal_events"][i] for i in ext["quality_diagnostics"]["selected_event_indices"]]
    new = {}
    for movement in sorted(p["movement_streams"]):
        all_events = [e for e in ext["temporal_events"] if e["movement"] == movement]
        values = [e for e in selected if e["movement"] == movement]
        times = [e["timestamp_ms"] for e in values]
        new[movement] = {"all_type_counts": dict(Counter(e["event_type"] for e in all_events)),
                         "selected_count": len(values), "selected_methods": dict(Counter(e["evidence_method"] for e in values)),
                         "selected_range_ms": [min(times), max(times)] if times else None}
    assert sum(v["release_count"] for v in legacy_summary.values()) == prediction(BEFORE)["event_extraction"]["release_evidence_count"]
    save("record6_diagnostics.json", {"sample_manifest_sha256": sha(OUT / "sample_selection.json"),
                                     "source_sha256": sha(SOURCE), "scan_counts": dict(counters),
                                     "scan_plus_legacy_extraction_s": time.perf_counter() - started,
                                     "phase_marks_accessed": False, "phase_fit_runs": 0,
                                     "legacy_by_movement": legacy_summary, "permission_by_movement": new,
                                     "before_saved_candidate_K": prediction(BEFORE)["phase_model_selection"],
                                     "after_saved_candidate_K": p["phase_model_selection"], "samples": samples,
                                     "limits": "No verified units, independent stop annotations or stop-line geometry; no causation claim."})
    print("analysis saved", len(samples), flush=True)


def profile():
    from app.core.v9 import vehicle_evidence as module
    selection = json.loads((OUT / "sample_selection.json").read_text(encoding="utf-8"))
    paths = [OUT / "tracks" / (r["event"]["provenance"]["track_fingerprint"] + ".json") for r in selection["samples"]]
    # Fixed eight tracks; loading outside timers. No source archives or fitting.
    tracks = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    module.extract_vehicle_evidence(tracks[0])  # Explicit warmup, excluded.
    repeats = []
    for _ in range(5):
        timings = {"sanitization_s": 0.0, "fingerprinting_s": 0.0}
        clean_fn, fingerprint_fn = module.clean_detections, module.track_fingerprint
        def clean(*args):
            t = time.perf_counter()
            result = clean_fn(*args)
            timings["sanitization_s"] += time.perf_counter() - t
            return result
        def fingerprint(*args):
            t = time.perf_counter()
            result = fingerprint_fn(*args)
            timings["fingerprinting_s"] += time.perf_counter() - t
            return result
        with patch.object(module, "clean_detections", clean), patch.object(module, "track_fingerprint", fingerprint):
            t = time.perf_counter()
            all_events = [e for track in tracks for e in module.extract_vehicle_evidence(track)[0]]
            total = time.perf_counter() - t
        timings["extraction_exclusive_s"] = total - sum(timings.values())
        timings["extraction_inclusive_s"] = total
        t = time.perf_counter()
        payload = [e.to_dict() for e in all_events]
        timings["to_dict_s"] = time.perf_counter() - t
        t = time.perf_counter()
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        timings["json_encoding_s"] = time.perf_counter() - t
        timings["serialized_bytes"] = len(encoded)
        timings["event_count"] = len(all_events)
        repeats.append(timings)
    save("small_input_profile.json", {"input_files": [{"file": str(p.relative_to(OUT)), "sha256": sha(p)} for p in paths],
                                      "track_count": len(tracks), "detection_count": sum(len(t["detections"]) for t in tracks),
                                      "warmup_repeats": 1, "measured_repeats": 5, "python": sys.version,
                                      "timer": "perf_counter; wrapper overhead retained", "repeats": repeats,
                                      "median": {k: statistics.median(r[k] for r in repeats) for k in repeats[0]},
                                      "excluded": ["source parsing", "phase fitting", "file IO", "full benchmark runtime"],
                                      "code_sha256": sha(ROOT / "app/core/v9/vehicle_evidence.py")})


def contract():
    from app.core.temporal_evidence import TemporalEvent, EvidenceUnavailable
    from app.core.v9.model import discover_records
    reps = json.loads((OUT / "selected_representatives.json").read_text(encoding="utf-8"))
    for item in reps:
        event = TemporalEvent(**item["original_event"])
        item["explicit_uncertainty_serialization"] = event.to_dict()
        item["original_artifact_mutated"] = False
    probes = {}
    inputs = {"no_demand": [], "no_permission": [{"id": "probe", "zone_in": "N", "zone_out": "S",
                    "detections": [{"millis": 1000, "zone": "N", "speed": 10}]}]}
    def forbidden_fit(*args, **kwargs):
        raise AssertionError("phase fitting ran without permission")
    with patch("app.core.v9.model.discover_phase_count", forbidden_fit):
        for name, tracks in inputs.items():
            try:
                discover_records(tracks)
            except EvidenceUnavailable as exc:
                probes[name] = exc.to_dict()
            else:
                raise AssertionError("missing evidence did not abstain")
    save("uncertainty_and_unknown.json", {"representatives": reps, "machine_probes": probes,
                                          "phase_fit_runs": 0, "phase_marks_accessed": False,
                                          "scope": "additive serialization clarification; historical predictions unchanged"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=["tests", "select", "analyze", "profile", "contract"])
    args = parser.parse_args()
    globals()[args.task]()


if __name__ == "__main__":
    main()
