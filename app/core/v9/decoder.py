from __future__ import annotations
import math
import json
import itertools
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence
import numpy as np
from scipy.ndimage import gaussian_filter1d

def _duration_penalty(period: float, k: int, max_d: int, targets=None, strength: float=2.0):
    if targets is None:
        targets = [float(period) / float(k)] * k
    d = np.arange(max_d + 1, dtype=float)
    out = np.zeros((k, max_d + 1), dtype=float)
    for z, target in enumerate(targets):
        target = max(2.0, float(target))
        sigma = max(4.0, 0.25 * target)
        out[z] = strength * ((d - target) / sigma) ** 2
    return out

def _segments_from_labels(labels: np.ndarray, dt: float=1.0):
    labels = np.asarray(labels, dtype=int)
    if labels.size == 0:
        return []
    out = []
    start = 0
    state = int(labels[0])
    for i in range(1, len(labels)):
        z = int(labels[i])
        if z != state:
            out.append((start * dt, i * dt, state))
            start, state = i, z
    out.append((start * dt, len(labels) * dt, state))
    return out

def _periodic_boundary_evidence(by_stream: Optional[Dict[str, List[float]]], period: float, resolution_s: float=0.5, smooth_s: float=2.5):
    if not by_stream or period <= 0:
        return (None, None)
    n = max(64, int(round(period / max(0.1, resolution_s))))
    profiles = []
    for ts in by_stream.values():
        if len(ts) < 4:
            continue
        h = np.zeros(n, dtype=float)
        for t in ts:
            h[int(float(t) % period / period * n) % n] += 1.0
        h = gaussian_filter1d(h, max(0.8, smooth_s / (period / n)), mode='wrap')
        d = gaussian_filter1d(np.roll(h, -1) - np.roll(h, 1), 0.8, mode='wrap')
        scale = float(np.std(d)) + 1e-06
        profiles.append(d / scale)
    if not profiles:
        return (None, None)
    evidence = np.mean(np.asarray(profiles), axis=0)
    evidence -= float(np.min(evidence))
    mx = float(np.max(evidence))
    if mx > 1e-09:
        evidence /= mx
    return np.arange(n, dtype=float) * period / n, evidence

def _boundary_coherence(segments, period, evidence_grid, evidence_values):
    if evidence_grid is None or evidence_values is None or not segments:
        return 0.0
    starts = [float(a) % period for a, _, _ in segments[1:]]
    if not starts:
        return 0.0
    vals = np.interp(np.asarray(starts) % period, evidence_grid, evidence_values, period=period)
    return float(np.mean(vals))

def decode_cyclic_hsmm(x: np.ndarray, probs: np.ndarray, period: float, k: int, dt: float=1.0, min_duration_s: Optional[float]=None, max_duration_s: Optional[float]=None, transition_penalty: float=0.25, duration_targets: Optional[Sequence[float]]=None, initial_phase: Optional[int]=None, duration_min_factor: float=0.65, duration_max_factor: float=1.35):
    n, _ = x.shape
    expected = float(period) / float(k)
    if duration_targets is None:
        duration_targets = [expected] * k
    targets = np.asarray(duration_targets, dtype=float)
    if len(targets) != k or np.any(~np.isfinite(targets)):
        targets = np.full(k, expected, dtype=float)
    targets = np.maximum(2.0, targets)
    global_min = float(min_duration_s if min_duration_s is not None else max(3.0, 0.04 * period))
    global_max = float(max_duration_s if max_duration_s is not None else min(0.9 * period, max(20.0, 2.25 * expected)))
    min_by_state = np.maximum(global_min, duration_min_factor * targets)
    max_by_state = np.minimum(global_max, duration_max_factor * targets)
    max_by_state = np.maximum(max_by_state, min_by_state + 1.0)
    min_d_by_state = np.maximum(2, np.round(min_by_state / dt).astype(int))
    max_d_by_state = np.maximum(min_d_by_state + 1, np.round(max_by_state / dt).astype(int))
    prob = probs.T[np.newaxis, :, :]
    xx = x[:, :, np.newaxis]
    emissions = np.sum(xx * np.log(prob) + (1.0 - xx) * np.log(1.0 - prob), axis=1)
    prefix = np.vstack([np.zeros((1, k)), np.cumsum(emissions, axis=0)])
    dpen = _duration_penalty(period, k, int(np.max(max_d_by_state)), targets, strength=2.0)
    best_total = -float('inf')
    best_payload = None
    initials = range(k) if initial_phase is None else [int(initial_phase) % k]
    for initial in initials:
        dp = np.full((n + 1, k), -float('inf'), dtype=float)
        prev_phase = np.full((n + 1, k), -1, dtype=np.int16)
        prev_d = np.zeros((n + 1, k), dtype=np.int16)
        dp[0, initial] = 0.0
        for t in range(1, n + 1):
            first_max = int(max_d_by_state[initial])
            if 2 <= t <= first_max:
                dp[t, initial] = prefix[t, initial]
                prev_d[t, initial] = t
            for phase in range(k):
                prev = (phase - 1) % k
                min_d, max_d = int(min_d_by_state[phase]), int(max_d_by_state[phase])
                lo, hi = max(min_d, t - max_d), t - min_d
                if lo > hi:
                    continue
                starts = np.arange(lo, hi + 1, dtype=int)
                durs = t - starts
                previous_scores = dp[starts, prev]
                if not np.any(np.isfinite(previous_scores)):
                    continue
                candidates = previous_scores + (prefix[t, phase] - prefix[starts, phase]) - dpen[phase, durs] - transition_penalty
                j = int(np.nanargmax(candidates))
                val = float(candidates[j])
                if val > dp[t, phase]:
                    dp[t, phase] = val
                    prev_phase[t, phase] = prev
                    prev_d[t, phase] = int(durs[j])
        end_phase = int(np.argmax(dp[n]))
        total = float(dp[n, end_phase])
        if total > best_total:
            best_total = total
            best_payload = (initial, end_phase, prev_phase, prev_d)
    if best_payload is None or not np.isfinite(best_total):
        raise RuntimeError('HSMM decoder could not find a valid cyclic segmentation')
    initial, phase, prev_phase, prev_d = best_payload
    t, segments = n, []
    while t > 0:
        dur = int(prev_d[t, phase])
        if dur <= 0:
            raise RuntimeError('corrupt HSMM backtrace')
        a = t - dur
        segments.append((a * dt, t * dt, int(phase)))
        pp = int(prev_phase[t, phase])
        t, phase = a, (pp if pp >= 0 else initial)
    segments.reverse()
    labels = np.zeros(n, dtype=np.int16)
    for a, b, z in segments:
        labels[int(round(a / dt)):int(round(b / dt))] = int(z)
    return labels, float(best_total), segments, {
        'min_duration_s': [float(v * dt) for v in min_d_by_state],
        'max_duration_s': [float(v * dt) for v in max_d_by_state],
        'duration_targets_s': [float(v) for v in targets],
        'transition_penalty': float(transition_penalty),
        'initial_phase_constraint': None if initial_phase is None else int(initial_phase) % k,
    }
