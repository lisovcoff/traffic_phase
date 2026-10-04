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
            duration_min_factor=0.25 if k == 3 else 0.65,
            duration_max_factor=1.75 if k == 3 else 1.35,
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
    if k == 3:
        try:
            split_offset = initial_offset_search(
                x,
                period,
                2,
                dt=dt,
            )
            labels2 = phase_labels_for_time(
                len(x),
                dt,
                period,
                2,
                split_offset,
            )
            time_axis = np.arange(len(x), dtype=float) * dt
            for parent_phase in range(2):
                labels3 = np.where(
                    labels2 == parent_phase,
                    parent_phase,
                    2 if parent_phase == 0 else 0,
                ).astype(np.int16)
                positions = np.flatnonzero(labels2 == parent_phase)
                if not positions.size:
                    continue
                start = int(positions[0])
                previous = start
                runs = []
                for position in positions[1:]:
                    position = int(position)
                    if position != previous + 1:
                        runs.append((start, previous + 1))
                        start = position
                    previous = position
                runs.append((start, previous + 1))
                for left, right in runs:
                    midpoint = left + max(
                        1,
                        (right - left) // 2,
                    )
                    labels3[midpoint:right] = (
                        1 if parent_phase == 0 else 2
                    )
                counts = np.bincount(
                    labels3,
                    minlength=3,
                ).astype(float)
                if np.any(counts <= 0):
                    continue
                durations = (
                    counts / max(1.0, float(len(labels3)))
                ) * float(period)
                seed_candidates.append(
                    (
                        "two_phase_internal_split_seed",
                        labels3,
                        {
                            "method": "two_phase_internal_split_seed",
                            "split_parent_phase": int(parent_phase),
                            "offset_s": float(split_offset),
                            "durations_s": [
                                float(value)
                                for value in durations
                            ],
                        },
                    )
                )
        except Exception:
            pass

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

def _phase_support_metrics(
    fit,
    *,
    activity_threshold: float = 0.08,
    selectivity_ratio: float = 1.15,
):
    """Measure whether each fitted phase has distinct transport evidence."""
    probs = np.asarray(fit.get("probs"), dtype=float)
    if probs.ndim != 2:
        return {
            "supported_phase_count": 0,
            "unsupported_phase_count": int(fit.get("k", 0)),
            "phase_support_by_phase": {},
            "phase_contrast_by_phase": {},
        }
    k = int(probs.shape[0])
    support_by_phase = {}
    contrast_by_phase = {}
    for phase in range(k):
        current = probs[phase]
        others = np.delete(probs, phase, axis=0) if k > 1 else np.zeros((1, len(current)))
        strongest_other = np.max(others, axis=0)
        contrast = np.maximum(current - np.mean(others, axis=0), 0.0)
        supported = (
            (current >= float(activity_threshold))
            & (current >= float(selectivity_ratio) * np.maximum(strongest_other, 0.001))
        )
        support_by_phase[str(phase)] = int(np.sum(supported))
        contrast_by_phase[str(phase)] = float(np.max(contrast) if contrast.size else 0.0)
    supported_phase_count = sum(value > 0 for value in support_by_phase.values())
    return {
        "supported_phase_count": int(supported_phase_count),
        "unsupported_phase_count": int(k - supported_phase_count),
        "phase_support_by_phase": support_by_phase,
        "phase_contrast_by_phase": contrast_by_phase,
    }

def _phase_boundary_stats(fit, x: np.ndarray, period: float, dt: float):
    labels = np.asarray(fit.get("labels"), dtype=np.int16)
    segments = fit.get("segments", [])
    if labels.size == 0 or not segments or period <= 0.0:
        return {}
    window = max(1, min(5, int(round(0.04 * float(period) / max(dt, 1e-12)))))
    stats = {}
    for index in range(len(segments) - 1):
        left, right = segments[index], segments[index + 1]
        a, b = int(left[2]), int(right[2])
        if a == b:
            continue
        boundary = int(round(float(right[0]) / max(dt, 1e-12)))
        lo, hi = max(0, boundary - window), min(len(x), boundary + window)
        split = min(window, boundary - lo, hi - boundary)
        if split <= 0:
            continue
        before = np.mean(x[boundary - split:boundary], axis=0)
        after = np.mean(x[boundary:boundary + split], axis=0)
        delta = after - before
        magnitude = float(np.sum(np.abs(delta)))
        scale = float(np.sum(before + after)) + 1e-9
        change_strength = magnitude / scale
        positive = float(np.sum(np.maximum(delta, 0.0)))
        negative = float(np.sum(np.maximum(-delta, 0.0)))
        exchange = min(positive, negative) / max(positive + negative, 1e-9)
        key = tuple(sorted((a, b)))
        bucket = stats.setdefault(key, {"change_strength": [], "exchange_ratio": []})
        bucket["change_strength"].append(change_strength)
        bucket["exchange_ratio"].append(exchange)
    return {
        key: {
            "change_strength": float(np.median(value["change_strength"])),
            "exchange_ratio": float(np.median(value["exchange_ratio"])),
            "observations": int(len(value["change_strength"])),
        }
        for key, value in stats.items()
    }

