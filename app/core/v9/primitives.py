from __future__ import annotations
import math
import json
import itertools
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence
import numpy as np
from scipy.ndimage import gaussian_filter1d
from sklearn.cluster import KMeans

def norm_zone(z) -> Optional[str]:
    if z is None:
        return None
    s = str(z).replace('_', '').strip().upper()
    return s or None

def _speed_restart_plausible(ds: Sequence[dict], target_s: float) -> bool:
    points = []
    for d in ds:
        if d.get('millis') is None or d.get('speed') is None:
            continue
        try:
            speed = float(d['speed'])
        except (TypeError, ValueError):
            continue
        if speed < 0:
            continue
        points.append((float(d['millis']) / 1000.0, speed))
    if len(points) < 6:
        return True
    before = [s for t, s in points if target_s - 3.0 <= t <= target_s]
    after = [s for t, s in points if target_s <= t <= target_s + 3.0]
    if not before or not after:
        return False
    before_med = float(np.median(before))
    after_med = float(np.median(after))
    spread = float(np.std(before)) + 1e-06
    return after_med - before_med >= max(1.0, 0.75 * spread)

def _circular_recurrence(by_stream: Dict[str, List[float]], period: float) -> float:
    vals = []
    for ts in by_stream.values():
        if len(ts) < 6:
            continue
        ph = 2.0 * np.pi * (np.asarray(ts) % period) / period
        r = float(np.hypot(np.cos(ph).mean(), np.sin(ph).mean()))
        vals.append(r * math.sqrt(len(ts)))
    return float(np.mean(vals)) if vals else 0.0

def _lag_recurrence(by_stream: Dict[str, List[float]], period: float, dt: float=2.0) -> float:
    if not by_stream:
        return 0.0
    end_s = max((max(ts) for ts in by_stream.values()))
    n = int(math.floor(end_s / dt)) + 1
    if n < int(period / dt) + 10:
        return 0.0
    names = sorted(by_stream)
    idx = {s: i for i, s in enumerate(names)}
    a = np.zeros((n, len(names)), dtype=np.float32)
    for s, ts in by_stream.items():
        for t in ts:
            i = int(t / dt)
            if 0 <= i < n:
                a[i, idx[s]] = 1.0
    a = gaussian_filter1d(a, 0.9, axis=0, mode='nearest')
    lag = int(round(period / dt))
    if lag <= 0 or lag >= n - 10:
        return 0.0
    x = a[:-lag]
    y = a[lag:]
    x = x - x.mean(axis=0, keepdims=True)
    y = y - y.mean(axis=0, keepdims=True)
    num = float(np.sum(x * y))
    den = math.sqrt(float(np.sum(x * x) * np.sum(y * y))) + 1e-09
    return num / den

