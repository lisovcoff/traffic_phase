"""Event-only census of the sealed A/D E->W union; no fitting or truth access."""
from __future__ import annotations

import csv
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import time
from unittest.mock import patch

from app.core.v9 import events as ev, vehicle_evidence as ve
from app.core.v9.primitives import norm_zone, _speed_restart_plausible
from app.core.trajectory_geometry import _finite_number
from scripts.temporal_ablation_2b1 import deny_annotation_reads

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/stage2b1_ew_event_audit"
BASE_HEAD = "6f75e81cf6f22d7e1e14f2fad0c0348e9811f9a1"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(name, value):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")


def summarize(values):
    return {"n": len(values), "min": min(values) if values else None,
            "median": statistics.median(values) if values else None,
            "max": max(values) if values else None}


def support(ds, timestamp):
    """Observed support only; image distance uses UNKNOWN coordinate units."""
    local = [d for d in ds if abs(d["millis"] - timestamp) <= 3000]
    segments = []
    for a, b in zip(ds, ds[1:]):
        if all(_finite_number(d.get(k)) for d in (a, b) for k in ("centroid_x", "centroid_y")):
            dt = b["millis"] - a["millis"]
            if dt > 0:
                segments.append({"end_ms": b["millis"], "gap_ms": dt,
                                 "relative_motion_per_s": math.hypot(b["centroid_x"]-a["centroid_x"],
                                                                     b["centroid_y"]-a["centroid_y"]) / (dt/1000)})
    result = {"window_radius_ms": 3000, "observation_interval_ms": ve.bracket(ds, timestamp),
              "local_observations": local,
              "local_segments": [s for s in segments if abs(s["end_ms"]-timestamp) <= 3000]}
    for side in ("before", "after"):
        selected = [d for d in local if (d["millis"] < timestamp) == (side == "before")]
        result[side + "_count"] = len(selected)
        result[side + "_raw_speed"] = summarize([d["speed"] for d in selected if _finite_number(d.get("speed"))])
        result[side + "_image_motion"] = summarize([s["relative_motion_per_s"] for s in result["local_segments"]
                                                   if (s["end_ms"] < timestamp) == (side == "before")])
    return result


