from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from typing import Sequence

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks, peak_widths

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CycleCandidate:
    period_seconds: float
    strength: float
    peak_width_seconds: float
    stability: float
    repetitions: int
    score: float

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


@dataclass(frozen=True)
class CycleEstimate:
    cycle_seconds: float
    confidence: float
    candidate_periods: tuple[CycleCandidate, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "cycle_seconds": self.cycle_seconds,
            "confidence": self.confidence,
            "candidate_periods": [candidate.to_dict() for candidate in self.candidate_periods],
        }


class CycleEstimator:
    """Estimate a recurring traffic cycle from a 1-D traffic-flow signal."""

    def __init__(
        self,
        *,
        min_period_seconds: float = 20.0,
        max_period_seconds: float = 180.0,
        peak_distance_seconds: float = 12.0,
        smoothing_sigma: float = 1.2,
        max_candidates: int = 8,
    ) -> None:
        if min_period_seconds <= 0 or max_period_seconds <= min_period_seconds:
            raise ValueError("invalid cycle search range")
        self.min_period_seconds = min_period_seconds
        self.max_period_seconds = max_period_seconds
        self.peak_distance_seconds = peak_distance_seconds
        self.smoothing_sigma = smoothing_sigma
        self.max_candidates = max_candidates

    def estimate(
        self,
        signal: Sequence[float] | np.ndarray,
        *,
        sampling_seconds: float,
    ) -> CycleEstimate:
        values = np.asarray(signal, dtype=float)
        if sampling_seconds <= 0:
            raise ValueError("sampling_seconds must be positive")
        if values.ndim != 1 or values.size < 8:
            raise ValueError("signal must be a one-dimensional sequence with at least 8 samples")

        values = np.nan_to_num(values, nan=0.0)
        values = gaussian_filter1d(values, sigma=self.smoothing_sigma)
        centered = values - values.mean()
        autocorr = np.correlate(centered, centered, mode="full")[len(centered) - 1 :]
        if autocorr[0] <= 0:
            raise RuntimeError("traffic signal has zero variance")
        normalized = autocorr / autocorr[0]
        lags = np.arange(normalized.size) * sampling_seconds

        mask = (lags >= self.min_period_seconds) & (lags <= self.max_period_seconds)
        if not mask.any():
            raise RuntimeError("cycle search range is outside the observed signal")
        local = normalized[mask]
        local_lags = lags[mask]
        if float(local.max()) <= 0:
            raise RuntimeError("autocorrelation contains no positive cycle candidate")

        peaks, properties = find_peaks(
            local,
            distance=max(1, int(self.peak_distance_seconds / sampling_seconds)),
            prominence=max(0.01, float(local.max()) * 0.05),
        )
        if peaks.size == 0:
            peaks = np.array([int(np.argmax(local))])
            properties = {"prominences": np.array([float(local.max())])}

        widths = peak_widths(local, peaks, rel_height=0.5)[0] * sampling_seconds
        candidates: list[CycleCandidate] = []
        total_duration = len(values) * sampling_seconds

        for peak_index, width in zip(peaks, widths):
            period = float(local_lags[peak_index])
            strength = float(local[peak_index])
            stability = self._estimate_stability(values, sampling_seconds, period)
            repetitions = max(1, int(total_duration // period))
            width_ratio = min(1.0, max(0.0, float(width) / period))
            repetition_score = min(1.0, repetitions / 4.0)
            # Autocorrelation strength is the primary evidence for a true period.
            # Width, stability and repetitions refine that evidence instead of
            # allowing a weak autocorrelation peak to dominate the selection.
            score = (
                0.70 * strength
                + 0.10 * width_ratio
                + 0.10 * stability
                + 0.10 * repetition_score
            )
            candidates.append(
                CycleCandidate(
                    period_seconds=round(period, 2),
                    strength=round(strength, 4),
                    peak_width_seconds=round(float(width), 2),
                    stability=round(stability, 4),
                    repetitions=repetitions,
                    score=round(float(score), 4),
                )
            )

        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        candidates = candidates[: self.max_candidates]
        weights = np.asarray([candidate.score for candidate in candidates], dtype=float)
        confidence = float(weights[0] / weights.sum()) if weights.sum() else 0.0
        best = candidates[0]

        LOGGER.info(
            "cycle estimate: period=%.1fs confidence=%.3f candidates=%s",
            best.period_seconds,
            confidence,
            [candidate.to_dict() for candidate in candidates],
        )
        return CycleEstimate(
            cycle_seconds=best.period_seconds,
            confidence=round(confidence, 4),
            candidate_periods=tuple(candidates),
        )

    def _estimate_stability(
        self,
        values: np.ndarray,
        sampling_seconds: float,
        period_seconds: float,
    ) -> float:
        if len(values) < 16:
            return 0.5
        half = len(values) // 2
        periods = []
        for part in (values[:half], values[-half:]):
            centered = part - part.mean()
            ac = np.correlate(centered, centered, mode="full")[len(centered) - 1 :]
            if ac[0] <= 0:
                continue
            lags = np.arange(len(ac)) * sampling_seconds
            mask = (lags >= self.min_period_seconds) & (lags <= self.max_period_seconds)
            if not mask.any():
                continue
            local = ac[mask] / ac[0]
            idx = int(np.argmax(local))
            periods.append(float(lags[mask][idx]))
        if len(periods) != 2:
            return 0.5
        error = abs(periods[0] - periods[1]) / max(period_seconds, 1.0)
        return max(0.0, 1.0 - min(1.0, error))
