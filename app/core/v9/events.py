from __future__ import annotations
import math
import json
import itertools
import codecs
import zipfile
from array import array
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence
import numpy as np
from scipy.ndimage import gaussian_filter1d

from .primitives import norm_zone, _speed_restart_plausible
from .fit import anonymous_phase_name

def _track_detection_times(tr):
    ds = [
        d for d in tr.get('detections') or []
        if isinstance(d, dict) and d.get('millis') is not None
    ]
    if len(ds) < 2:
        return ds
    previous = float(ds[0]['millis'])
    ordered = True
    for d in ds[1:]:
        current = float(d['millis'])
        if current < previous:
            ordered = False
            break
        previous = current
    if not ordered:
        ds.sort(key=lambda d: float(d['millis']))
    return ds

def _iter_json_records(stream, *, chunk_size=64 * 1024, max_object_chars=16 * 1024 * 1024):
    decoder = json.JSONDecoder()
    utf8 = codecs.getincrementaldecoder("utf-8")()
    buffer = ""
    eof = False
    started = False
    expect_value = True

    def fill() -> bool:
        nonlocal buffer, eof
        if eof:
            return False
        chunk = stream.read(chunk_size)
        if chunk:
            buffer += chunk if isinstance(chunk, str) else utf8.decode(chunk, final=False)
            return True
        buffer += utf8.decode(b"", final=True)
        eof = True
        return False

    while True:
        if not started:
            buffer = buffer.lstrip()
            if not buffer:
                if not fill():
                    raise ValueError("Trajectory JSON root must be a list")
                continue
            if not buffer.startswith("["):
                raise ValueError("Trajectory JSON root must be a list")
            buffer = buffer[1:]
            started = True

        buffer = buffer.lstrip()
        if not buffer:
            if eof:
                raise ValueError("unterminated trajectory JSON array")
            fill()
            continue

        if expect_value:
            if buffer[0] == "]":
                buffer = buffer[1:]
                expect_value = False
                continue
            while True:
                try:
                    value, end_index = decoder.raw_decode(buffer)
                    break
                except json.JSONDecodeError as exc:
                    if eof:
                        raise ValueError(
                            f"invalid trajectory JSON: {exc.msg} at char {exc.pos}"
                        ) from exc
                    if len(buffer) > max_object_chars:
                        raise ValueError(
                            "trajectory JSON object exceeds bounded streaming size"
                        ) from exc
                    fill()
            buffer = buffer[end_index:]
            expect_value = False
            if isinstance(value, dict):
                yield value
            continue

        buffer = buffer.lstrip()
        if not buffer:
            if eof:
                raise ValueError("unterminated trajectory JSON array")
            fill()
            continue
        if buffer[0] == ",":
            buffer = buffer[1:]
            expect_value = True
            continue
        if buffer[0] == "]":
            buffer = buffer[1:]
            if buffer.strip():
                raise ValueError("unexpected data after trajectory JSON array")
            while not eof:
                fill()
                if buffer.strip():
                    raise ValueError("unexpected data after trajectory JSON array")
            return
        raise ValueError("expected ',' or ']' in trajectory JSON array")


def _iter_json_records_from_path(path: Path):
    with Path(path).open("rb") as stream:
        yield from _iter_json_records(stream)


def _iter_source_records(path: Path):
    path = Path(path)
    if path.is_file() and path.suffix.lower() == ".json":
        yield path.name, _iter_json_records_from_path(path)
        return
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            for info in sorted(archive.infolist(), key=lambda item: item.filename):
                if info.is_dir() or not info.filename.lower().endswith(".json"):
                    continue
                member = Path(info.filename)
                if member.is_absolute() or ".." in member.parts:
                    raise ValueError(f"unsafe ZIP member path: {info.filename}")
                stream = archive.open(info, "r")
                try:
                    records = _iter_json_records(stream)
                    yield info.filename, records
                    for _ in records:
                        pass
                finally:
                    stream.close()
        return
    if path.is_dir():
        for item in sorted(path.rglob("*.json")):
            name = item.name.lower()
            if (
                name.endswith("_manual_marks.json")
                or "phase_discovery" in name
                or "benchmark" in name
            ):
                continue
            yield str(item), _iter_json_records_from_path(item)
        return
    if not path.exists():
        raise FileNotFoundError(path)
    raise ValueError(f"unsupported V9 source: {path}")


