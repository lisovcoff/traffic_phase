from __future__ import annotations
import math
import json
import itertools
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence
import numpy as np
from scipy.ndimage import gaussian_filter1d

from .primitives import (
    fit_bernoulli_templates,
    initial_offset_search,
    initial_seed_from_streams,
    phase_labels_for_time,
    _pointwise_loglik,
)
from .decoder import (
    decode_cyclic_hsmm,
    _periodic_boundary_evidence,
    _boundary_coherence,
    _segments_from_labels,
)

def _seed_labels_to_fit(labels, x, k, period, by_stream, dt, seed_info, evidence_grid, evidence_values):
    probs = fit_bernoulli_templates(x, labels, k)
    segments = _segments_from_labels(labels, dt)
    point_ll = _pointwise_loglik(x, probs, labels)
    coherence = _boundary_coherence(segments, period, evidence_grid, evidence_values)
    return {
        'labels': np.asarray(labels, dtype=np.int16),
        'probs': probs,
        'segments': segments,
        'pointwise_loglik': float(point_ll),
        'coherence': float(coherence),
        'seed_info': seed_info,
    }

def _fit_from_initial_labels(
    x,
    labels0,
    k,
    period,
    by_stream,
    dt,
    iterations,
    seed_info,
    evidence_grid,
    evidence_values,
):
    probs = fit_bernoulli_templates(x, labels0, k)
    targets = seed_info.get('durations_s') if isinstance(seed_info, dict) else None
    if not targets:
        targets = [float(period) / float(k)] * k
    initial_phase = int(labels0[0]) if len(labels0) else 0
    history = []
    best_refined = None
    for _ in range(max(1, int(iterations))):
        labels, score, segments, decoder_info = decode_cyclic_hsmm(
            x,
            probs,
            period,
            k,
            dt=dt,
            transition_penalty=0.25,
            duration_targets=targets,
            initial_phase=initial_phase,
        )
        new_probs = fit_bernoulli_templates(x, labels, k)
        coherence = _boundary_coherence(
            segments,
            period,
            evidence_grid,
            evidence_values,
        )
        point_ll = _pointwise_loglik(x, new_probs, labels)
        payload = {
            'labels': labels,
            'probs': new_probs,
            'score': float(score),
            'segments': segments,
            'decoder_info': decoder_info,
            'pointwise_loglik': float(point_ll),
            'coherence': float(coherence),
        }
        if best_refined is None or payload['score'] > best_refined['score']:
            best_refined = payload
        history.append(
            {
                'loglik_with_duration_penalty': float(score),
                'pointwise_loglik': float(point_ll),
                'boundary_coherence': float(coherence),
            }
        )
        if np.max(np.abs(new_probs - probs)) < 0.001:
            probs = new_probs
            break
        probs = new_probs
    if best_refined is None:
        raise RuntimeError('could not refine HSMM fit')
    return best_refined, history

def _fit_quality(fit, x_shape, evidence_weight: float=0.05):
    n, s = x_shape
    norm_ll = float(
        fit.get('pointwise_loglik', fit.get('score', 0.0))
    ) / max(1, n * s)
    return norm_ll + evidence_weight * float(fit.get('coherence', 0.0))

