from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from app.core.v9.events import load_event_streams
from app.core.v9.fit import discover_phase_count
from app.core.v9.model import _choose_phase_evidence, _slice_streams
from app.core.v9.primitives import build_occupancy_matrix, infer_period


WINDOW_S = 3600.0
MIN_EVENTS = 120


def _cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    if left_norm <= 1e-12 or right_norm <= 1e-12:
        return 0.0
    return float(np.dot(left, right) / (left_norm * right_norm))


def _phase_signature_diagnostics(probs: np.ndarray) -> dict[str, Any]:
    if probs.ndim != 2 or probs.shape[0] < 2:
        return {
            "pairwise_cosine_similarity": [],
            "max_cosine_similarity": 0.0,
            "min_cosine_distance": 0.0,
        }

    pairs: list[dict[str, Any]] = []
    for left in range(probs.shape[0]):
        for right in range(left + 1, probs.shape[0]):
            similarity = _cosine_similarity(probs[left], probs[right])
            pairs.append(
                {
                    "left_phase": int(left),
                    "right_phase": int(right),
                    "cosine_similarity": round(similarity, 6),
                    "cosine_distance": round(1.0 - similarity, 6),
                }
            )

    max_similarity = max(
        (item["cosine_similarity"] for item in pairs),
        default=0.0,
    )
    min_distance = min(
        (item["cosine_distance"] for item in pairs),
        default=0.0,
    )
    return {
        "pairwise_cosine_similarity": pairs,
        "max_cosine_similarity": round(float(max_similarity), 6),
        "min_cosine_distance": round(float(min_distance), 6),
    }


def _window_diagnostic(
    by_stream: dict[str, Any],
    entry_streams: dict[str, Any],
    release_streams: dict[str, Any],
    start_s: float,
    end_s: float,
    *,
    min_events: int,
) -> dict[str, Any] | None:
    window_by_stream = _slice_streams(by_stream, start_s, end_s)
    window_entry_streams = _slice_streams(entry_streams, start_s, end_s)
    window_release_streams = _slice_streams(release_streams, start_s, end_s)

    event_count = sum(len(values) for values in window_entry_streams.values())
    if event_count < int(min_events):
        return None

    period, period_info = infer_period(window_entry_streams)
    phase_evidence, phase_evidence_method = _choose_phase_evidence(
        window_by_stream,
        window_release_streams,
        event_count,
    )
    end_local_s = max(
        (
            max(float(value) for value in values)
            for values in window_by_stream.values()
            if len(values)
        ),
        default=0.0,
    )
    if end_local_s <= 0.0:
        return None

    x, stream_names = build_occupancy_matrix(
        phase_evidence,
        end_local_s,
        dt=1.0,
    )
    selected_k, candidates, fits = discover_phase_count(
        x,
        phase_evidence,
        period,
        dt=1.0,
        recording_end_s=max(1.0, end_s - start_s),
        entry_streams=window_entry_streams,
        topology_streams=window_by_stream,
    )
    selected_fit = fits[selected_k]
    selected_candidate = next(
        candidate for candidate in candidates
        if int(candidate["k"]) == int(selected_k)
    )

    probs = np.asarray(selected_fit["probs"], dtype=float)
    canonical = ("N->S", "S->N", "E->W", "W->E")
    active_streams = [
        stream for stream in sorted(window_by_stream)
        if window_by_stream[stream]
    ]
    canonical_active = [
        stream for stream in canonical
        if stream in window_by_stream and window_by_stream[stream]
    ]
    active_approaches = sorted(
        {
            stream.split("->", 1)[0]
            for stream in active_streams
            if "->" in stream
        }
    )

    return {
        "start_s": round(float(start_s), 3),
        "end_s": round(float(end_s), 3),
        "event_count": int(event_count),
        "active_stream_count": int(len(active_streams)),
        "active_streams": active_streams,
        "canonical_straight_stream_count": int(len(canonical_active)),
        "canonical_straight_streams": canonical_active,
        "active_approach_count": int(len(active_approaches)),
        "active_approaches": active_approaches,
        "period_s": round(float(period), 6),
        "period_confidence": round(
            max(
                0.0,
                min(
                    1.0,
                    float(
                        period_info.get("top_candidates", [{}])[0].get(
                            "combined_score",
                            0.0,
                        )
                    ),
                ),
            ),
            6,
        ),
        "period_top_candidates": [
            {
                "period_s": round(float(item.get("period_s", 0.0)), 6),
                "combined_score": round(
                    float(item.get("combined_score", 0.0)),
                    6,
                ),
            }
            for item in period_info.get("top_candidates", [])[:5]
        ],
        "phase_evidence_source": phase_evidence_method,
        "selected_phase_count": int(selected_k),
        "phase_candidates": candidates,
        "selected_model": {
            "selection_score": float(selected_candidate["selection_score"]),
            "objective": float(selected_candidate["objective"]),
            "approx_bic": float(selected_candidate["approx_bic"]),
            "recurrent_complexity_penalty": float(
                selected_candidate["recurrent_complexity_penalty"]
            ),
            "supported_phase_count": int(
                selected_candidate["supported_phase_count"]
            ),
            "unsupported_phase_count": int(
                selected_candidate["unsupported_phase_count"]
            ),
            "phase_support_by_phase": selected_candidate[
                "phase_support_by_phase"
            ],
            "phase_contrast_by_phase": selected_candidate[
                "phase_contrast_by_phase"
            ],
            "segment_count": int(selected_candidate["segment_count"]),
            "median_segment_duration_s": float(
                selected_candidate["median_segment_duration_s"]
            ),
            "boundary_coherence": float(
                selected_fit.get("boundary_coherence", 0.0)
            ),
        },
        "phase_signature": _phase_signature_diagnostics(probs),
        "stream_names_used_for_fit": list(stream_names),
    }


