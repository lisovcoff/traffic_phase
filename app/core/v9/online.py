from __future__ import annotations
import math
from typing import Optional
import numpy as np

from .fit import anonymous_phase_name

class OnlinePhaseTracker:
    """Causal short-term phase tracking against a learned anonymous baseline."""
    def __init__(
        self,
        result: dict[str, object],
        *,
        lookback_s: Optional[float] = None,
        shift_step_s: float = 1.0,
    ):
        self.period = float(result["schedule"]["period_s"])
        self.k = int(result["schedule"]["phase_count"])
        self.analysis_base_ms = float(result["analysis_base_timestamp_ms"])
        self.baseline = [
            tuple(segment)
            for segment in result["schedule"]["baseline_segments"]
        ]
        rows = result["schedule"].get("stream_activity_by_phase", [])
        self.stream_names = [row["stream"] for row in rows]
        self.probs = np.zeros(
            (self.k, len(self.stream_names)),
            dtype=float,
        )
        for j, row in enumerate(rows):
            values = row.get(
                "event_probability_by_phase",
                {},
            )
            for z in range(self.k):
                self.probs[z, j] = float(
                    values.get(
                        anonymous_phase_name(z),
                        0.05,
                    )
                )
        self.index = {
            stream: index
            for index, stream in enumerate(self.stream_names)
        }
        self.events: list[tuple[float, str]] = []
        self.lookback_s = float(
            lookback_s
            if lookback_s is not None
            else min(60.0, 0.5 * self.period)
        )
        self.shift_step_s = max(
            0.25,
            float(shift_step_s),
        )

    def observe(
        self,
        timestamp_ms: int,
        stream: str,
    ) -> None:
        relative = (
            float(timestamp_ms)
            - self.analysis_base_ms
        ) / 1000.0
        self.events.append((
            relative,
            str(stream),
        ))
        cutoff = relative - 2.0 * self.lookback_s
        self.events = [
            item
            for item in self.events
            if item[0] >= cutoff
        ]

    def infer(
        self,
        timestamp_ms: int,
    ) -> dict[str, object]:
        rel_now = (
            float(timestamp_ms)
            - self.analysis_base_ms
        ) / 1000.0
        recent = [
            item
            for item in self.events
            if rel_now - self.lookback_s
            <= item[0]
            <= rel_now
        ]

        if not recent:
            return {
                "timestamp_ms": timestamp_ms,
                "phase": None,
                "phase_index": None,
                "schedule_shift_s": 0.0,
                "confidence": 0.0,
                "status": "WARMUP",
                "recent_event_count": 0,
            }

        max_shift = min(
            0.20 * self.period,
            max(6.0, 0.35 * self.lookback_s),
        )
        shifts = np.arange(
            -max_shift,
            max_shift + 1e-9,
            self.shift_step_s,
        )
        background = (
            np.maximum(
                self.probs.mean(axis=0),
                0.01,
            )
            if self.probs.size
            else np.array([])
        )
        scores = []

        for shift in shifts:
            values = []
            for t, stream in recent:
                j = self.index.get(stream)
                if j is None:
                    continue
                position = (
                    t - float(shift)
                ) % self.period
                state = 0
                for a, b, z in self.baseline:
                    aa = float(a) % self.period
                    bb = float(b) % self.period
                    inside = (
                        aa <= position < bb
                        if aa <= bb
                        else (
                            position >= aa
                            or position < bb
                        )
                    )
                    if inside:
                        state = int(z)
                        break

                probability = float(
                    np.clip(
                        self.probs[state, j],
                        0.01,
                        0.99,
                    )
                )
                background_rate = float(
                    np.clip(
                        background[j],
                        0.01,
                        0.99,
                    )
                )
                values.append(
                    math.log(
                        probability
                        / background_rate
                    )
                )

            score = (
                float(np.mean(values))
                if values
                else 0.0
            )
            score -= (
                0.18
                * (
                    float(shift)
                    / max(
                        1.0,
                        0.10 * self.period,
                    )
                ) ** 2
            )
            scores.append(score)

        scores = np.asarray(scores, dtype=float)
        best_index = int(
            np.argmax(scores)
        ) if len(scores) else 0
        shift = (
            float(shifts[best_index])
            if len(shifts)
            else 0.0
        )
        position = (
            rel_now - shift
        ) % self.period

        state = (
            int(self.baseline[-1][2])
            if self.baseline
            else 0
        )
        for a, b, z in self.baseline:
            aa = float(a) % self.period
            bb = float(b) % self.period
            inside = (
                aa <= position < bb
                if aa <= bb
                else position >= aa or position < bb
            )
            if inside:
                state = int(z)
                break

        if len(scores):
            exponent = np.exp(
                scores - float(np.max(scores))
            )
            probabilities = exponent / np.sum(exponent)
            confidence = float(
                np.max(probabilities)
            )
        else:
            confidence = 0.0

        limit = max(
            2.0,
            0.03 * self.period,
        )
        interpretation = (
            "temporary_phase_extension_or_delay"
            if shift > limit
            else (
                "temporary_phase_advance"
                if shift < -limit
                else "near_baseline"
            )
        )
        return {
            "timestamp_ms": int(timestamp_ms),
            "relative_time_s": float(rel_now),
            "phase": anonymous_phase_name(state),
            "phase_index": state,
            "cycle_position_s": round(
                position,
                3,
            ),
            "schedule_shift_s": round(
                shift,
                3,
            ),
            "interpretation": interpretation,
            "confidence": round(
                confidence,
                4,
            ),
            "status": (
                "SYNCHRONIZED"
                if confidence >= 0.55
                else "WARMUP"
            ),
            "recent_event_count": len(recent),
        }