def _track_event_view(tr, ds=None):
    zin = norm_zone(tr.get("zone_in"))
    zout = norm_zone(tr.get("zone_out"))
    if ds is None:
        ds = _track_detection_times(tr)
    if not zin or not zout or zin == zout or not ds:
        return None

    entry_ms = next(
        (
            float(d["millis"])
            for d in ds
            if norm_zone(d.get("zone")) == zin
        ),
        float(ds[0]["millis"]),
    )
    exit_ms = next(
        (
            float(d["millis"])
            for d in ds
            if norm_zone(d.get("zone")) == zout
        ),
        float(ds[-1]["millis"]),
    )
    stream = f"{zin}->{zout}"
    entry_event = (
        entry_ms,
        stream,
        tr.get("id"),
        "input_zone_entry",
    )

    stay_s = max(
        0.0,
        float(tr.get("wait_s") or 0.0),
        float(tr.get("stay_duration_millis") or 0.0) / 1000.0,
    )
    main_ms = entry_ms
    method = "input_zone_entry"
    release = None

    if stay_s >= 1.5:
        target_ms = entry_ms + stay_s * 1000.0
        if (
            target_ms <= exit_ms + 1e-6
            and target_ms <= entry_ms + 0.95 * max(1.0, exit_ms - entry_ms)
            and _speed_restart_plausible(ds, target_ms / 1000.0)
        ):
            main_ms = min(target_ms, exit_ms)
            method = "metadata_dwell_end_restart"
            release = (
                main_ms,
                stream,
                tr.get("id"),
                method,
                0.9,
            )

    if release is None and method == "input_zone_entry":
        kin = _kinematic_release_candidate(ds, entry_ms, exit_ms)
        if kin is not None:
            _duration, rt, conf, _separation = kin
            release = (
                rt * 1000.0,
                stream,
                tr.get("id"),
                "kinematic_release",
                float(conf),
            )

    return (
        (main_ms, stream, tr.get("id"), method),
        entry_event,
        release,
    )


def load_event_views(path: Path):
    main_events, entry_events, release_evidence = [], [], []
    method_counts = defaultdict(int)
    files = []
    seen = set()
    recording_start_ms = None

    for source_name, records in _iter_source_records(Path(path)):
        files.append(source_name)
        for tr in records:
            if not isinstance(tr, dict):
                continue
            ds = _track_detection_times(tr)
            if ds:
                first_ms = float(ds[0]["millis"])
                if recording_start_ms is None or first_ms < recording_start_ms:
                    recording_start_ms = first_ms
            key = (
                tr.get("id"),
                float(ds[0]["millis"]) if ds else None,
                norm_zone(tr.get("zone_in")),
                norm_zone(tr.get("zone_out")),
            )
            if key in seen:
                continue
            seen.add(key)
            view = _track_event_view(tr, ds)
            if view is None:
                continue
            main_event, entry_event, release = view
            main_events.append(main_event)
            entry_events.append(entry_event)
            if release is not None:
                release_evidence.append(release)
            method_counts[main_event[3]] += 1

    main_events.sort(key=lambda x: x[0])
    entry_events.sort(key=lambda x: x[0])
    release_evidence.sort(key=lambda x: x[0])
    if not main_events:
        raise ValueError(f"no usable trajectory JSON files found in {path}")
    return (
        main_events,
        entry_events,
        release_evidence,
        dict(method_counts),
        files,
        recording_start_ms,
    )


def load_event_streams(path: Path):
    """
    Stream a source into the compact representation consumed by V9 discovery.

    Unlike load_event_views(), this avoids allocating one Python tuple per
    traffic event. Timestamps are kept in packed C doubles per movement stream,
    which is substantially smaller for multi-gigabyte archives.
    """
    main_absolute = defaultdict(lambda: array('d'))
    entry_absolute = defaultdict(lambda: array('d'))
    release_absolute = defaultdict(lambda: array('d'))
    method_counts = defaultdict(int)
    release_method_counts = defaultdict(int)
    source_files = []
    seen = set()
    recording_start_ms = None
    analysis_base_ms = None
    trajectory_count = 0
    event_count = 0

    for source_name, records in _iter_source_records(Path(path)):
        source_files.append(source_name)
        for tr in records:
            if not isinstance(tr, dict):
                continue
            trajectory_count += 1
            ds = _track_detection_times(tr)
            if ds:
                first_ms = float(ds[0]['millis'])
                if recording_start_ms is None or first_ms < recording_start_ms:
                    recording_start_ms = first_ms
            key = (
                tr.get("id"),
                float(ds[0]["millis"]) if ds else None,
                norm_zone(tr.get("zone_in")),
                norm_zone(tr.get("zone_out")),
            )
            if key in seen:
                continue
            seen.add(key)

            view = _track_event_view(tr, ds)
            if view is None:
                continue
            main_event, entry_event, release = view
            main_ms, stream = float(main_event[0]), main_event[1]
            entry_ms = float(entry_event[0])
            main_absolute[stream].append(main_ms)
            entry_absolute[stream].append(entry_ms)
            event_count += 1
            if analysis_base_ms is None or main_ms < analysis_base_ms:
                analysis_base_ms = main_ms
            method_counts[main_event[3]] += 1
            if release is not None:
                release_absolute[release[1]].append(float(release[0]))
                release_method_counts[release[3]] += 1

    if not main_absolute:
        raise ValueError(f"no usable trajectory JSON files found in {path}")
    if analysis_base_ms is None:
        raise ValueError(f"unable to determine analysis base for {path}")

    def relative(values):
        return array(
            'd',
            ((float(value) - analysis_base_ms) / 1000.0 for value in values),
        )

    by_stream = {
        stream: relative(sorted(values))
        for stream, values in main_absolute.items()
    }
    entry_streams = {
        stream: relative(sorted(values))
        for stream, values in entry_absolute.items()
    }
    release_streams = {
        stream: relative(sorted(values))
        for stream, values in release_absolute.items()
    }
    return (
        by_stream,
        entry_streams,
        release_streams,
        dict(method_counts),
        dict(release_method_counts),
        source_files,
        recording_start_ms,
        float(analysis_base_ms),
        int(trajectory_count),
        int(event_count),
    )

