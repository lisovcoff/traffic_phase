from __future__ import annotations
import math
import json
import itertools
from array import array
from bisect import bisect_left, bisect_right
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence
import numpy as np
from scipy.ndimage import gaussian_filter1d

from .primitives import build_streams_from_base, build_occupancy_matrix, infer_period
from .fit import (
    discover_phase_count,
    anonymous_phase_name,
    phase_activity_summary,
    evaluate_phase_redundancy,
)
from .events import (
    extract_event_views,
    load_event_streams,
    _recording_start_ms,
    periodic_baseline_from_segments,
    _phase_duration_targets_from_baseline,
    detect_temporary_phase_deviations,
)
from .evaluate import evaluate
from app.core.v10.automatic_physical import infer_physical_signal_plan

def _discover_from_event_views(
    events,
    entry_events,
    release_evidence,
    method_counts,
    *,
    input_name: str = "records",
    dt: float = 1.0,
    marks_path: Optional[Path] = None,
    recording_start_ms: float | None = None,
    trajectory_count: int = 0,
):
    if not events:
        raise ValueError("no traffic events supplied")
    by_stream, _base_ms, end_s = build_streams_from_base(
        events,
        events[0][0],
    )
    entry_streams, _entry_base_ms, _entry_end_s = build_streams_from_base(
        entry_events,
        events[0][0],
    )
    release_methods = defaultdict(int)
    release_streams = defaultdict(list)
    for row in release_evidence:
        release_methods[row[3]] += 1
        release_streams[row[1]].append(
            (float(row[0]) - float(events[0][0])) / 1000.0
        )
    return _discover_from_stream_views(
        by_stream,
        entry_streams,
        method_counts,
        dict(release_methods),
        release_streams=dict(release_streams),
        input_name=input_name,
        dt=dt,
        marks_path=marks_path,
        recording_start_ms=recording_start_ms,
        analysis_base_ms=float(events[0][0]),
        trajectory_count=trajectory_count,
        event_count=len(events),
    )

def _slice_streams(streams, start_s: float, end_s: float):
    sliced = {}
    for stream, values in streams.items():
        left = bisect_left(values, float(start_s))
        right = bisect_left(values, float(end_s))
        if right <= left:
            continue
        offset_values = (
            float(value) - float(start_s)
            for value in values[left:right]
        )
        if isinstance(values, array):
            sliced[stream] = array(values.typecode, offset_values)
        else:
            sliced[stream] = type(values)(offset_values)
    return sliced


def _regime_phase_structure(
    by_stream,
    entry_streams,
    release_streams,
    *,
    period: float,
    window_s: float,
) -> dict[str, object] | None:
    """Fit phase structure for one local regime window.

    Period stability alone cannot distinguish a true phase topology from a
    boundary/initialization artifact. Reuse the canonical V9 phase-count
    selection here so regime selection can prefer the structure that recurs
    across multiple windows.
    """
    event_count = sum(len(values) for values in entry_streams.values())
    if event_count <= 0:
        return None

    phase_evidence, evidence_method = _choose_phase_evidence(
        by_stream,
        release_streams,
        event_count,
    )
    end_s = max(
        (
            max(float(value) for value in values)
            for values in phase_evidence.values()
            if len(values)
        ),
        default=0.0,
    )
    if end_s <= 0.0:
        return None

    x, _names = build_occupancy_matrix(
        phase_evidence,
        end_s,
        dt=1.0,
    )
    try:
        selected_k, candidates, fits = discover_phase_count(
            x,
            phase_evidence,
            float(period),
            dt=1.0,
            recording_end_s=max(1.0, float(window_s)),
            entry_streams=entry_streams,
            topology_streams=by_stream,
        )
    except Exception:
        return None

    selected_candidate = next(
        (
            candidate
            for candidate in candidates
            if int(candidate["k"]) == int(selected_k)
        ),
        None,
    )
    if selected_candidate is None:
        return None

    fit = fits[selected_k]
    coherence = float(
        np.clip(
            float(fit.get("boundary_coherence", 0.0)),
            0.0,
            1.0,
        )
    )
    return {
        "phase_count": int(selected_k),
        "phase_evidence_source": evidence_method,
        "boundary_coherence": coherence,
        "supported_phase_count": int(
            selected_candidate.get("supported_phase_count", 0)
        ),
        "unsupported_phase_count": int(
            selected_candidate.get("unsupported_phase_count", 0)
        ),
        "selection_score": float(
            selected_candidate.get("selection_score", float("inf"))
        ),
    }


