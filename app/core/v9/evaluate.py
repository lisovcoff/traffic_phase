from __future__ import annotations
import itertools
import json
from pathlib import Path
import numpy as np

from .fit import anonymous_phase_name

def _read_marks(path: Path):
    payload = json.loads(
        path.read_text(encoding="utf-8")
    )
    return [
        (
            float(item["timestamp_ms"]),
            str(item["kind"]),
        )
        for item in payload.get("marks", [])
    ]

def _state_at_time(t: float, segments):
    for a, b, z in segments:
        if float(a) <= t < float(b):
            return int(z)
    if segments:
        return int(
            segments[0][2]
            if t < segments[0][0]
            else segments[-1][2]
        )
    return 0

def evaluate(
    segments,
    period: float,
    base_ms: float,
    marks_path: Path,
    step_s: float = 0.25,
):
    marks = _read_marks(marks_path)
    if len(marks) < 2 or not segments:
        return {"status": "insufficient_marks"}

    relative = [
        (
            (timestamp - base_ms) / 1000.0,
            label,
        )
        for timestamp, label in marks
    ]
    labels = list(
        dict.fromkeys(
            label
            for _, label in relative
        )
    )
    end = min(
        float(segments[-1][1]),
        relative[-1][0],
    )
    start = max(
        0.0,
        relative[0][0],
    )
    if end <= start or len(labels) < 2:
        return {"status": "insufficient_overlap"}

    timestamps = np.arange(
        start,
        end,
        step_s,
    )
    ground_truth = []
    for t in timestamps:
        label = labels[-1]
        for i in range(len(relative) - 1):
            if (
                relative[i][0]
                <= t
                < relative[i + 1][0]
            ):
                label = relative[i][1]
                break
        ground_truth.append(label)

    predicted = [
        _state_at_time(
            float(t),
            segments,
        )
        for t in timestamps
    ]
    decoded_names = [
        anonymous_phase_name(i)
        for i in range(
            max(predicted) + 1
        )
    ]

    best = 0.0
    best_mapping = {}
    for permutation in itertools.permutations(
        labels,
        r=min(
            len(labels),
            len(decoded_names),
        ),
    ):
        mapping = dict(
            zip(
                decoded_names,
                permutation,
            )
        )
        mapped = [
            mapping.get(
                anonymous_phase_name(
                    int(state)
                ),
                None,
            )
            for state in predicted
        ]
        score = float(
            np.mean(
                [
                    left == right
                    for left, right
                    in zip(
                        mapped,
                        ground_truth,
                    )
                ]
            )
        )
        if score > best:
            best = score
            best_mapping = mapping

    return {
        "status": "ok",
        "continuous_accuracy_percent": 100.0 * best,
        "manual_label_count": len(labels),
        "decoded_phase_count": len(decoded_names),
        "evaluated_overlap_s": [
            start,
            end,
        ],
        "evaluation_mapping_only": best_mapping,
    }