def load_tracks(path: Path):
    tracks = []
    for _name, records in _iter_source_records(Path(path)):
        tracks.extend(records)
    if not tracks:
        raise ValueError(f"no trajectory JSON files found in {path}")
    return tracks


def load_source(path: Path):
    path = Path(path)
    if path.is_file() and path.suffix.lower() in {".json", ".zip"}:
        return load_tracks(path), [path]
    if not path.is_dir():
        raise FileNotFoundError(path)

    tracks = []
    files = []
    seen = set()
    for item in sorted(path.rglob("*.json")):
        name = item.name.lower()
        if name.endswith("_manual_marks.json") or "phase_discovery" in name or "benchmark" in name:
            continue
        files.append(item)
        for tr in _iter_json_records_from_path(item):
            ds = _track_detection_times(tr)
            if not ds:
                continue
            key = (
                tr.get("id"),
                float(ds[0]["millis"]),
                norm_zone(tr.get("zone_in")),
                norm_zone(tr.get("zone_out")),
            )
            if key in seen:
                continue
            seen.add(key)
            tracks.append(tr)
    tracks.sort(key=lambda tr: float(_track_detection_times(tr)[0]["millis"]))
    if not tracks:
        raise ValueError(f"no trajectory JSON files found in {path}")
    return tracks, files


def _recording_start_ms(tracks):
    vals = [
        float(ds[0]['millis'])
        for tr in tracks
        if (ds := _track_detection_times(tr))
    ]
    if not vals:
        raise ValueError('unable to determine recording start')
    return min(vals)

def _kinematic_release_candidate(ds, entry_ms, exit_ms):
    pts = []
    for d in ds:
        try:
            if d.get('centroid_x') is None or d.get('centroid_y') is None:
                continue
            pts.append((
                float(d['millis']) / 1000.0,
                float(d['centroid_x']),
                float(d['centroid_y']),
            ))
        except (TypeError, ValueError):
            continue
    if len(pts) < 14:
        return None

    t = np.asarray([p[0] for p in pts], dtype=float)
    xy = np.asarray([[p[1], p[2]] for p in pts], dtype=float)
    dt = np.diff(t)
    ok = dt > 0.001
    if int(np.sum(ok)) < 12:
        return None

    v = np.linalg.norm(np.diff(xy, axis=0), axis=1) / np.maximum(dt, 0.001)
    v = np.where(np.isfinite(v), v, 0.0)
    med_dt = float(np.median(dt[ok]))
    sigma = max(1.0, 0.65 / max(med_dt, 0.001))
    vs = gaussian_filter1d(v, sigma, mode='nearest')
    pos = vs[vs > 1e-7]
    if len(pos) < 10:
        return None

    z = np.log(pos + 1e-6)
    c = np.percentile(z, [20.0, 80.0]).astype(float)
    for _ in range(12):
        lab = np.argmin(
            np.abs(z[:, None] - c[None, :]),
            axis=1,
        )
        nc = np.array([
            float(np.mean(z[lab == j])) if np.any(lab == j) else c[j]
            for j in range(2)
        ])
        if float(np.max(np.abs(nc - c))) < 0.0001:
            break
        c = nc

    lo, hi = np.sort(c)
    separation = float(hi - lo)
    if separation < 0.55:
        return None
    threshold = float(np.exp((lo + hi) * 0.5))
    low = vs <= threshold

    stop_min = max(1.5, 7.0 * med_dt)
    runs = []
    start = None
    for i, flag in enumerate(low):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(low)))

    candidates = []
    for a, b in runs:
        if b >= len(t):
            continue
        duration = float(t[b] - t[a])
        if duration < stop_min:
            continue
        if t[b] >= exit_ms / 1000.0 - max(0.5, 3 * med_dt):
            continue
        width = max(
            3,
            int(round(0.9 / max(med_dt, 0.001))),
        )
        after = vs[b:min(len(vs), b + width)]
        if len(after) < 3:
            continue
        frac = float(np.mean(after > threshold * 1.1))
        med_after = float(np.median(after))
        if frac < 0.65 or med_after <= threshold * 1.1:
            continue
        confidence = float(
            np.clip(
                0.5
                + 0.1 * math.log1p(duration)
                + 0.1 * min(2.5, separation),
                0.0,
                0.92,
            )
        )
        candidates.append((
            duration,
            float(t[b]),
            confidence,
            separation,
        ))
    return max(candidates, key=lambda q: (q[2], q[0], -q[1])) if candidates else None