def _cluster_local_regime_windows(windows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Cluster hourly windows by period regime and recurring phase topology."""
    clusters: list[dict[str, object]] = []
    for window in windows:
        phase_count = window.get("selected_phase_count")
        placed = False
        for cluster in clusters:
            if (
                phase_count == cluster["phase_count"]
                and abs(
                    float(window["period_bucket_s"])
                    - float(cluster["center_s"])
                ) <= 4.0
            ):
                cluster["windows"].append(window)
                weights = [
                    max(1.0, float(item["event_count"]))
                    * max(0.05, float(item["confidence"]))
                    for item in cluster["windows"]
                ]
                cluster["center_s"] = float(
                    sum(
                        float(item["period_bucket_s"]) * weight
                        for item, weight in zip(
                            cluster["windows"],
                            weights,
                        )
                    )
                    / max(1e-9, sum(weights))
                )
                placed = True
                break
        if not placed:
            clusters.append(
                {
                    "center_s": float(window["period_bucket_s"]),
                    "phase_count": (
                        int(phase_count)
                        if phase_count is not None
                        else None
                    ),
                    "windows": [window],
                }
            )

    for cluster in clusters:
        cluster["support_events"] = int(
            sum(int(item["event_count"]) for item in cluster["windows"])
        )
        cluster["support_windows"] = int(len(cluster["windows"]))
        cluster["mean_boundary_coherence"] = float(
            np.mean(
                [
                    float(item.get("boundary_coherence", 0.0))
                    for item in cluster["windows"]
                ]
            )
        )
        cluster["support_score"] = float(
            sum(
                max(1.0, float(item["event_count"]))
                * max(0.05, float(item["confidence"]))
                for item in cluster["windows"]
            )
        )
    return clusters


def _local_regime_selection(
    by_stream,
    entry_streams,
    release_streams,
    total_end_s,
    *,
    window_s: float = 3600.0,
    min_events: int = 120,
):
    if total_end_s < 2.0 * window_s:
        return None

    windows = []
    max_start = float(total_end_s) - float(window_s)
    start = 0.0
    while start <= max_start + 1e-9:
        end = start + window_s
        entry_window = _slice_streams(entry_streams, start, end)
        event_count = sum(len(values) for values in entry_window.values())
        if event_count >= min_events:
            period, info = infer_period(entry_window)
            top = info.get("top_candidates", [{}])[0]
            score = float(top.get("combined_score", 0.0))
            confidence = max(0.0, min(1.0, score))

            window_by_stream = _slice_streams(by_stream, start, end)
            release_window = _slice_streams(
                release_streams,
                start,
                end,
            )
            phase_structure = _regime_phase_structure(
                window_by_stream,
                entry_window,
                release_window,
                period=float(period),
                window_s=window_s,
            )
            if phase_structure is None:
                selected_phase_count = None
                boundary_coherence = 0.0
                supported_phase_count = 0
                unsupported_phase_count = 0
            else:
                selected_phase_count = int(
                    phase_structure["phase_count"]
                )
                boundary_coherence = float(
                    phase_structure["boundary_coherence"]
                )
                supported_phase_count = int(
                    phase_structure["supported_phase_count"]
                )
                unsupported_phase_count = int(
                    phase_structure["unsupported_phase_count"]
                )
            bucket = round(float(period) / 2.0) * 2.0
            windows.append(
                {
                    "start_s": float(start),
                    "end_s": float(end),
                    "period_s": float(period),
                    "period_bucket_s": float(bucket),
                    "event_count": int(event_count),
                    "score": float(score),
                    "confidence": float(confidence),
                    "selected_phase_count": selected_phase_count,
                    "boundary_coherence": boundary_coherence,
                    "supported_phase_count": supported_phase_count,
                    "unsupported_phase_count": unsupported_phase_count,
                }
            )
        start += window_s

    if not windows:
        return None

    clusters = _cluster_local_regime_windows(windows)

    selected_cluster = max(
        clusters,
        key=lambda item: (
            item["support_score"],
            item["support_windows"],
            item["support_events"],
            -abs(float(item["center_s"]) - 120.0),
        ),
    )
    representative = max(
        selected_cluster["windows"],
        key=lambda item: (
            max(0.05, float(item["confidence"]))
            * max(0.25, float(item.get("boundary_coherence", 0.0)))
            * max(1.0, float(item["event_count"])),
            float(item["event_count"]),
        ),
    )
    selected_start = float(representative["start_s"])
    selected_end = float(representative["end_s"])

    regime_detection = {
        "method": "hourly_local_period_consensus",
        "window_s": float(window_s),
        "windows_evaluated": int(len(windows)),
        "candidate_regimes": [
            {
                "period_s": round(float(cluster["center_s"]), 3),
                "phase_count": cluster["phase_count"],
                "support_windows": int(cluster["support_windows"]),
                "support_events": int(cluster["support_events"]),
                "support_score": round(float(cluster["support_score"]), 3),
                "mean_boundary_coherence": round(
                    float(cluster["mean_boundary_coherence"]),
                    4,
                ),
            }
            for cluster in sorted(
                clusters,
                key=lambda item: item["support_score"],
                reverse=True,
            )
        ],
        "selected_period_s": round(float(selected_cluster["center_s"]), 3),
        "selected_phase_count": selected_cluster["phase_count"],
        "selected_window_start_s": round(selected_start, 3),
        "selected_window_end_s": round(selected_end, 3),
        "selected_window_event_count": int(representative["event_count"]),
        "selected_window_confidence": round(
            float(representative["confidence"]),
            4,
        ),
        "selected_window_boundary_coherence": round(
            float(representative.get("boundary_coherence", 0.0)),
            4,
        ),
        "scope": "single_representative_window_from_dominant_period_and_phase_topology",
    }
    return (
        regime_detection,
        (
            _slice_streams(by_stream, selected_start, selected_end),
            _slice_streams(entry_streams, selected_start, selected_end),
            _slice_streams(release_streams, selected_start, selected_end),
        ),
    )


def _choose_phase_evidence(by_stream, release_streams, event_count: int):
    release_events = sum(len(values) for values in release_streams.values())
    active_streams = sum(bool(values) for values in by_stream.values())
    release_stream_count = sum(bool(values) for values in release_streams.values())
    sufficient = (
        release_events >= max(80, int(0.15 * max(1, event_count)))
        and active_streams > 0
        and release_stream_count >= max(1, int(math.ceil(0.5 * active_streams)))
    )
    if sufficient:
        return release_streams, "release_only"
    return by_stream, "mixed_release_or_entry"



def _calibrate_phase_anchor(
    phase_evidence,
    stream_names,
    phase_probs,
    baseline_segments,
    period: float,
    initial_anchor_s: float,
    *,
    min_improvement: float = 5.0,
) -> dict[str, object]:
    if not phase_evidence or period <= 0.0:
        return {
            "applied": False,
            "method": "not_available",
            "initial_anchor_s": float(initial_anchor_s),
            "delta_s": 0.0,
            "final_anchor_s": float(initial_anchor_s),
        }

    probs = np.asarray(phase_probs, dtype=float)
    if probs.ndim != 2 or probs.shape[1] != len(stream_names):
        return {
            "applied": False,
            "method": "invalid_phase_probability_shape",
            "initial_anchor_s": float(initial_anchor_s),
            "delta_s": 0.0,
            "final_anchor_s": float(initial_anchor_s),
        }

    starts = np.asarray(
        [float(row[0]) for row in baseline_segments],
        dtype=float,
    )
    if starts.size == 0:
        return {
            "applied": False,
            "method": "no_baseline_segments",
            "initial_anchor_s": float(initial_anchor_s),
            "delta_s": 0.0,
            "final_anchor_s": float(initial_anchor_s),
        }

    stream_arrays = []
    for index, stream in enumerate(stream_names):
        values = np.asarray(phase_evidence.get(stream, ()), dtype=float)
        values = values[np.isfinite(values)]
        if values.size:
            stream_arrays.append((index, values))

    if not stream_arrays:
        return {
            "applied": False,
            "method": "no_full_archive_phase_evidence",
            "initial_anchor_s": float(initial_anchor_s),
            "delta_s": 0.0,
            "final_anchor_s": float(initial_anchor_s),
        }

    def score(delta_s: float) -> float:
        anchor = float(initial_anchor_s) + float(delta_s)
        total = 0.0
        for index, values in stream_arrays:
            positions = np.mod(values - anchor, float(period))
            phase_index = np.searchsorted(
                starts,
                positions,
                side="right",
            ) - 1
            phase_index = np.clip(
                phase_index,
                0,
                probs.shape[0] - 1,
            )
            probabilities = np.clip(
                probs[phase_index, index],
                0.005,
                0.995,
            )
            total += float(np.log(probabilities).sum())
        return total

    coarse_step = max(0.25, min(1.0, float(period) / 240.0))
    coarse = np.arange(0.0, float(period), coarse_step, dtype=float)
    coarse_scores = np.asarray(
        [score(float(delta)) for delta in coarse],
        dtype=float,
    )
    best_delta = float(coarse[int(np.argmax(coarse_scores))])

    refine_step = 0.05
    refined = np.arange(
        max(0.0, best_delta - coarse_step),
        min(float(period), best_delta + coarse_step + refine_step),
        refine_step,
        dtype=float,
    )
    refined_scores = np.asarray(
        [score(float(delta)) for delta in refined],
        dtype=float,
    )
    best_i = int(np.argmax(refined_scores))
    calibrated_delta = float(refined[best_i])
    initial_score = float(score(0.0))
    best_score = float(refined_scores[best_i])
    improvement = best_score - initial_score
    applied = improvement >= float(min_improvement)

    return {
        "applied": bool(applied),
        "method": "full_archive_phase_signature_anchor",
        "initial_anchor_s": float(initial_anchor_s),
        "delta_s": calibrated_delta if applied else 0.0,
        "candidate_period_s": float(period),
        "initial_score": initial_score,
        "best_score": best_score,
        "score_improvement": float(improvement),
        "coarse_step_s": float(coarse_step),
        "refine_step_s": float(refine_step),
        "final_anchor_s": float(
            initial_anchor_s + (calibrated_delta if applied else 0.0)
        ),
    }


def _discover_from_stream_views(
    by_stream,
    entry_streams,
    method_counts,
    release_method_counts,
    *,
    release_streams=None,
    input_name: str = "records",
    dt: float = 1.0,
    marks_path: Optional[Path] = None,
    recording_start_ms: float | None = None,
    analysis_base_ms: float | None = None,
    trajectory_count: int = 0,
    event_count: int | None = None,
    source_files=None,
):
    if not by_stream:
        raise ValueError("no traffic events supplied")
    if release_streams is None:
        release_streams = {}
    original_end_s = max(
        max(float(value) for value in ts)
        for ts in by_stream.values()
        if len(ts)
    )
    regime_detection = None
    working_by_stream = by_stream
    working_entry_streams = entry_streams
    working_release_streams = release_streams
    if original_end_s >= 7200.0:
        regime_payload = _local_regime_selection(
            by_stream,
            entry_streams,
            release_streams,
            original_end_s,
        )
        if regime_payload is not None:
            regime_detection, (
                working_by_stream,
                working_entry_streams,
                working_release_streams,
            ) = regime_payload
    if analysis_base_ms is None:
        first = min(
            float(ts[0])
            for ts in by_stream.values()
            if len(ts)
        )
        analysis_base_ms = first
    end_s = max(
        max(float(value) for value in ts)
        for ts in working_by_stream.values()
        if len(ts)
    )
    entry_end_s = max(
        max(float(value) for value in ts)
        for ts in working_entry_streams.values()
        if len(ts)
    )
    local_start_s = (
        float(regime_detection.get("selected_window_start_s", 0.0))
        if regime_detection is not None
        else 0.0
    )
    phase_anchor_calibration = {
        "applied": False,
        "method": "not_required",
        "initial_anchor_s": float(local_start_s),
        "delta_s": 0.0,
        "final_anchor_s": float(local_start_s),
    }
    period, period_info = infer_period(working_entry_streams)
    working_event_count = sum(len(ts) for ts in working_by_stream.values())
    phase_evidence, phase_evidence_method = _choose_phase_evidence(
        working_by_stream,
        working_release_streams,
        working_event_count,
    )
    x, names = build_occupancy_matrix(
        phase_evidence,
        end_s,
        dt=dt,
    )
    selected_k, count_candidates, all_fits = discover_phase_count(
        x,
        phase_evidence,
        period,
        dt=dt,
        recording_end_s=end_s,
        entry_streams=working_entry_streams,
        topology_streams=working_by_stream,
    )
    raw_selected_k = int(selected_k)
    phase_redundancy = {
        "detected": False,
        "method": "not_evaluated",
        "candidate_pair": None,
        "pairs": [],
    }
    fit = all_fits[selected_k]
    if selected_k == 3 and 2 in all_fits:
        phase_redundancy = evaluate_phase_redundancy(
            all_fits[3],
            all_fits[2],
            x,
            period,
            phase_evidence,
            dt=dt,
        )
        if bool(phase_redundancy.get("detected")):
            selected_k = 2
            fit = all_fits[2]

    raw_segments = [
        tuple(float(value) for value in segment)
        for segment in fit["segments"]
    ]
    baseline_segments, phase_centers = periodic_baseline_from_segments(
        raw_segments,
        period,
        end_s,
    )
    baseline_durations = _phase_duration_targets_from_baseline(
        baseline_segments,
        selected_k,
    )
    deviations = detect_temporary_phase_deviations(
        raw_segments,
        baseline_segments,
        selected_k,
    )

    if regime_detection is not None:
        archive_phase_evidence = (
            release_streams
            if phase_evidence_method == "release_only"
            else by_stream
        )
        phase_anchor_calibration = _calibrate_phase_anchor(
            archive_phase_evidence,
            names,
            fit["probs"],
            baseline_segments,
            period,
            local_start_s,
        )
        local_start_s += float(
            phase_anchor_calibration.get("delta_s", 0.0)
        )

    schedule_base_ms = (
        float(analysis_base_ms)
        + local_start_s * 1000.0
    )


    phase_durations = defaultdict(list)
    for a, b, z in raw_segments:
        phase_durations[int(z)].append(float(b - a))
    duration_summary = {
        anonymous_phase_name(z): {
            "median_s": float(np.median(values)) if values else 0.0,
            "mean_s": float(np.mean(values)) if values else 0.0,
            "observations": len(values),
        }
        for z, values in sorted(phase_durations.items())
    }

    result: dict[str, object] = {
        "algorithm": "direction-agnostic traffic phase discovery V9",
        "input": input_name,
        "trajectory_count": int(trajectory_count),
        "event_count": int(
            event_count if event_count is not None
            else sum(len(ts) for ts in by_stream.values())
        ),
        "movement_stream_count": len(by_stream),
        "movement_streams": {
            stream: len(times)
            for stream, times in sorted(working_by_stream.items())
        },
        "archive_stream_event_counts": {
            stream: len(times)
            for stream, times in sorted(by_stream.items())
        },
        "analysis_base_timestamp_ms": float(schedule_base_ms),
        "event_base_timestamp_ms": float(analysis_base_ms),
        "schedule_base_timestamp_ms": float(schedule_base_ms),
        "recording_start_timestamp_ms": (
            float(recording_start_ms)
            if recording_start_ms is not None
            else None
        ),
        "recording_duration_s": max(
            original_end_s,
            max(
                max(float(value) for value in ts)
                for ts in entry_streams.values()
                if len(ts)
            ),
        ),
        "event_extraction": {
            "methods": method_counts,
            "release_evidence_count": int(
                sum(release_method_counts.values())
            ),
            "release_evidence_methods": {
                name: int(count)
                for name, count in sorted(
                    release_method_counts.items()
                )
            },
            "manual_marks_used_for_discovery": False,
        },
        "period_inference": {
            "period_s": float(period),
            **period_info,
        },
        "regime_detection": (
            regime_detection
            if regime_detection is not None
            else {
                "method": "global_fallback",
                "scope": "full_input",
            }
        ),
        "phase_anchor_calibration": phase_anchor_calibration,
        "phase_redundancy": phase_redundancy,
        "phase_evidence": {
            "source": phase_evidence_method,
            "release_event_count": int(
                sum(len(values) for values in working_release_streams.values())
            ),
        },
        "phase_model_selection": {
            "raw_selected_phase_count": int(raw_selected_k),
            "selected_phase_count": int(selected_k),
            "redundancy_detector": phase_redundancy.get(
                "method",
                "not_evaluated",
            ),
            "topology_prior": {
                "canonical_four_leg_cap_applied": bool(
                    any(
                        stream in working_by_stream
                        for stream in (
                            "N->S", "S->N", "E->W", "W->E"
                        )
                    )
                    and all(
                        stream in working_by_stream
                        for stream in (
                            "N->S", "S->N", "E->W", "W->E"
                        )
                    )
                ),
            },
            "criterion": (
                "approximate_BIC_plus_recurrent_phase_complexity_penalty"
            ),
            "candidates": [
                {
                    "k": int(candidate["k"]),
                    "objective": float(candidate["objective"]),
                    "approx_bic": float(candidate["approx_bic"]),
                    "selection_score": float(
                        candidate["selection_score"]
                    ),
                    "segment_count": int(
                        candidate["segment_count"]
                    ),
                }
                for candidate in count_candidates
            ],
        },
        "schedule": {
            "model": "cyclic_bernoulli_hsmm_plus_periodic_baseline",
            "phase_count": int(selected_k),
            "phase_names": [
                anonymous_phase_name(i)
                for i in range(selected_k)
            ],
            "period_s": float(period),
            "decoder": fit["decoder_info"],
            "raw_hsmm_segments": [
                [float(a), float(b), int(z)]
                for a, b, z in raw_segments
            ],
            "baseline_phase_centers_s": {
                anonymous_phase_name(z): float(value)
                for z, value in sorted(
                    phase_centers.items()
                )
            },
            "baseline_duration_targets_s": {
                anonymous_phase_name(z): float(value)
                for z, value in enumerate(
                    baseline_durations
                )
            },
            "baseline_segments": [
                [float(a), float(b), int(z)]
                for a, b, z in baseline_segments
            ],
            "phase_duration_summary": duration_summary,
            "stream_activity_by_phase": phase_activity_summary(
                names,
                fit["probs"],
            ),
        },
        "anomaly_detection": {
            "temporary_phase_deviations": deviations,
            "cause": "unknown",
        },
        "online": {
            "tracker": "OnlinePhaseTracker",
            "input": "timestamp_ms + anonymous stream",
            "no_retraining_per_chunk": True,
        },
    }
    try:
        result["physical_signal_plan"] = infer_physical_signal_plan(result)
    except ValueError as exc:
        result["physical_signal_plan"] = {
            "enabled": False,
            "auto_inferred": True,
            "model": "v10_automatic_physical_signal_plan",
            "reason": str(exc),
        }

    if marks_path is not None:
        result["evaluation"] = evaluate(
            baseline_segments,
            period,
            float(schedule_base_ms),
            marks_path,
        )
    if source_files is not None:
        result["archive"] = {
            "source_file_count": len(source_files),
            "source_files": [str(value) for value in source_files],
        }
    return result


def discover_records(
    tracks: Sequence[dict],
    *,
    input_name: str = "records",
    dt: float = 1.0,
    marks_path: Optional[Path] = None,
) -> dict[str, object]:
    if not tracks:
        raise ValueError("no trajectory records supplied")
    recording_start_ms = float(_recording_start_ms(tracks))
    events, entry_events, release_evidence, method_counts = extract_event_views(tracks)
    return _discover_from_event_views(
        events,
        entry_events,
        release_evidence,
        method_counts,
        input_name=input_name,
        dt=dt,
        marks_path=marks_path,
        recording_start_ms=recording_start_ms,
        trajectory_count=len(tracks),
    )


def discover_path(
    path: Path,
    *,
    dt: float = 1.0,
    marks_path: Optional[Path] = None,
) -> dict[str, object]:
    path = Path(path)
    if path.is_file() and path.suffix.lower() not in {".json", ".zip"}:
        raise ValueError(f"unsupported V9 source: {path}")
    if path.is_dir() and not path.exists():
        raise FileNotFoundError(path)

    (
        by_stream,
        entry_streams,
        release_streams,
        method_counts,
        release_method_counts,
        source_files,
        recording_start_ms,
        analysis_base_ms,
        trajectory_count,
        event_count,
    ) = load_event_streams(path)

    return _discover_from_stream_views(
        by_stream,
        entry_streams,
        method_counts,
        release_method_counts,
        release_streams=release_streams,
        input_name=str(path),
        dt=dt,
        marks_path=marks_path,
        recording_start_ms=recording_start_ms,
        analysis_base_ms=analysis_base_ms,
        trajectory_count=trajectory_count,
        event_count=event_count,
        source_files=(
            [str(path)]
            if path.is_file()
            else source_files
        ),
    )