def diagnose_path(
    input_path: Path,
    *,
    window_s: float = WINDOW_S,
    min_events: int = MIN_EVENTS,
) -> dict[str, Any]:
    if window_s <= 0:
        raise ValueError("window_s must be positive")
    if min_events <= 0:
        raise ValueError("min_events must be positive")

    (
        by_stream,
        entry_streams,
        release_streams,
        _method_counts,
        _release_method_counts,
        source_files,
        recording_start_ms,
        analysis_base_ms,
        trajectory_count,
        event_count,
    ) = load_event_streams(Path(input_path))

    total_end_s = max(
        (
            max(float(value) for value in values)
            for values in by_stream.values()
            if len(values)
        ),
        default=0.0,
    )
    windows: list[dict[str, Any]] = []
    start_s = 0.0
    while start_s + float(window_s) <= total_end_s + 1e-9:
        diagnostic = _window_diagnostic(
            by_stream,
            entry_streams,
            release_streams,
            start_s,
            start_s + float(window_s),
            min_events=int(min_events),
        )
        if diagnostic is not None:
            windows.append(diagnostic)
        start_s += float(window_s)

    return {
        "algorithm": "V9 regime diagnostics",
        "input": str(input_path),
        "window_s": float(window_s),
        "min_events": int(min_events),
        "recording_duration_s": float(total_end_s),
        "trajectory_count": int(trajectory_count),
        "event_count": int(event_count),
        "movement_stream_count": int(len(by_stream)),
        "source_files": [str(item) for item in source_files],
        "recording_start_timestamp_ms": (
            float(recording_start_ms)
            if recording_start_ms is not None
            else None
        ),
        "analysis_base_timestamp_ms": float(analysis_base_ms),
        "windows": windows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect every hourly V9 regime window without changing "
            "production regime selection."
        )
    )
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("v9_regime_diagnostics.json"),
    )
    parser.add_argument("--window-s", type=float, default=WINDOW_S)
    parser.add_argument("--min-events", type=int, default=MIN_EVENTS)
    args = parser.parse_args()

    result = diagnose_path(
        args.input,
        window_s=args.window_s,
        min_events=args.min_events,
    )
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("[V9] regime diagnostics complete")
    print("  input:", args.input)
    print("  output:", args.output)
    print("  windows:", len(result["windows"]))
    for window in result["windows"]:
        selected = window["selected_model"]
        print(
            "  "
            f"T+{window['start_s']:.0f}-{window['end_s']:.0f}s: "
            f"period={window['period_s']:.3f}s, "
            f"events={window['event_count']}, "
            f"streams={window['active_stream_count']}, "
            f"k={window['selected_phase_count']}, "
            f"coherence={selected['boundary_coherence']:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
