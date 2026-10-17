from __future__ import annotations
import math
import time
from dataclasses import dataclass
import json
import itertools
from collections import defaultdict
from pathlib import Path
from numbers import Real
from typing import Dict, List, Optional, Sequence
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.stats import rankdata
from scipy.optimize import linear_sum_assignment

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
        'data_loglik': float(point_ll),
        'pointwise_loglik': float(point_ll),
        'penalized_objective': None,
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
        # The decoder evaluated this path with the *input* templates. Keep its
        # duration/transition cost, but rescore the returned, refitted templates.
        # This requires no second decode and preserves existing censoring rules.
        input_point_ll = _pointwise_loglik(x, probs, labels)
        returned_objective = float(score) + point_ll - input_point_ll
        payload = {
            'labels': labels,
            'probs': new_probs,
            'score': float(returned_objective),
            'score_semantics': 'returned_model_penalized_objective',
            'penalized_objective': float(returned_objective),
            'decoder_input_objective': float(score),
            'decoder_input_data_loglik': float(input_point_ll),
            'segments': segments,
            'decoder_info': decoder_info,
            'pointwise_loglik': float(point_ll),
            'data_loglik': float(point_ll),
            'coherence': float(coherence),
            'seed_info': seed_info,
        }
        if best_refined is None or payload['score'] > best_refined['score']:
            best_refined = payload
        history.append(
            {
                'loglik_with_duration_penalty': float(returned_objective),
                'decoder_input_objective': float(score),
                'decoder_input_data_loglik': float(input_point_ll),
                'data_loglik': float(point_ll),
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


def _fuse_seed_views(release_info, entry_info, period):
    """Match observed stream groups before averaging their cyclic onsets.

    Unique maximum shared-membership assignment is required. Times do not break
    identity ties; ambiguous identity/order/antipodes omit this optional seed.
    """
    diagnostic = {'status': 'unavailable', 'method': 'unique_membership_circular_midpoint'}
    def unavailable(reason):
        return None, {**diagnostic, 'reason': reason}
    ri, ei = release_info.get('group_onsets_s', []), entry_info.get('group_onsets_s', [])
    rg, eg = release_info.get('group_streams'), entry_info.get('group_streams')
    if not all(isinstance(v, (list, tuple)) for v in (ri, ei, rg, eg)):
        return unavailable('MISSING_GROUP_MEMBERSHIP')
    k = len(ri)
    if not rg or not eg or not k or len(ei) != k or len(rg) != k or len(eg) != k:
        return unavailable('MISSING_GROUP_MEMBERSHIP')
    if isinstance(period, bool) or not isinstance(period, Real) or not math.isfinite(period) or period <= 0:
        return unavailable('INVALID_PERIOD')
    if any(isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(v) or not 0 <= v < period for v in [*ri, *ei]):
        return unavailable('INVALID_GROUP_ONSETS')
    if any(b <= a for values in (ri, ei) for a, b in zip(values, values[1:])):
        return unavailable('UNSORTED_OR_DUPLICATE_GROUP_ONSETS')
    if any(not isinstance(group, (list, tuple)) or not group or
           not all(isinstance(s, str) and s for s in group) for group in [*rg, *eg]):
        return unavailable('INVALID_GROUP_MEMBERSHIP')
    weights = np.array([[len(set(a) & set(b)) for b in eg] for a in rg], dtype=int)
    rows, cols = linear_sum_assignment(-weights)
    optimum = int(weights[rows, cols].sum())
    if np.any(weights[rows, cols] == 0):
        return unavailable('NO_SHARED_MOVEMENT_FOR_MATCH')
    # If ANY edge of the optimum can be replaced at equal score, identity is
    # ambiguous. K additional polynomial assignments, not K! enumeration.
    for row, col in zip(rows, cols):
        alternative = weights.copy()
        alternative[row, col] = -int(weights.sum())-1
        ar, ac = linear_sum_assignment(-alternative)
        if int(alternative[ar, ac].sum()) == optimum:
            return unavailable('AMBIGUOUS_GROUP_ASSIGNMENT')
    if k > 1 and any((int(cols[(i+1) % k])-int(cols[i])) % k != 1 for i in range(k)):
        return unavailable('CYCLIC_ORDER_DISAGREEMENT')
    pairs = []
    numerical_tol = 8*np.finfo(float).eps*max(1., period)
    for row, col in zip(rows, cols):
        a, b = float(ri[row]), float(ei[col])
        delta = (b-a+period/2) % period-period/2
        if abs(abs(delta)-period/2) <= numerical_tol:
            return unavailable('ANTIPODAL_ONSETS')
        pairs.append({'onset_s': float((a+delta/2) % period),
            'release_group_index': int(row), 'entry_group_index': int(col),
            'release_onset_s': a, 'entry_onset_s': b,
            'shared_streams': sorted(set(rg[row]) & set(eg[col])),
            'group_streams': sorted(set(rg[row]) | set(eg[col]))})
    pairs.sort(key=lambda p: p['onset_s'])
    onsets = [p['onset_s'] for p in pairs]
    gaps = [(onsets[(i+1) % k]-a) % period for i, a in enumerate(onsets)] if k > 1 else [period]
    if min(gaps) < max(3., .03*period):
        return unavailable('INSUFFICIENT_ONSET_SPACING')
    info = {'method': 'release_entry_seed_ensemble', 'group_onsets_s': onsets,
        'durations_s': gaps, 'group_streams': [p['group_streams'] for p in pairs],
        'source_views': ['robust_release_events', 'input_zone_entry_events'],
        'release_onsets_s': [float(v) for v in ri], 'entry_onsets_s': [float(v) for v in ei],
        'group_matching': pairs, 'fusion_semantics': 'initialization_heuristic_NOT_signal_switch'}
    return info, {**diagnostic, 'status': 'available', 'reason': None, 'matches': pairs}

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

    ensemble_diagnostic = {'status': 'unavailable', 'reason': 'MISSING_SEED_VIEW'}
    if release_seed is not None and entry_seed is not None:
        fused_info, ensemble_diagnostic = _fuse_seed_views(release_seed[1], entry_seed[1], period)
        if fused_info is not None:
            tt = np.arange(len(x), dtype=float)*dt
            fused_labels = np.zeros(len(x), dtype=np.int16)
            for phase, (onset, duration) in enumerate(zip(fused_info['group_onsets_s'], fused_info['durations_s'])):
                fused_labels[(tt-onset) % period < duration] = phase
            seed_candidates.append(('release_entry_seed_ensemble', fused_labels, fused_info))

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

    # Finalize the candidate list before deduplication: internal split seeds
    # must reach the same fitting loop as the original seed views.
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

    # Same declared quality for every source. max keeps the first retained
    # candidate on exact ties; an ensemble cannot suppress a better pure view.
    best = max(fitted, key=lambda f: f['model_quality'])

    return {
        'k': int(k),
        'initialization': best.get(
            'seed_info',
            {'method': best.get('source')},
        ),
        'initialization_diagnostics': {
            'ensemble': ensemble_diagnostic,
            'selection_rule': 'max_model_quality_all_sources_first_retained_on_exact_tie',
        },
        'initialization_candidates': [
            {
                'source': f.get('source'),
                'selected': f is best,
                'model_quality': float(
                    f.get('model_quality', -float('inf'))
                ),
                'pointwise_loglik': float(
                    f.get('pointwise_loglik', 0.0)
                ),
                'data_loglik': float(f['pointwise_loglik']),
                'penalized_objective': f.get('penalized_objective'),
                'boundary_coherence': float(
                    f.get('coherence', 0.0)
                ),
            }
            for f in fitted
        ],
        'labels': best['labels'],
        'probs': best['probs'],
        # Public score is now a uniform compatibility alias. Decoder penalties
        # are diagnostics, never a source-dependent K-selection likelihood.
        'score': float(best['pointwise_loglik']),
        'score_semantics': 'data_loglik',
        'data_loglik': float(best['pointwise_loglik']),
        'penalized_objective': best.get('penalized_objective'),
        'decoder_input_objective': best.get('decoder_input_objective'),
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
    """Heuristic JOINT fitted-signature separability, not lamp observability.

    Shared streams are allowed: a different coordinate may distinguish each
    competitor. Symmetric contrast is conditional on the occupancy model;
    an inactive coordinate is not a physical RED/demand observation.
    """
    probs = np.asarray(fit.get("probs"), dtype=float)
    if probs.ndim != 2 or not np.all(np.isfinite(probs)) or np.any((probs < 0) | (probs > 1)):
        return {
            "supported_phase_count": 0,
            "unsupported_phase_count": int(fit.get("k", 0)),
            "phase_support_by_phase": {},
            "phase_contrast_by_phase": {},
            "phase_support_semantics": "INVALID_FITTED_SIGNATURES",
        }
    k = int(probs.shape[0])
    support_by_phase, contrast_by_phase, exclusive_by_phase, witnesses = {}, {}, {}, {}
    for phase in range(k):
        current = probs[phase]
        others = np.delete(probs, phase, axis=0)
        strongest_other = np.max(others, axis=0) if len(others) else np.zeros_like(current)
        contrast = np.maximum(current-np.mean(others, axis=0), 0.) if len(others) else np.zeros_like(current)
        exclusive = (current >= activity_threshold) & (current >= selectivity_ratio*np.maximum(strongest_other,.001))
        exclusive_by_phase[str(phase)] = int(np.sum(exclusive))
        active = bool(np.any(current >= activity_threshold))
        pairwise = {}
        for other in range(k):
            if other == phase:
                continue
            competitor = probs[other]
            distinguishing = ((current >= activity_threshold) & (current >= selectivity_ratio*np.maximum(competitor,.001))) | (
                (competitor >= activity_threshold) & (competitor >= selectivity_ratio*np.maximum(current,.001)))
            pairwise[str(other)] = [int(i) for i in np.flatnonzero(distinguishing)]
        separated = active and all(pairwise.values())
        coordinates = set(i for values in pairwise.values() for i in values)
        support_by_phase[str(phase)] = (len(coordinates) if k > 1 else int(np.sum(current >= activity_threshold))) if separated else 0
        contrast_by_phase[str(phase)] = float(np.max(contrast)) if contrast.size else 0.
        witnesses[str(phase)] = pairwise
    supported_phase_count = sum(v > 0 for v in support_by_phase.values())
    return {
        "supported_phase_count": int(supported_phase_count),
        "unsupported_phase_count": int(k-supported_phase_count),
        "phase_support_by_phase": support_by_phase,
        "phase_contrast_by_phase": contrast_by_phase,
        "exclusive_stream_support_by_phase": exclusive_by_phase,
        "pairwise_signature_witness_columns": witnesses,
        "phase_support_semantics": "heuristic_joint_fitted_signature_NOT_external_identifiability",
    }



def _phase_boundary_stats(
    fit,
    x: np.ndarray,
    period: float,
    dt: float,
):
    labels = np.asarray(fit.get("labels"), dtype=np.int16)
    segments = fit.get("segments", [])
    if labels.size == 0 or not segments or period <= 0.0:
        return {}

    window = max(
        1,
        min(
            5,
            int(round(0.04 * float(period) / max(dt, 1e-12))),
        ),
    )
    stats = {}
    for index in range(len(segments) - 1):
        left = segments[index]
        right = segments[index + 1]
        a = int(left[2])
        b = int(right[2])
        if a == b:
            continue
        boundary = int(round(float(right[0]) / max(dt, 1e-12)))
        lo = max(0, boundary - window)
        hi = min(len(x), boundary + window)
        split = min(window, boundary - lo, hi - boundary)
        if split <= 0:
            continue
        before = np.mean(
            x[boundary - split:boundary],
            axis=0,
        )
        after = np.mean(
            x[boundary:boundary + split],
            axis=0,
        )
        delta = after - before
        magnitude = float(np.sum(np.abs(delta)))
        scale = float(np.sum(before + after)) + 1e-9
        change_strength = magnitude / scale
        positive = float(np.sum(np.maximum(delta, 0.0)))
        negative = float(np.sum(np.maximum(-delta, 0.0)))
        exchange = (
            min(positive, negative)
            / max(positive + negative, 1e-9)
        )
        key = tuple(sorted((a, b)))
        bucket = stats.setdefault(
            key,
            {
                "change_strength": [],
                "exchange_ratio": [],
            },
        )
        bucket["change_strength"].append(
            float(change_strength)
        )
        bucket["exchange_ratio"].append(
            float(exchange)
        )

    out = {}
    for key, value in stats.items():
        out[key] = {
            "change_strength": float(
                np.median(value["change_strength"])
            ),
            "exchange_ratio": float(
                np.median(value["exchange_ratio"])
            ),
            "observations": int(
                len(value["change_strength"])
            ),
        }
    return out


def _duration_balance_by_pair(
    fit,
    period: float,
):
    durations = defaultdict(list)
    for a, b, z in fit.get("segments", []):
        durations[int(z)].append(float(b) - float(a))
    medians = {
        z: float(np.median(values))
        for z, values in durations.items()
        if values
    }
    pairs = {}
    for a, b in itertools.combinations(range(3), 2):
        if a not in medians or b not in medians:
            pairs[(a, b)] = 0.0
            continue
        lo = min(medians[a], medians[b])
        hi = max(medians[a], medians[b])
        pairs[(a, b)] = (
            float(lo / hi)
            if hi > 1e-9
            else 0.0
        )
    return pairs



def _rank_correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Spearman correlation with average ranks for exact ties.

    Equal occupancies must not acquire different ranks from movement column
    order. The existing zero convention for short/constant vectors is retained.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size < 2 or b.size != a.size:
        return 0.0
    if np.std(a) <= 1e-12 or np.std(b) <= 1e-12:
        return 0.0
    ra = rankdata(a, method='average')
    rb = rankdata(b, method='average')
    return float(np.corrcoef(ra, rb)[0, 1])


def _template_similarity_features(probs, a, b, third):
    pa = np.asarray(probs[a], dtype=float)
    pb = np.asarray(probs[b], dtype=float)
    pc = np.asarray(probs[third], dtype=float)

    min_mass = float(np.minimum(pa, pb).sum())
    max_mass = float(np.maximum(pa, pb).sum())
    overlap = (
        min_mass / max_mass
        if max_mass > 1e-9
        else 0.0
    )
    active_a = set(
        np.flatnonzero(pa >= 0.08).tolist()
    )
    active_b = set(
        np.flatnonzero(pb >= 0.08).tolist()
    )
    union = active_a | active_b
    active_jaccard = (
        float(len(active_a & active_b)) / float(len(union))
        if union else 0.0
    )
    rank_corr = _rank_correlation(pa, pb)
    cosine = _cosine_vector(pa, pb)
    third_cosine = max(
        _cosine_vector(pa, pc),
        _cosine_vector(pb, pc),
    )
    isolation = float(cosine - third_cosine)
    delta = pb - pa
    positive = float(np.sum(np.maximum(delta, 0.0)))
    negative = float(np.sum(np.maximum(-delta, 0.0)))
    exchange = (
        min(positive, negative)
        / max(positive + negative, 1e-9)
    )
    return {
        "cosine": float(cosine),
        "template_overlap": float(overlap),
        "active_jaccard": float(active_jaccard),
        "rank_correlation": float(rank_corr),
        "third_phase_max_cosine": float(third_cosine),
        "third_phase_isolation": isolation,
        "template_exchange_ratio": float(exchange),
    }


def _cosine_vector(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    denominator = float(
        np.linalg.norm(a) * np.linalg.norm(b)
    )
    if denominator <= 1e-12:
        return 0.0
    return float(np.dot(a, b) / denominator)


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
    """Detect a k=3 fit that contains one internal, redundant split.

    The detector combines phase-template similarity with evidence that the
    candidate boundary is weaker and less topologically distributive than the
    other two phase boundaries. No fixed intersection directions are assumed.
    """
    probs = np.asarray(fit3.get("probs"), dtype=float)
    if (
        probs.ndim != 2
        or probs.shape[0] != 3
        or fit2 is None
    ):
        return {
            "detected": False,
            "method": "invalid_redundancy_inputs",
            "candidate_pair": None,
            "pairs": [],
        }
    labels3 = np.asarray(
        fit3.get("labels"),
        dtype=np.int16,
    )
    if labels3.shape != (x.shape[0],):
        return {
            "detected": False,
            "method": "invalid_redundancy_labels",
            "candidate_pair": None,
            "pairs": [],
        }
        return {
            "detected": False,
            "method": "invalid_redundancy_inputs",
            "candidate_pair": None,
            "pairs": [],
        }

    support = _phase_support_metrics(fit3)
    support_by_phase = {
        str(key): int(value)
        for key, value in support["phase_support_by_phase"].items()
    }
    boundary_stats = _phase_boundary_stats(
        fit3,
        x,
        float(period),
        float(dt),
    )
    duration_balance = _duration_balance_by_pair(
        fit3,
        float(period),
    )
    cycle_count = (
        float(cycles)
        if cycles is not None
        else max(
            1.0,
            float(len(x) * dt) / max(float(period), 1e-9),
        )
    )

    ll3 = float(fit3.get("pointwise_loglik", fit3.get("score", 0.0)))
    ll2 = float(fit2.get("pointwise_loglik", fit2.get("score", 0.0)))
    effective_obs = max(2, int(x.shape[0] * x.shape[1]))
    bic3 = (
        -2.0 * ll3
        + 3 * x.shape[1] * math.log(effective_obs)
    )
    bic2 = (
        -2.0 * ll2
        + 2 * x.shape[1] * math.log(effective_obs)
    )
    bic_gap_per_cycle = float(
        (bic3 - bic2) / cycle_count
    )

    rows = []
    for a, b in itertools.combinations(range(3), 2):
        third = 3 - a - b
        features = _template_similarity_features(
            probs,
            a,
            b,
            third,
        )
        key = tuple(sorted((a, b)))
        boundary = boundary_stats.get(
            key,
            {
                "change_strength": 0.0,
                "exchange_ratio": 1.0,
                "observations": 0,
            },
        )
        other_keys = [
            tuple(sorted((a, third))),
            tuple(sorted((b, third))),
        ]
        other_strengths = [
            float(
                boundary_stats.get(
                    other_key,
                    {"change_strength": 0.0},
                )["change_strength"]
            )
            for other_key in other_keys
            if other_key in boundary_stats
        ]
        if other_strengths:
            boundary_strength_ratio = (
                float(boundary["change_strength"])
                / max(
                    float(np.median(other_strengths)),
                    1e-6,
                )
            )
        else:
            boundary_strength_ratio = 1.0

        unsupported = (
            support_by_phase.get(str(a), 0) == 0
            or support_by_phase.get(str(b), 0) == 0
        )
        pair_affinity = (
            0.28 * float(features["template_overlap"])
            + 0.24 * float(features["active_jaccard"])
            + 0.20 * max(
                float(features["rank_correlation"]),
                0.0,
            )
            + 0.12 * max(
                min(
                    float(features["third_phase_isolation"]) / 0.20,
                    1.0,
                ),
                0.0,
            )
            + 0.10 * float(
                duration_balance.get(key, 0.0)
            )
            + 0.06 * (
                1.0
                - min(
                    float(boundary["exchange_ratio"]),
                    1.0,
                )
            )
        )

        merged_labels = np.where(
            (labels3 == a) | (labels3 == b),
            0,
            1,
        ).astype(np.int16)
        merged_probs = fit_bernoulli_templates(
            x,
            merged_labels,
            2,
        )
        merge_loss = max(
            0.0,
            ll3 - _pointwise_loglik(
                x,
                merged_probs,
                merged_labels,
            ),
        ) / max(cycle_count, 1.0)

        rows.append(
            {
                **features,
                "pair": [int(a), int(b)],
                "pair_id": int(len(rows)),
                "duration_balance": float(
                    duration_balance.get(key, 0.0)
                ),
                "boundary_change_strength": float(
                    boundary["change_strength"]
                ),
                "boundary_exchange_ratio": float(
                    boundary["exchange_ratio"]
                ),
                "boundary_strength_ratio": float(
                    min(
                        2.0,
                        max(
                            0.0,
                            boundary_strength_ratio,
                        ),
                    )
                ),
                "boundary_observations": int(
                    boundary["observations"]
                ),
                "pair_has_unsupported_phase": bool(
                    unsupported
                ),
                "merge_loss_per_cycle": float(merge_loss),
                "pair_affinity": float(pair_affinity),
            }
        )

    rows.sort(
        key=lambda item: (
            -float(item["pair_affinity"]),
            float(item["merge_loss_per_cycle"]),
        )
    )
    candidate = rows[0]
    candidate_weak_boundary = (
        float(candidate["boundary_strength_ratio"]) <= 0.82
        or (
            float(candidate["boundary_exchange_ratio"]) <= 0.20
            and float(candidate["boundary_strength_ratio"]) <= 0.95
        )
    )
    topological_redundancy = (
        float(candidate["template_overlap"]) >= 0.68
        and float(candidate["active_jaccard"]) >= 0.55
        and float(candidate["rank_correlation"]) >= 0.35
        and float(candidate["duration_balance"]) >= 0.45
        and float(candidate["third_phase_isolation"]) >= 0.04
    )
    sparse_weak_phase = (
        bool(candidate["pair_has_unsupported_phase"])
        and float(candidate["template_overlap"]) >= 0.62
        and float(candidate["active_jaccard"]) >= 0.45
        and float(candidate["rank_correlation"]) >= 0.25
        and float(candidate["third_phase_isolation"]) >= 0.03
    )
    merge_cost_ok = (
        float(candidate["merge_loss_per_cycle"]) <= 18.0
        or float(candidate["pair_affinity"]) >= 0.78
    )
    selected = bool(
        (
            topological_redundancy
            and candidate_weak_boundary
            and merge_cost_ok
            and (
                float(candidate["boundary_exchange_ratio"]) <= 0.35
                or float(candidate["boundary_strength_ratio"]) <= 0.70
            )
        )
        or (
            sparse_weak_phase
            and candidate_weak_boundary
            and merge_cost_ok
        )
    )

    return {
        "detected": selected,
        "method": "topological_temporal_redundancy_v4",
        "candidate_pair": candidate["pair"],
        "supported_phase_count": int(
            support["supported_phase_count"]
        ),
        "unsupported_phase_count": int(
            support["unsupported_phase_count"]
        ),
        "phase_support_by_phase": support_by_phase,
        "bic_gap_per_cycle": bic_gap_per_cycle,
        "pairs": rows,
    }

def candidate_metrics(fit, x_shape):
    """Compare the same data-likelihood definition for seed and refined paths.

    pointwise_loglik is the historical alias; score-only fits are deliberately
    rejected because their duration-penalty semantics cannot be inferred.
    This approximate complete-path criterion is not marginal model evidence.
    """
    n, s = x_shape
    data_ll = float(fit['data_loglik'] if 'data_loglik' in fit else fit['pointwise_loglik'])
    if not math.isfinite(data_ll):
        raise ValueError('finite returned-model data_loglik required')
    p_count = fit['k'] * s
    effective_obs = max(2, n * s)
    bic = (
        -2.0 * data_ll
        + p_count * math.log(effective_obs)
    )
    seg_lengths = [
        b - a
        for a, b, _ in fit['segments']
    ]
    return {
        'k': int(fit['k']),
        'objective': data_ll,
        'objective_semantics': 'returned_model_data_loglik',
        'initialization_diagnostics': fit.get('initialization_diagnostics', {}),
        'data_loglik': data_ll,
        'penalized_objective': fit.get('penalized_objective'),
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
        **_phase_support_metrics(fit),
    }

@dataclass(frozen=True)
class PhaseSearchConfig:
    kmin: int = 2
    kmax: int = 6
    max_candidates: int = 5
    max_seconds: float = 60.0

    def __post_init__(self):
        if any(isinstance(v,bool) or not isinstance(v,int) for v in (self.kmin,self.kmax,self.max_candidates)):
            raise ValueError("integer search bounds and candidate budget required")
        if not 1 <= self.kmin <= self.kmax or self.max_candidates < 0:
            raise ValueError("invalid phase search range/budget")
        if not math.isfinite(self.max_seconds) or self.max_seconds < 0:
            raise ValueError("finite nonnegative search time budget required")


class PhaseCountSearch(tuple):
    """Three-item legacy API plus complete search/evidence diagnostics."""
    def __new__(cls, selected, candidates, fits, diagnostics):
        obj=super().__new__(cls,(selected,candidates,fits))
        obj.diagnostics=diagnostics
        return obj


def discover_phase_count(
    x, by_stream_global, period, kmin=2, kmax=6, dt=1.0,
    extra_phase_penalty_per_cycle: float=5.0,
    recording_end_s: Optional[float]=None, entry_streams=None, topology_streams=None,
    *, max_candidates=5, max_seconds=60.0,
):
    """Topology-free candidate comparison, bounded by calls and cooperative time.

    Names/cardinality never cap K. Time is checked between unchanged em_fit calls;
    an in-flight call may overrun. The offline worker supplies a hard file timeout.
    No calibrated confidence or global optimum follows from this finite search.
    """
    config=PhaseSearchConfig(kmin,kmax,max_candidates,max_seconds)
    started=time.monotonic(); candidates=[]; fits={}; ledger=[]
    event_count=sum(len(v) for v in by_stream_global.values())
    cycle_count=max(1.,float(recording_end_s or len(x)*dt)/max(float(period),1e-6))
    attempted=0
    for k in range(config.kmin,config.kmax+1):
        reason=None
        if not event_count and not np.any(x):
            reason="NO_DEMAND_OR_PERMISSION_OBSERVATIONS"
        elif attempted >= config.max_candidates:
            reason="CANDIDATE_BUDGET_EXHAUSTED"
        elif time.monotonic()-started >= config.max_seconds:
            reason="TIME_BUDGET_EXHAUSTED"
        if reason:
            ledger.append({"k":k,"status":"skipped","reason":reason}); continue
        attempted+=1; before=time.monotonic()
        try:
            fit=em_fit(x,period,k,by_stream_global=by_stream_global,
                       entry_streams=entry_streams,dt=dt,iterations=2)
        except TimeoutError as exc:
            ledger.append({"k":k,"status":"timeout","reason":str(exc),"runtime_s":time.monotonic()-before})
            continue
        except (ValueError, RuntimeError, FloatingPointError) as exc:
            ledger.append({"k":k,"status":"failed","reason":type(exc).__name__+": "+str(exc),
                           "runtime_s":time.monotonic()-before})
            continue
        metrics=candidate_metrics(fit,x.shape)
        metrics['recurrent_complexity_penalty']=float(extra_phase_penalty_per_cycle*max(0,k-2)*cycle_count)
        metrics['criterion_score']=float(metrics['approx_bic']+metrics['recurrent_complexity_penalty'])
        metrics['degenerate_phase_model']=metrics.get('unsupported_phase_count',0)>1 and k>2
        metrics['phase_support_penalty']=float('inf') if metrics['degenerate_phase_model'] else 0.
        metrics['selection_score']=float('inf') if metrics['degenerate_phase_model'] else metrics['criterion_score']
        metrics['topology_cap_applied']=False
        metrics['eligibility_reason']='MULTIPLE_UNSUPPORTED_PHASES' if metrics['degenerate_phase_model'] else None
        labels=fit.get('labels')
        support={str(z):0 for z in range(k)}
        for values in by_stream_global.values():
            for t in values:
                i=int(float(t)/dt)
                if labels is not None and 0<=i<len(labels):
                    z=int(labels[i])
                else:
                    z=next((int(z) for a,b,z in fit['segments'] if a<=float(t)<b),-1)
                if 0<=z<k:
                    support[str(z)]+=1
        metrics['event_support_by_phase']=support
        metrics['runtime_s']=time.monotonic()-before
        fits[k]=fit; candidates.append(metrics)
        ledger.append({"k":k,"status":"evaluated","reason":metrics['eligibility_reason'],
                       "runtime_s":metrics['runtime_s']})
    eligible=[c for c in candidates if math.isfinite(c['selection_score'])]
    ranked=sorted(eligible,key=lambda c:c['selection_score'])
    selected=ranked[0]['k'] if ranked else None
    elapsed=time.monotonic()-started
    complete=all(row['status']=='evaluated' for row in ledger) and elapsed<=config.max_seconds
    chosen=ranked[0] if ranked else None
    weak=bool(chosen and (chosen['unsupported_phase_count'] or any(v==0 for v in chosen['event_support_by_phase'].values())))
    diagnostics={"requested_range":[config.kmin,config.kmax],
        "budget":{"max_candidates":config.max_candidates,"max_seconds":config.max_seconds,
                  "enforcement":"candidate-call bound; cooperative wall time; no in-flight preemption"},
        "candidate_ledger":ledger,"search_status":"complete" if complete else "partial_or_unavailable",
        "attempted_candidate_count":attempted,"evaluated_candidate_count":len(candidates),
        "elapsed_s":elapsed,"selected_k":selected,"alternatives_ranked":[c['k'] for c in ranked],
        "budget_overrun_s":max(0.,elapsed-config.max_seconds),
        "score_margin":ranked[1]['selection_score']-ranked[0]['selection_score'] if len(ranked)>1 else None,
        "score_margin_semantics":"uncalibrated_criterion_difference_NOT_confidence",
        "optimality":"best_eligible_evaluated_candidate_NOT_proven_global_optimum",
        "event_count":event_count,
        "evidence_status":'NO_EVALUABLE_CANDIDATE' if chosen is None else
            'UNSUPPORTED_PHASES_OR_NO_EVENTS' if weak else 'MODEL_SIGNATURE_SUPPORTED_NOT_EXTERNAL_VALIDATION',
        "ambiguity":"PARTIAL_SEARCH" if not complete else 'UNSUPPORTED_PHASES' if weak else
            'EQUAL_SELECTION_SCORES' if len(ranked)>1 and ranked[0]['selection_score']==ranked[1]['selection_score'] else
            'ALTERNATIVES_RETAINED_NO_CALIBRATED_CERTAINTY',
        "topology_prior":"none; stream names are not verified geometry"}
    return PhaseCountSearch(selected,candidates,fits,diagnostics)


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