def inspect_track(track, event, current_events, stats, image_calls):
    ds, sanitation = ve.clean_detections(track)
    ts = event["timestamp_ms"]
    emitted = [e.to_dict() for e in current_events]
    entry = next(e.timestamp_ms for e in current_events if e.event_type == "ENTRY")
    crossing = next((e.timestamp_ms for e in current_events if e.event_type == "CROSSING_PROXY"), None)
    outgoing = next((d["millis"] for d in ds if norm_zone(d.get("zone")) == "W"), None)
    runs = []
    for d in ds:
        z = norm_zone(d.get("zone"))
        if not runs or runs[-1]["zone"] != z:
            runs.append({"zone": z, "first_ms": d["millis"], "last_ms": d["millis"], "n": 1})
        else:
            runs[-1]["last_ms"] = d["millis"]
            runs[-1]["n"] += 1
    matches = [e for e in emitted if e["event_type"] == "RELEASE" and e["timestamp_ms"] == ts]
    reasons = []
    if matches:
        reasons.append("accepted_exact_timestamp_RELEASE; inspect emitted method/provenance")
    else:
        reasons.append("requested_timestamp_not_emitted_as_RELEASE; no nearest-time substitution")
    if stats.get("unsupported_metadata_restart"):
        reasons.append("metadata_candidate_failed_joint_support_guards")
    if not any(e["event_type"] == "STOP" for e in emitted):
        reasons.append("no_sustained_exact_zero_STOP_emitted; does_not_prove_absence_of_stop")
    if image_calls:
        reasons.append("image_solver_called_with_recorded_bounds_and_result")
    else:
        reasons.append("image_solver_not_called; see guard_facts")
    raw_speeds = [d["speed"] for d in ds if _finite_number(d.get("speed"))]
    durations = [v for v in (track.get("wait_s"), track.get("stay_duration_millis", 0)/1000
                 if _finite_number(track.get("stay_duration_millis", 0)) else None) if _finite_number(v) and v >= 0]
    stay = max(durations, default=0)
    metadata_ts = entry + stay*1000
    metadata_bounds = ve.bracket(ds,metadata_ts)
    speeds = [(d["millis"],d["speed"]) for d in ds if _finite_number(d.get("speed")) and d["speed"] >= 0]
    before = [s for t,s in speeds if metadata_ts-3000 <= t < metadata_ts]
    after = [s for t,s in speeds if metadata_ts <= t <= metadata_ts+3000]
    stops = [e["timestamp_ms"] for e in emitted if e["event_type"] == "STOP"]
    metadata_guards = {"stay_at_least_1_5s":stay>=1.5,
        "sustained_zero_stop_precedes_candidate":bool(stops and min(stops)<metadata_ts),
        "candidate_before_track_end":metadata_ts<ds[-1]["millis"],
        "bracket_gap_at_most_config":bool(metadata_bounds and metadata_bounds[1]-metadata_bounds[0]<=ve.CONFIG.max_detection_gap_s*1000),
        "at_least_six_speeds":len(speeds)>=6,"two_before":len(before)>=2,"two_after":len(after)>=2,
        "relative_median_guard":bool(before and after and statistics.median(before)<=.25*max(statistics.median(after),1e-9)),
        "legacy_plausibility_guard":_speed_restart_plausible(ds,metadata_ts/1000)}
    return {"event": event, "fingerprint": ve.track_fingerprint(track, ds),
            "zone_runs": runs, "entry_ms": entry, "zone_transition_proxy_ms": crossing,
            "first_outgoing_ms": outgoing, "track_end_ms": ds[-1]["millis"],
            "candidate_minus_entry_ms": ts-entry,
            "candidate_minus_zone_transition_ms": ts-crossing if crossing is not None else None,
            "candidate_minus_first_outgoing_ms": ts-outgoing if outgoing is not None else None,
            "candidate_minus_track_end_ms": ts-ds[-1]["millis"],
            "max_gap_ms": max((b["millis"]-a["millis"] for a,b in zip(ds,ds[1:])), default=None),
            "sampling_gaps_ms": [b["millis"]-a["millis"] for a,b in zip(ds,ds[1:])],
            "raw_speed_units": "UNKNOWN", "centroid_units": "UNKNOWN",
            "raw_speed_summary": summarize(raw_speeds), "raw_exact_zero_count": raw_speeds.count(0),
            "sustained_zero_events": [e for e in emitted if e["event_type"] == "STOP"],
            "support": support(ds, ts), "new_extractor_events": emitted, "stats": stats,
            "guard_facts": {"clean_count": len(ds), "sanitation": sanitation,
                "all_finite_centroids": all(_finite_number(d.get(k)) for d in ds for k in ("centroid_x", "centroid_y")),
                "incoming_observed": any(norm_zone(d.get("zone")) == "E" for d in ds),
                "crossing_proxy_observed": crossing is not None,
                "metadata_duration_raw": {k: track.get(k) for k in ("wait_s", "stay_duration_millis", "move_duration_millis")}},
            "metadata_candidate_ms":metadata_ts,"metadata_support_guards":metadata_guards,
            "image_calls": image_calls, "acceptance_rejection_reasons": reasons,
            "signal_state": "UNKNOWN", "stop_line_geometry": "UNKNOWN"}


class HashReader:
    def __init__(self, stream):
        self.stream, self.hash = stream, hashlib.sha256()
    def read(self, size):
        data = self.stream.read(size)
        self.hash.update(data)
        return data