def _normalize_vector(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    lo = float(np.min(values))
    hi = float(np.max(values))
    if hi - lo < 1e-09:
        return np.zeros_like(values)
    return np.clip((values - lo) / (hi - lo), 0.0, 1.0)

def infer_period(by_stream: Dict[str, List[float]], pmin: float=45.0, pmax: float=180.0, step: float=0.5):
    periods = np.arange(pmin, pmax + 1e-09, step)
    circular = np.array([_circular_recurrence(by_stream, float(p)) for p in periods])
    lag = np.array([_lag_recurrence(by_stream, float(p)) for p in periods])
    circ_n = _normalize_vector(circular)
    lag_n = _normalize_vector(lag)
    score = 0.8 * circ_n + 0.2 * lag_n
    i = int(np.argmax(score))
    if 0 < i < len(periods) - 1:
        y0, y1, y2 = (float(score[i - 1]), float(score[i]), float(score[i + 1]))
        den = y0 - 2.0 * y1 + y2
        if abs(den) > 1e-09:
            delta = float(np.clip(0.5 * (y0 - y2) / den, -0.45, 0.45))
            period = float(periods[i] + delta * step)
        else:
            period = float(periods[i])
    else:
        period = float(periods[i])
    order = np.argsort(score)[::-1][:8]
    top = [
        {
            'period_s': float(periods[j]),
            'combined_score': float(score[j]),
            'circular_score': float(circular[j]),
            'lag_score': float(lag[j]),
        }
        for j in order
    ]
    return period, {
        'method': 'hybrid_circular_plus_multistream_lag_recurrence',
        'search_range_s': [float(pmin), float(pmax)],
        'grid_step_s': float(step),
        'top_candidates': top,
    }

def build_streams_from_base(events, base_ms):
    by_stream = defaultdict(list)
    for row in events:
        by_stream[row[1]].append((float(row[0]) - float(base_ms)) / 1000.0)
    end_s = max((max(ts) for ts in by_stream.values()), default=0.0)
    return dict(by_stream), float(base_ms), float(end_s)

def build_occupancy_matrix(by_stream: Dict[str, List[float]], end_s: float, dt: float=1.0):
    names = sorted(by_stream, key=lambda s: (-len(by_stream[s]), s))
    n = int(math.floor(end_s / dt)) + 1
    x = np.zeros((n, len(names)), dtype=np.float32)
    index = {s: j for j, s in enumerate(names)}
    for stream, ts in by_stream.items():
        for t in ts:
            i = int(t / dt)
            if 0 <= i < n:
                x[i, index[stream]] = 1.0
    return x, names

def phase_labels_for_time(n: int, dt: float, period: float, k: int, offset: float):
    t = np.arange(n, dtype=float) * dt
    phase_pos = (t - offset) % period / period
    return np.floor(phase_pos * k).astype(int) % k

def fit_bernoulli_templates(x: np.ndarray, labels: np.ndarray, k: int):
    n, s = x.shape
    probs = np.full((k, s), 0.5, dtype=float)
    for z in range(k):
        mask = labels == z
        count = int(np.sum(mask))
        if count:
            probs[z] = (np.sum(x[mask], axis=0) + 0.5) / (count + 1.0)
    return np.clip(probs, 0.01, 0.99)

def _pointwise_loglik(x: np.ndarray, probs: np.ndarray, labels: np.ndarray) -> float:
    p = probs[labels]
    return float(np.sum(x * np.log(p) + (1.0 - x) * np.log(1.0 - p)))

def initial_offset_search(x, period, k, dt=1.0):
    best = (-float('inf'), 0.0)
    for off in np.arange(0.0, period, max(1.0, 2.0 * dt)):
        labels = phase_labels_for_time(x.shape[0], dt, period, k, float(off))
        lp = _pointwise_loglik(x, fit_bernoulli_templates(x, labels, k), labels)
        if lp > best[0]:
            best = (lp, float(off))
    return best[1]

def _stream_phase_centers(by_stream: Dict[str, List[float]], period: float):
    names, points, weights = [], [], []
    for stream, ts in by_stream.items():
        if len(ts) < 4:
            continue
        a = 2.0 * np.pi * (np.asarray(ts) % period) / period
        c, s = float(np.cos(a).mean()), float(np.sin(a).mean())
        r = float(np.hypot(c, s))
        names.append(stream)
        points.append([c, s])
        weights.append(max(0.25, math.sqrt(len(ts)) * max(r, 0.15)))
    if not points:
        return [], np.zeros((0, 2)), np.zeros(0)
    return names, np.asarray(points, dtype=float), np.asarray(weights, dtype=float)

def _group_onset(by_stream, streams, period, bins=200, smooth_s=2.0):
    if not streams:
        return None, 0.0
    profile = np.zeros(bins, dtype=float)
    total_w = 0.0
    for stream in streams:
        ts = np.asarray(by_stream.get(stream, []), dtype=float)
        if not ts.size:
            continue
        h, _ = np.histogram(ts % period, bins=np.linspace(0.0, period, bins + 1))
        h = gaussian_filter1d(h.astype(float), max(0.8, smooth_s / (period / bins)), mode='wrap')
        w = max(1.0, len(ts)) ** 0.25
        profile += w * h
        total_w += w
    if total_w <= 0:
        return None, 0.0
    profile /= total_w
    deriv = gaussian_filter1d(
        (np.roll(profile, -1) - np.roll(profile, 1)) / (2.0 * period / bins),
        1.0,
        mode='wrap',
    )
    idx = int(np.argmax(deriv))
    return float(idx * period / bins), float(deriv[idx])

def initial_seed_from_streams(by_stream: Dict[str, List[float]], period: float, k: int, n: int, dt: float):
    names, points, weights = _stream_phase_centers(by_stream, period)
    if len(names) < k or len(np.unique(np.round(points, 8), axis=0)) < k:
        return None
    try:
        km = KMeans(n_clusters=k, n_init=50, random_state=42).fit(points, sample_weight=weights)
    except Exception:
        return None
    groups = []
    for j in range(k):
        streams = [names[i] for i, lab in enumerate(km.labels_) if int(lab) == j]
        onset, strength = _group_onset(by_stream, streams, period)
        if onset is None:
            return None
        groups.append((onset, strength, streams))
    groups.sort(key=lambda item: item[0])
    onsets = [g[0] for g in groups]
    gaps = []
    for i, a in enumerate(onsets):
        b = onsets[(i + 1) % k] + (period if i == k - 1 else 0.0)
        gaps.append(b - a)
    if min(gaps) < max(3.0, 0.03 * period):
        return None
    t = np.arange(n, dtype=float) * dt
    labels = np.zeros(n, dtype=int)
    for i, a in enumerate(onsets):
        b = onsets[(i + 1) % k] if i < k - 1 else onsets[0] + period
        labels[(t - a) % period < (b - a)] = i
    return labels, {
        'method': 'anonymous_stream_center_cluster_plus_group_onset',
        'group_onsets_s': [float(x) for x in onsets],
        'durations_s': [float(x) for x in gaps],
        'group_sizes': [int(len(g[2])) for g in groups],
        'onset_strengths': [float(g[1]) for g in groups],
    }