def em_fit(
    x: np.ndarray,
    period: float,
    k: int,
    by_stream_global: Optional[Dict[str, List[float]]] = None,
    entry_streams: Optional[Dict[str, List[float]]] = None,
    dt: float = 1.0,
    iterations: int = 3,
):
    seed_candidates = []
    evidence_grid = evidence_values = None
    if by_stream_global is not None:
        evidence_grid, evidence_values = _periodic_boundary_evidence(
            by_stream_global,
            period,
        )

    release_seed = None
    entry_seed = None
    if by_stream_global is not None:
        release_seed = initial_seed_from_streams(
            by_stream_global,
            period,
            k,
            len(x),
            dt,
        )
        if release_seed is not None:
            seed_candidates.append(
                ('robust_release_seed', release_seed[0], release_seed[1])
            )
    if entry_streams is not None:
        entry_seed = initial_seed_from_streams(
            entry_streams,
            period,
            k,
            len(x),
            dt,
        )
        if entry_seed is not None:
            seed_candidates.append(
                ('entry_seed', entry_seed[0], entry_seed[1])
            )

    if release_seed is not None and entry_seed is not None:
        ri = release_seed[1].get('group_onsets_s', [])
        ei = entry_seed[1].get('group_onsets_s', [])
        if len(ri) == k and len(ei) == k:
            fused_onsets = sorted(
                [
                    float((float(a) + float(b)) * 0.5) % float(period)
                    for a, b in zip(ri, ei)
                ]
            )
            gaps = []
            for i, a in enumerate(fused_onsets):
                b = fused_onsets[(i + 1) % k]
                if i == k - 1:
                    b += period
                gaps.append(float(b - a))
            if min(gaps) >= max(3.0, 0.03 * period):
                tt = np.arange(len(x), dtype=float) * dt
                fused_labels = np.zeros(
                    len(x),
                    dtype=np.int16,
                )
                for i, a in enumerate(fused_onsets):
                    b = fused_onsets[(i + 1) % k]
                    if i == k - 1:
                        b += period
                    fused_labels[(tt - a) % period < (b - a)] = i
                fused_info = {
                    'method': 'release_entry_seed_ensemble',
                    'group_onsets_s': fused_onsets,
                    'durations_s': gaps,
                    'source_views': [
                        'robust_release_events',
                        'input_zone_entry_events',
                    ],
                    'release_onsets_s': [float(v) for v in ri],
                    'entry_onsets_s': [float(v) for v in ei],
                }
                seed_candidates.append(
                    (
                        'release_entry_seed_ensemble',
                        fused_labels,
                        fused_info,
                    )
                )

    try:
        offset = initial_offset_search(
            x,
            period,
            k,
            dt=dt,
        )
        equal_labels = phase_labels_for_time(
            len(x),
            dt,
            period,
            k,
            offset,
        )
        seed_candidates.append(
            (
                'equal_duration_offset_search',
                equal_labels,
                {
                    'method': 'equal_duration_offset_search',
                    'offset_s': float(offset),
                    'durations_s': [
                        float(period) / float(k)
                    ] * k,
                },
            )
        )
    except Exception:
        pass

    unique = []
    seen = set()
    for source, labels, info in seed_candidates:
        sig = tuple(
            int(z)
            for z in labels[
                :min(len(labels), int(round(period / dt)) + 2)
            ]
        )
        if sig in seen and source != 'release_entry_seed_ensemble':
            continue
        seen.add(sig)
        unique.append((source, labels, info))

    fitted = []
    for source, labels0, seed_info in unique:
        seed_fit = _seed_labels_to_fit(
            labels0,
            x,
            k,
            period,
            by_stream_global,
            dt,
            {**seed_info, 'source': source},
            evidence_grid,
            evidence_values,
        )
        seed_fit['source'] = source
        seed_quality = _fit_quality(seed_fit, x.shape)
        try:
            refined, history = _fit_from_initial_labels(
                x,
                labels0,
                k,
                period,
                by_stream_global,
                dt,
                iterations,
                {**seed_info, 'source': source},
                evidence_grid,
                evidence_values,
            )
            refined['source'] = source + '+hsmm'
            refined['history'] = history
            refined_quality = _fit_quality(
                refined,
                x.shape,
            )
        except Exception:
            refined = None
            refined_quality = -float('inf')

        best = seed_fit
        if refined is not None and refined_quality > seed_quality + 0.0001:
            best = refined
        best['model_quality'] = float(
            _fit_quality(best, x.shape)
        )
        fitted.append(best)

    if not fitted:
        raise RuntimeError('could not initialize V9')

    ensemble = [
        f
        for f in fitted
        if f.get('source') == 'release_entry_seed_ensemble'
    ]
    if ensemble:
        best = max(
            ensemble,
            key=lambda f: f['model_quality'],
        )
        for f in fitted:
            if f.get('source') in {
                'release_entry_seed_ensemble',
                'robust_release_seed',
                'entry_seed',
            }:
                continue
            if (
                f.get('model_quality', -float('inf'))
                > best.get('model_quality', -float('inf')) + 0.002
            ):
                best = f
    else:
        best = max(
            fitted,
            key=lambda f: f['model_quality'],
        )

    return {
        'k': int(k),
        'initialization': best.get(
            'seed_info',
            {'method': best.get('source')},
        ),
        'initialization_candidates': [
            {
                'source': f.get('source'),
                'model_quality': float(
                    f.get('model_quality', -float('inf'))
                ),
                'pointwise_loglik': float(
                    f.get('pointwise_loglik', 0.0)
                ),
                'boundary_coherence': float(
                    f.get('coherence', 0.0)
                ),
            }
            for f in fitted
        ],
        'labels': best['labels'],
        'probs': best['probs'],
        'score': float(
            best.get(
                'score',
                best.get('pointwise_loglik', 0.0),
            )
        ),
        'pointwise_loglik': float(
            best.get('pointwise_loglik', 0.0)
        ),
        'boundary_coherence': float(
            best.get('coherence', 0.0)
        ),
        'segments': best['segments'],
        'decoder_info': best.get(
            'decoder_info',
            {
                'min_duration_s': best.get(
                    'seed_info', {}
                ).get('durations_s'),
                'max_duration_s': best.get(
                    'seed_info', {}
                ).get('durations_s'),
                'transition_penalty': 0.25,
            },
        ),
        'history': best.get('history', []),
        'model_quality': float(
            best.get('model_quality', 0.0)
        ),
    }