def _duration_balance_by_pair(fit, period: float):
    durations = defaultdict(list)
    for a, b, z in fit.get("segments", []):
        durations[int(z)].append(float(b) - float(a))
    medians = {z: float(np.median(values)) for z, values in durations.items() if values}
    return {
        (a, b): (
            float(min(medians[a], medians[b]) / max(medians[a], medians[b]))
            if a in medians and b in medians and max(medians[a], medians[b]) > 1e-9
            else 0.0
        )
        for a, b in itertools.combinations(range(3), 2)
    }

def _rank_correlation(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size < 2 or b.size != a.size or np.std(a) <= 1e-12 or np.std(b) <= 1e-12:
        return 0.0
    return float(np.corrcoef(np.argsort(np.argsort(a)), np.argsort(np.argsort(b)))[0, 1])

def _cosine_vector(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator > 1e-12 else 0.0

def _merge_loss_per_cycle(x, labels3, a, b, cycles):
    merged_labels = np.where((labels3 == a) | (labels3 == b), 0, 1).astype(np.int16)
    merged_probs = fit_bernoulli_templates(x, merged_labels, 2)
    probs3 = fit_bernoulli_templates(x, labels3, 3)
    ll3 = _pointwise_loglik(x, probs3, labels3)
    ll2 = _pointwise_loglik(x, merged_probs, merged_labels)
    return max(0.0, ll3 - ll2) / max(float(cycles), 1.0)

def _topology_redundancy_pair(probs, a, b, third):
    pa, pb, pc = [np.asarray(probs[z], dtype=float) for z in (a, b, third)]
    active = 0.08
    # Test both orderings: a low-intensity tail of b is redundant just as b can be
    # a tail of a. A true protected turn must introduce at least one stable active stream.
    def relation(parent, child):
        unique_child = int(np.sum((child >= active) & (child > parent + 0.04)))
        parent_dominates = bool(np.all(child <= parent + 0.02) and unique_child == 0)
        return parent_dominates, unique_child

    a_contains_b, b_unique = relation(pa, pb)
    b_contains_a, a_unique = relation(pb, pa)
    subset = bool(a_contains_b or b_contains_a)
    pair_cosine = _cosine_vector(pa, pb)
    third_cosine = max(_cosine_vector(pa, pc), _cosine_vector(pb, pc))
    return {
        "subset_relationship": (
            "a_contains_b" if a_contains_b
            else "b_contains_a" if b_contains_a
            else "none"
        ),
        "directional_exclusivity": float(1.0 if subset else 0.0),
        "new_active_streams": int(0 if subset else min(a_unique, b_unique)),
        "pair_cosine": float(pair_cosine),
        "pair_contrast_to_third": float(pair_cosine - third_cosine),
        "third_phase_max_cosine": float(third_cosine),
        "reference_active_streams": int(np.sum(np.maximum(pa, pb) >= active)),
        "candidate_active_streams": int(np.sum(np.minimum(pa, pb) >= active)),
    }

def evaluate_phase_redundancy(
    fit3,
    fit2,
    x: np.ndarray,
    period: float,
    by_stream_global=None,
    *,
    cycles: float | None = None,
    dt: float = 1.0,
):
    """Detect k=3 overfit using directional subset, contrast gap and boundary coherence."""
    probs = np.asarray(fit3.get("probs"), dtype=float)
    labels3 = np.asarray(fit3.get("labels"), dtype=np.int16)
    if probs.shape != (3, x.shape[1]) or labels3.shape != (x.shape[0],):
        return {
            "detected": False,
            "method": "invalid_redundancy_inputs",
            "candidate_pair": None,
            "pairs": [],
        }

    support = _phase_support_metrics(fit3)
    boundary_stats = _phase_boundary_stats(fit3, x, float(period), float(dt))
    cycle_count = (
        float(cycles) if cycles is not None
        else max(1.0, len(x) * dt / max(float(period), 1e-9))
    )
    rows = []

    for a, b in itertools.combinations(range(3), 2):
        third = 3 - a - b
        topo = _topology_redundancy_pair(probs, a, b, third)
        key = tuple(sorted((a, b)))
        boundary = boundary_stats.get(
            key,
            {"change_strength": 0.0, "exchange_ratio": 1.0, "observations": 0},
        )
        cross_strengths = [
            boundary_stats.get(tuple(sorted((a, third))), {}).get("change_strength"),
            boundary_stats.get(tuple(sorted((b, third))), {}).get("change_strength"),
        ]
        cross_strengths = [float(v) for v in cross_strengths if v is not None]
        boundary_ratio = (
            float(boundary["change_strength"] / max(np.median(cross_strengths), 1e-6))
            if cross_strengths else 1.0
        )
        merge_loss = _merge_loss_per_cycle(x, labels3, a, b, cycle_count)
        cross_losses = [
            _merge_loss_per_cycle(x, labels3, a, third, cycle_count),
            _merge_loss_per_cycle(x, labels3, b, third, cycle_count),
        ]
        contrast_gap = float(merge_loss / max(min(cross_losses), 1e-6))
        supported_a = support["phase_support_by_phase"].get(str(a), 0)
        supported_b = support["phase_support_by_phase"].get(str(b), 0)
        # A single unsupported phase is allowed: it is a sparse protected turn.
        # It becomes redundant only when the subset relation also holds.
        unsupported_pair = bool(supported_a == 0 or supported_b == 0)
        boundary_coherent = bool(
            boundary["observations"] > 0
            and boundary_ratio <= 0.70
            and float(boundary["exchange_ratio"]) <= 0.35
        )
        selected = bool(
            topo["directional_exclusivity"] >= 1.0
            and contrast_gap < 0.20
            and boundary_coherent
        )
        rows.append({
            **topo,
            "pair": [int(a), int(b)],
            "third_phase": int(third),
            "merge_loss_per_cycle": float(merge_loss),
            "cross_merge_losses_per_cycle": [float(v) for v in cross_losses],
            "contrast_gap_ratio": float(contrast_gap),
            "boundary_change_strength": float(boundary["change_strength"]),
            "boundary_exchange_ratio": float(boundary["exchange_ratio"]),
            "boundary_strength_ratio": float(min(2.0, max(0.0, boundary_ratio))),
            "boundary_observations": int(boundary["observations"]),
            "pair_has_unsupported_phase": unsupported_pair,
            "boundary_coherent": boundary_coherent,
            "selected_by_v5_rule": selected,
        })

    selected_rows = [row for row in rows if row["selected_by_v5_rule"]]
    candidate = selected_rows[0] if selected_rows else max(
        rows,
        key=lambda row: (row["directional_exclusivity"], -row["contrast_gap_ratio"]),
    )
    return {
        "detected": bool(selected_rows),
        "method": "topological_temporal_redundancy_v5",
        "candidate_pair": candidate["pair"],
        "supported_phase_count": int(support["supported_phase_count"]),
        "unsupported_phase_count": int(support["unsupported_phase_count"]),
        "phase_support_by_phase": support["phase_support_by_phase"],
        "pairs": rows,
    }

def candidate_metrics(fit, x_shape):
    n, s = x_shape
    p_count = fit['k'] * s
    effective_obs = max(2, n * s)
    bic = (
        -2.0 * float(fit['score'])
        + p_count * math.log(effective_obs)
    )
    seg_lengths = [b - a for a, b, _ in fit['segments']]
    return {
        'k': int(fit['k']),
        'objective': float(fit['score']),
        'approx_bic': float(bic),
        'parameter_count': int(p_count),
        'segment_count': int(len(seg_lengths)),
        'median_segment_duration_s': float(np.median(seg_lengths)) if seg_lengths else 0.0,
        'mean_segment_duration_s': float(np.mean(seg_lengths)) if seg_lengths else 0.0,
        **_phase_support_metrics(fit),
    }

def discover_phase_count(
    x,
    by_stream_global,
    period,
    kmin=2,
    kmax=6,
    dt=1.0,
    extra_phase_penalty_per_cycle: float=5.0,
    recording_end_s: Optional[float]=None,
    entry_streams=None,
    topology_streams=None,
):
    upper = min(int(kmax), max(2, x.shape[1] + 1))
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
        candidates.append(candidate_metrics(fit, x.shape))

    cycle_count = max(
        1.0,
        float(recording_end_s or len(x) * dt) / max(float(period), 1e-6),
    )
    for candidate in candidates:
        candidate['recurrent_complexity_penalty'] = float(
            extra_phase_penalty_per_cycle
            * max(0, candidate['k'] - 2)
            * cycle_count
        )
        candidate['selection_score'] = float(
            candidate['approx_bic'] + candidate['recurrent_complexity_penalty']
        )

    for candidate in candidates:
        candidate["topology_cap_applied"] = topology_cap_applied
        # One unsupported phase is valid for a sparse protected turn. A model
        # is degenerate only when every fitted phase is unsupported.
        candidate["degenerate_phase_model"] = (
            candidate.get("unsupported_phase_count", 0) >= candidate["k"]
            and candidate["k"] > 2
        )
        candidate["phase_support_penalty"] = (
            float("inf") if candidate["degenerate_phase_model"] else 0.0
        )
        if topology_cap_applied and candidate["k"] > 3:
            candidate["selection_score"] = float("inf")
        elif candidate["degenerate_phase_model"]:
            candidate["selection_score"] = float("inf")

    selected = min(candidates, key=lambda candidate: candidate['selection_score'])
    return int(selected['k']), candidates, fits

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