def extract_event_views(tracks):
    main_events, entry_events = [], []
    release_evidence = []
    method_counts = defaultdict(int)

    for tr in tracks:
        if not isinstance(tr, dict):
            continue
        view = _track_event_view(tr)
        if view is None:
            continue
        main_event, entry_event, release = view
        main_events.append(main_event)
        entry_events.append(entry_event)
        if release is not None:
            release_evidence.append(release)
        method_counts[main_event[3]] += 1

    main_events.sort(key=lambda x: x[0])
    entry_events.sort(key=lambda x: x[0])
    release_evidence.sort(key=lambda x: x[0])
    if not main_events:
        raise ValueError('unable to extract traffic events')
    return (
        main_events,
        entry_events,
        release_evidence,
        dict(method_counts),
    )

def _circular_center(values, period):
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return None
    ang = 2.0 * np.pi * (values % period) / period
    return float(
        math.atan2(
            float(np.mean(np.sin(ang))),
            float(np.mean(np.cos(ang))),
        )
        % (2.0 * np.pi)
        * period
        / (2.0 * np.pi)
    )

def periodic_baseline_from_segments(segments, period, end_s):
    if not segments or period <= 0:
        return [], {}
    k = max(int(z) for _, _, z in segments) + 1
    centers = {}
    for z in range(k):
        c = _circular_center(
            [float(a) % period for a, _, zz in segments if int(zz) == z],
            period,
        )
        if c is not None:
            centers[z] = c
    if len(centers) != k:
        return list(segments), {z: 0.0 for z in range(k)}

    starts = sorted((float(c), int(z)) for z, c in centers.items())
    points = []
    for cycle in range(-1, int(math.ceil(end_s / period)) + 1):
        points.extend((cycle * period + off, z) for off, z in starts)
    points.sort()

    baseline = []
    for i, (a, z) in enumerate(points):
        b = points[i + 1][0] if i + 1 < len(points) else a + period
        if b <= 0.0 or a >= end_s:
            continue
        aa, bb = max(0.0, a), min(float(end_s), b)
        if aa < bb:
            baseline.append((aa, bb, z))
    return baseline, centers

def _phase_duration_targets_from_baseline(baseline, k):
    durations = [[] for _ in range(k)]
    for a, b, z in baseline:
        if 0 <= int(z) < k:
            durations[int(z)].append(float(b - a))
    return [
        float(np.median(values)) if values else 0.0
        for values in durations
    ]

def detect_temporary_phase_deviations(segments, baseline, k):
    base_d = _phase_duration_targets_from_baseline(baseline, k)
    robust = []
    for z in range(k):
        values = [
            float(b - a)
            for a, b, zz in segments
            if int(zz) == z
        ]
        if values:
            median = float(np.median(values))
            mad = float(
                np.median(
                    np.abs(
                        np.asarray(values) - median
                    )
                )
            )
            robust.append(
                max(
                    6.0,
                    2.5 * mad,
                    0.2 * max(base_d[z], 1.0),
                )
            )
        else:
            robust.append(
                max(
                    6.0,
                    0.2 * max(base_d[z], 1.0),
                )
            )

    out = []
    for idx, (a, b, z) in enumerate(segments):
        if idx in (0, len(segments) - 1):
            continue
        z = int(z)
        target = float(base_d[z]) if 0 <= z < k else 0.0
        if target <= 0:
            continue
        observed = float(b - a)
        delta = observed - target
        if abs(delta) < robust[z]:
            continue
        out.append({
            'start_s': float(a),
            'end_s': float(b),
            'phase': anonymous_phase_name(z),
            'observed_duration_s': observed,
            'baseline_duration_s': target,
            'delta_s': delta,
            'type': (
                'temporary_phase_extension'
                if delta > 0
                else 'temporary_phase_shortening'
            ),
            'cause': 'unknown',
        })
    return out