def candidate_metrics(fit, x_shape):
    n, s = x_shape
    p_count = fit['k'] * s
    effective_obs = max(2, n * s)
    bic = (
        -2.0 * float(fit['score'])
        + p_count * math.log(effective_obs)
    )
    seg_lengths = [
        b - a
        for a, b, _ in fit['segments']
    ]
    return {
        'k': int(fit['k']),
        'objective': float(fit['score']),
        'approx_bic': float(bic),
        'parameter_count': int(p_count),
        'segment_count': int(len(seg_lengths)),
        'median_segment_duration_s': (
            float(np.median(seg_lengths))
            if seg_lengths else 0.0
        ),
        'mean_segment_duration_s': (
            float(np.mean(seg_lengths))
            if seg_lengths else 0.0
        ),
    }

def discover_phase_count(
    x,
    by_stream_global,
    period,
    kmin=2,
    kmax=6,
    dt=1.0,
    # BIC already penalizes extra phase templates. Keep the recurrent boundary
    # penalty modest so sparse/uneven multi-phase patterns are not collapsed into k=2.
    extra_phase_penalty_per_cycle: float=5.0,
    recording_end_s: Optional[float]=None,
    entry_streams=None,
    topology_streams=None,
):
    upper = min(
        int(kmax),
        max(2, x.shape[1] + 1),
    )
    topology_source = topology_streams if topology_streams is not None else by_stream_global
    canonical = {
        str(name).upper().replace("_", "")
        for name in topology_source
    }
    has_ns_axis = {"N->S", "S->N"} <= canonical
    has_ew_axis = {"E->W", "W->E"} <= canonical
    topology_cap_applied = bool(has_ns_axis and has_ew_axis)
    if topology_cap_applied:
        upper = min(upper, 3)
    candidates = []
    fits = {}
    for k in range(int(kmin), upper + 1):
        fit = em_fit(
            x,
            period,
            k,
            by_stream_global=by_stream_global,
            entry_streams=entry_streams,
            dt=dt,
            iterations=2,
        )
        fits[k] = fit
        candidates.append(
            candidate_metrics(
                fit,
                x.shape,
            )
        )

    cycle_count = max(
        1.0,
        float(
            recording_end_s
            or len(x) * dt
        ) / max(float(period), 1e-06),
    )
    for candidate in candidates:
        candidate['recurrent_complexity_penalty'] = float(
            extra_phase_penalty_per_cycle
            * max(
                0,
                candidate['k'] - 2,
            )
            * cycle_count
        )
        candidate['selection_score'] = float(
            candidate['approx_bic']
            + candidate['recurrent_complexity_penalty']
        )

    selected = min(
        candidates,
        key=lambda candidate: candidate['selection_score'],
    )
    for candidate in candidates:
        candidate["topology_cap_applied"] = topology_cap_applied
        if topology_cap_applied and candidate["k"] > 3:
            candidate["selection_score"] = float("inf")
    return (
        int(selected['k']),
        candidates,
        fits,
    )

def anonymous_phase_name(i: int) -> str:
    x = i + 1
    out = ''
    while x:
        x, r = divmod(x - 1, 26)
        out = chr(65 + r) + out
    return f'PHASE_{out}'

def phase_activity_summary(names, probs):
    return [
        {
            'stream': stream,
            'event_probability_by_phase': {
                anonymous_phase_name(z): float(probs[z, j])
                for z in range(probs.shape[0])
            },
        }
        for j, stream in enumerate(names)
    ]