def run():
    started = time.perf_counter()
    if OUT.exists():
        raise RuntimeError("exclusive event audit; refusing a second source pass")
    source = ROOT.parent / "data" / "ручная разметка" / "6_2025_2_14_20.json"
    inputs = {name: ROOT / "evidence/stage2b1_ablation" / ("events_"+name+".json") for name in ("A", "D")}
    with deny_annotation_reads():
        sets = {name: [e for e in json.loads(path.read_text(encoding="utf-8")) if e["movement"] == "E->W"]
                for name,path in inputs.items()}
        assert len(sets["A"]) == 26 and len(sets["D"]) == 8
        events = [("current" if name == "A" else "legacy", i, e) for name,es in sets.items() for i,e in enumerate(es)]
        ids = {e["source_track_id"] for _,_,e in events}
        producer = ["app/core/v9/vehicle_evidence.py", "app/core/v9/events.py", "app/core/temporal_evidence.py", "app/core/trajectory_events.py"]
        frozen = {p: sha((ROOT/p).read_bytes()) for p in producer}
        save("manifest.json", {"base_head_sha": BASE_HEAD,
            "runner_head_sha": subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
            "producer_contract_version": 1, "producer_schema_version": 1, "producer_sha256": frozen,
            "config": asdict(ve.CONFIG), "event_input_sha256": {k: sha(p.read_bytes()) for k,p in inputs.items()},
            "selection": "all 26 A and all 8 D E->W events; exact ID/fingerprint; no truth or phase errors",
            "source": str(source), "source_pass_limit": 1, "fitting_invocations": 0})
        tracks, count = [], 0
        with source.open("rb") as stream:
            reader = HashReader(stream)
            for tr in ev._iter_json_records(reader):
                count += 1
                if isinstance(tr,dict) and tr.get("id") in ids:
                    tracks.append(tr)
        assert reader.hash.hexdigest() == "57d04137cc1d8383d89edbd4a88084c1a874f8ee7e6eb2d206954624c2753651"
        assert len(tracks) == len(ids), "ID ambiguity/missing track: fail rather than choose"
        by_id = {tr["id"]: tr for tr in tracks}
        save("source_tracks.json", tracks)
        rows, details = [], []
        for membership,i,event in events:
            tr = by_id[event["source_track_id"]]
            ds,_ = ve.clean_detections(tr)
            fingerprint = ve.track_fingerprint(tr,ds)
            if membership == "current":
                assert fingerprint == event["provenance"]["track_fingerprint"]
            else:
                view = ev._track_event_view(tr)
                assert view[2][0] == event["timestamp_ms"] and view[2][3] == event["evidence_method"]
            calls = []
            original = ev._kinematic_release_candidate
            def capture(points, entry, upper):
                value = original(points,entry,upper)
                calls.append({"entry_ms": entry,"upper_ms":upper,"candidate":value})
                return value
            with patch.object(ev,"_kinematic_release_candidate",capture):
                emitted,stats = ve.extract_vehicle_evidence(tr,source_name=source.name)
            detail = inspect_track(tr,event,emitted,stats,calls)
            other = sets["D" if membership == "current" else "A"]
            counterparts = [e for e in other if e["source_track_id"] == event["source_track_id"]]
            detail.update(event_id=f"{membership}_{i:02d}", membership=membership,
                          other_set_timestamps_ms=[e["timestamp_ms"] for e in counterparts],
                          exact_timestamp_match=any(e["timestamp_ms"] == event["timestamp_ms"] for e in counterparts))
            details.append(detail)
            rows.append({"event_id": detail["event_id"], "membership":membership,"track_id":tr["id"],
                "fingerprint":fingerprint,"method":event["evidence_method"],"timestamp_ms":event["timestamp_ms"],
                "other_set_timestamps_ms":json.dumps(detail["other_set_timestamps_ms"]),
                "exact_timestamp_match":detail["exact_timestamp_match"],
                "zone_runs":json.dumps(detail["zone_runs"]),
                **{k:detail[k] for k in ("entry_ms","zone_transition_proxy_ms","first_outgoing_ms","track_end_ms",
                    "candidate_minus_entry_ms","candidate_minus_zone_transition_ms","candidate_minus_track_end_ms","max_gap_ms","raw_exact_zero_count")},
                "sustained_zero_STOP_count":len(detail["sustained_zero_events"]),
                **{k:json.dumps(detail["support"][k]) for k in ("before_count","after_count","before_raw_speed","after_raw_speed","before_image_motion","after_image_motion","observation_interval_ms")},
                "raw_speed_units":"UNKNOWN","centroid_units":"UNKNOWN",
                "acceptance_rejection_reasons":"; ".join(detail["acceptance_rejection_reasons"])})
        save("event_details.json",details)
        with (OUT/"events.csv").open("x",encoding="utf-8",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
        save("independent_review_template.json", {"status":"BLOCKED_EXTERNAL_TRUTH_ONLY", "instructions":
            "Leave truth unset until independent video/producer descriptions/verified geometry are supplied; raw tracks are not truth.",
            "missing_materials":["original video covering all selected tracks", "frame-to-millis synchronization and its uncertainty",
                "producer field specification and speed/centroid calibration", "verified zone polygons and stop-line geometry with coordinate transform"],
            "reviews":[{"event_id":d["event_id"],"track_id":d["event"]["source_track_id"],
                "independent_event_type":None,"interval_start_ms":None,"interval_end_ms":None,
                "visibility":None,"position_relative_to_verified_geometry":None,"geometry_source":None,
                "independent_source":None,"reviewer":None,"vehicle_timing_uncertainty_ms":None,
                "uncertainty_reason":None,"notes":None} for d in details]})
        assert frozen == {p:sha((ROOT/p).read_bytes()) for p in producer}
        save("summary.json", {"source_sha256":reader.hash.hexdigest(),"source_record_count":count,
            "union_track_count":len(tracks),"current_events":26,"legacy_events":8,"table_rows":len(rows),
            "exact_matching_rows":sum(d["exact_timestamp_match"] for d in details),
            "current_after_zone_transition":sum(d["membership"]=="current" and d["candidate_minus_zone_transition_ms"] is not None and d["candidate_minus_zone_transition_ms"]>0 for d in details),
            "union_tracks_with_emitted_sustained_zero_STOP":len({d["event"]["source_track_id"] for d in details if d["sustained_zero_events"]}),
            "fitting_invocations":0,"annotation_reads":0,"source_passes":1,"runtime_s":time.perf_counter()-started})


if __name__ == "__main__":
    run()
