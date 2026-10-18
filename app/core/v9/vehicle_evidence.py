"""V9 evidence adapter; reuse existing timing candidates and zone-transition logic."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import statistics
from types import SimpleNamespace

from app.core.temporal_evidence import TemporalEvent
from app.core.trajectory_geometry import _finite_number
from app.core.trajectory_events import EventExtractionConfig, _first_sustained, _zone_crossing_timestamp


CONFIG = EventExtractionConfig()  # Shared gap/stop support limits; no label-based tuning.


def clean_detections(track):
    raw = track.get("detections") or []
    if not isinstance(raw, list):
        return [], {"invalid_detections": 1, "duplicate_detections": 0, "conflicting_timestamps": 0}
    groups = defaultdict(list)
    stats = {"invalid_detections": 0, "duplicate_detections": 0, "conflicting_timestamps": 0}
    for d in raw:
        if (not isinstance(d, dict) or not _finite_number(d.get("millis"))
                or d["millis"] < 0 or d["millis"] != int(d["millis"])):
            stats["invalid_detections"] += 1
            continue
        groups[int(d["millis"])].append(d)
    result = []
    for ts in sorted(groups):
        observations = groups[ts]
        # Same-time distinct measurements cannot define speed; do not pick an
        # arbitrary coordinate. Duplicate identical snapshots count once.
        keys = {json.dumps(d, sort_keys=True, default=str) for d in observations}
        if len(keys) != 1:
            stats["conflicting_timestamps"] += 1
            continue
        stats["duplicate_detections"] += len(observations) - 1
        result.append(observations[0])
    return result, stats


def track_fingerprint(track, detections):
    # Missing IDs no longer collapse different tracks with the same start time.
    core = [track.get("id"), track.get("zone_in"), track.get("zone_out"),
            track.get("stay_duration_millis"), track.get("wait_s"), detections]
    return hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()


def bracket(detections, timestamp_ms):
    before = [d["millis"] for d in detections if d["millis"] < timestamp_ms]
    after = [d["millis"] for d in detections if d["millis"] >= timestamp_ms]
    if not before or not after:
        return None
    return [max(before), min(after)]


def extract_vehicle_evidence(track, *, source_name="records"):
    # Local imports avoid circular import; V9's existing image-space solver stays
    # in events.py and is not duplicated with another fitted motion model.
    from .events import _kinematic_release_candidate
    from .primitives import norm_zone, _speed_restart_plausible
    if not isinstance(track, dict):
        return [], {"invalid_tracks": 1}
    ds, stats = clean_detections(track)
    origin, target = norm_zone(track.get("zone_in")), norm_zone(track.get("zone_out"))
    if not origin or not target or origin == target or not ds:
        return [], stats
    movement = f"{origin}->{target}"
    fingerprint = track_fingerprint(track, ds)
    gaps = [b["millis"] - a["millis"] for a, b in zip(ds, ds[1:])]
    max_gap = max(gaps, default=None)
    provenance = {"schema_version": 1, "source": source_name, "track_fingerprint": fingerprint,
                  "verified_stop_line": False, "signal_state_observed": False,
                  "confidence_semantics": "heuristic_vehicle_evidence_quality_NOT_lamp_probability",
                  "track_range_ms": [ds[0]["millis"], ds[-1]["millis"]],
                  "max_detection_gap_ms": max_gap, **stats}
    dirty = stats["invalid_detections"] or stats["conflicting_timestamps"]
    events = []

    def emit(ts, kind, method, score, quality, uncertainty, **extra):
        events.append(TemporalEvent(float(ts), kind, movement, track.get("id"), method,
                                    min(score, .4) if dirty else score,
                                    "LOW" if dirty else quality, uncertainty,
                                    {**provenance, **extra}))

    incoming = [d for d in ds if norm_zone(d.get("zone")) == origin]
    entry_ms = incoming[0]["millis"] if incoming else ds[0]["millis"]
    emit(entry_ms, "ENTRY", "input_zone_entry" if incoming else "first_detection_entry_proxy",
         .7 if incoming and len(ds) > 1 else .25,
         "MEDIUM" if incoming and len(ds) > 1 else "LOW", None,
         role="demand_only", left_censored=True)

    # Reuse common zone-transition detector. Unknown stop-line geometry means
    # that an observed zone transition is CROSSING_PROXY, never CROSSING.
    points = [SimpleNamespace(millis=d["millis"], zone=norm_zone(d.get("zone"))) for d in ds]
    crossing_ms, named = _zone_crossing_timestamp(points, zone_in=origin, zone_out=target)
    if crossing_ms is not None:
        bounds = bracket(ds, crossing_ms)
        sampled_gap = bounds[1] - bounds[0] if bounds else None
        emit(crossing_ms, "CROSSING_PROXY", "observed_zone_transition_proxy",
             .35, "LOW", None, role="movement_permission_proxy",
             observation_interval_ms=bounds, sampling_uncertainty_ms=sampled_gap,
             uncertainty_reason="distance_and_time_to_stop_line_unknown",
             eligible_proxy=bool(bounds and sampled_gap <= CONFIG.max_detection_gap_s * 1000))
    elif not named:
        # Do not invent even a crossing proxy from a track's final detection.
        stats["missing_crossing_zone_evidence"] = 1

    speeds = [(float(d["millis"]), float(d["speed"])) for d in ds
              if _finite_number(d.get("speed")) and d["speed"] >= 0]
    # Raw speed units are not established. Exact zero is unit-independent;
    # thresholds in m/s from metric geometry must not be applied to raw speed.
    intervals = [(b[0], b[1], (b[0] - a[0]) / 1000) for a, b in zip(speeds, speeds[1:])
                 if b[0] - a[0] <= CONFIG.max_detection_gap_s * 1000]
    # Reset sustained runs across missing observations instead of concatenating
    # them into a fictitious continuous stop.
    stop_ms = None
    chunks = []
    for item in intervals:
        if not chunks or item[0] - item[2] * 1000 > chunks[-1][-1][0]:
            chunks.append([])
        chunks[-1].append(item)
    for chunk in chunks:
        stop_ms = _first_sustained(chunk, lambda speed: speed == 0, CONFIG.stop_min_duration_s)
        if stop_ms is not None:
            break
    if stop_ms is not None:
        bounds = bracket(ds, stop_ms)
        emit(stop_ms, "STOP", "sustained_zero_raw_speed", .6, "MEDIUM",
             (bounds[1] - bounds[0]) if bounds else None,
             role="vehicle_stationary_not_proof_of_RED", observation_interval_ms=bounds,
             stop_location="unknown_relative_to_stop_line")

    durations = [v for v in (track.get("wait_s"),
                             track.get("stay_duration_millis", 0) / 1000
                             if _finite_number(track.get("stay_duration_millis", 0)) else None)
                 if _finite_number(v) and v >= 0]
    stay_s = max(durations, default=0)
    candidate = entry_ms + stay_s * 1000
    bounds = bracket(ds, candidate)
    before = [s for t, s in speeds if candidate - 3000 <= t < candidate]
    after = [s for t, s in speeds if candidate <= t <= candidate + 3000]
    # The old plausible() returns True with <6 speeds: explicitly disallow this.
    metadata_supported = (
        stay_s >= 1.5 and stop_ms is not None and stop_ms < candidate
        and candidate < ds[-1]["millis"] and bounds is not None
        and bounds[1] - bounds[0] <= CONFIG.max_detection_gap_s * 1000
        and len(speeds) >= 6 and len(before) >= 2 and len(after) >= 2
        and statistics.median(before) <= .25 * max(statistics.median(after), 1e-9)
        and _speed_restart_plausible(ds, candidate / 1000)
    )
    if metadata_supported:
        emit(candidate, "RELEASE", "metadata_dwell_end_restart_supported", .65, "MEDIUM",
             max(3000, bounds[1] - bounds[0]), role="vehicle_restart_proxy_not_GREEN",
             observation_interval_ms=bounds, proxy=True,
             uncertainty_reason="metadata_dwell_anchor_and_restart_sampling_unvalidated")
    else:
        if stay_s >= 1.5:
            stats["unsupported_metadata_restart"] = 1
        # Existing image-space candidate is a relative motion heuristic. Gaps,
        # invalid coordinates and missing origin/exit observations invalidate it.
        coords = [d for d in ds if _finite_number(d.get("centroid_x"))
                  and _finite_number(d.get("centroid_y"))]
        if len(coords) == len(ds) and len(ds) >= 14 and incoming and crossing_ms is not None:
            if max_gap <= CONFIG.max_detection_gap_s * 1000:
                candidate = _kinematic_release_candidate(ds, entry_ms, ds[-1]["millis"])
                if candidate is not None:
                    duration, ts, score, separation = candidate
                    bounds = bracket(ds, ts * 1000)
                    emit(ts * 1000, "RELEASE", "kinematic_restart_proxy", min(.65, score),
                         "MEDIUM", max(1300, (bounds[1] - bounds[0]) if bounds else 0),
                         role="vehicle_restart_proxy_not_GREEN", proxy=True,
                         observation_interval_ms=bounds, relative_low_speed_duration_s=duration,
                         image_speed_separation=separation,
                         uncertainty_reason="image_motion_restart_and_smoothing_unvalidated")
    return events, stats


def select_permission_events(events):
    """Per movement: observed restart first, otherwise eligible zone proxy.

    No demand entry substitution. Weak proxy uncertainty remains visible.
    Timestamp-based HSMM cannot yet consume the full uncertainty distribution.
    """
    releases, proxies = defaultdict(list), defaultdict(list)
    for event in events:
        if event.event_type == "RELEASE" and event.evidence_quality != "LOW":
            releases[event.movement].append(event)
        elif (event.event_type == "CROSSING_PROXY" and event.provenance.get("eligible_proxy")
              and not event.provenance.get("conflicting_timestamps")
              and not event.provenance.get("invalid_detections")):
            proxies[event.movement].append(event)
    chosen, methods = [], {}
    for movement in sorted(set(releases) | set(proxies)):
        values = releases.get(movement) or proxies[movement]
        chosen.extend(values)
        methods[movement] = "release_proxy" if releases.get(movement) else "zone_crossing_proxy"
    return sorted(chosen, key=lambda event: event.timestamp_ms), methods


def select_permission_events_per_track(events):
    """Opt-in: one permission proxy per source/track/movement, never demand.

    Preserve each free-flowing vehicle even if another car on the movement
    stopped. Prefer its own supported restart; otherwise its eligible crossing.
    Neither observation establishes a lamp color or switch timestamp.
    """
    grouped = defaultdict(lambda: defaultdict(list))

    def order(event):
        return (event.timestamp_ms,event.event_type,event.movement,
                str(event.provenance.get('source','')),
                str(event.provenance.get('track_fingerprint','')),
                event.evidence_method,json.dumps(event.to_dict(),sort_keys=True))

    for event in events:
        fingerprint=event.provenance.get('track_fingerprint')
        if not isinstance(fingerprint,str) or not fingerprint:
            continue
        if event.event_type=='RELEASE' and event.evidence_quality!='LOW':
            kind='release_proxy'
        elif (event.event_type=='CROSSING_PROXY' and event.provenance.get('eligible_proxy')
              and not event.provenance.get('conflicting_timestamps')
              and not event.provenance.get('invalid_detections')):
            kind='zone_crossing_proxy'
        else:
            continue
        key=(str(event.provenance.get('source','')),fingerprint,event.movement)
        grouped[key][kind].append(event)
    chosen,counts=[],defaultdict(Counter)
    for kinds in grouped.values():
        kind='release_proxy' if kinds.get('release_proxy') else 'zone_crossing_proxy'
        event=min(kinds[kind],key=order)
        chosen.append(event)
        counts[event.movement][kind]+=1
    methods={movement:('mixed_release_and_crossing_proxy' if len(kinds)>1 else next(iter(kinds)))
             for movement,kinds in sorted(counts.items())}
    return sorted(chosen,key=order),methods


def diagnostics(events, selected, methods, track_stats):
    weak = sum(e.evidence_quality == "LOW" or e.temporal_uncertainty_ms is None for e in events)
    selected_weak = sum(e.evidence_quality == "LOW" or e.temporal_uncertainty_ms is None for e in selected)
    return {"contract_version": 1, "event_type_counts": dict(Counter(e.event_type for e in events)),
            "event_method_counts": dict(Counter(e.evidence_method for e in events)),
            "total_events": len(events), "weak_or_unknown_uncertainty_events": weak,
            "weak_or_unknown_uncertainty_percent": 100 * weak / len(events) if events else None,
            "selected_event_count": len(selected), "selected_weak_or_unknown_uncertainty_events": selected_weak,
            "selected_weak_or_unknown_uncertainty_percent": 100 * selected_weak / len(selected) if selected else None,
            "selection_by_movement": methods, "track_quality_counts": dict(track_stats),
            "phase_model_receives": "timestamps_of_permission_proxies; NOT_lamp_states",
            "uncertainty_scope": "heuristic_or_unknown_not_calibrated_lamp_transition_interval"}
