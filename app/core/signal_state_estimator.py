from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping, Sequence
import json

import pandas as pd

from app.core.models import TrafficWindow
from app.core.phase_discovery import APPROACHES, Phase, PhaseDiscoveryResult
from app.core.preprocessing import load_trajectory_file, trajectories_to_frame

DEFAULT_YELLOW_DURATION_SECONDS = 2.0


class SignalState(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ApproachState:
    approach: str
    state: SignalState
    confidence: float
    phase_id: int | None
    evidence_weight: float

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


@dataclass(frozen=True)
class SignalStateResult:
    timestamp_s: float
    cycle_phase_s: float
    phase_id: int | None
    transition: bool
    phase_confidence: float
    approaches: tuple[ApproachState, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp_s": self.timestamp_s,
            "cycle_phase_s": self.cycle_phase_s,
            "phase_id": self.phase_id,
            "transition": self.transition,
            "phase_confidence": self.phase_confidence,
            "approaches": [state.to_dict() for state in self.approaches],
        }


class SignalStateEstimator:
    """Reconstruct per-approach signal states from an inferred phase model."""

    def __init__(
        self,
        phase_model: PhaseDiscoveryResult,
        *,
        recent_window_s: float = 12.0,
        min_evidence_weight: float = 1.0,
        min_confidence: float = 0.55,
        stop_weight: float = 1.0,
        yellow_duration_seconds: float = DEFAULT_YELLOW_DURATION_SECONDS,
    ) -> None:
        if phase_model.cycle_seconds <= 0:
            raise ValueError("phase model cycle must be positive")
        if recent_window_s <= 0:
            raise ValueError("recent_window_s must be positive")
        if min_evidence_weight <= 0:
            raise ValueError("min_evidence_weight must be positive")
        if not 0 < min_confidence <= 1:
            raise ValueError("min_confidence must be in (0, 1]")
        if stop_weight <= 0:
            raise ValueError("stop_weight must be positive")
        if yellow_duration_seconds < 0:
            raise ValueError("yellow_duration_seconds must be non-negative")
        if yellow_duration_seconds >= phase_model.cycle_seconds:
            raise ValueError("yellow_duration_seconds must be shorter than the cycle")

        self.phase_model = phase_model
        self.recent_window_s = recent_window_s
        self.min_evidence_weight = min_evidence_weight
        self.min_confidence = min_confidence
        self.stop_weight = stop_weight
        self.yellow_duration_seconds = yellow_duration_seconds

    def estimate(
        self,
        current_time_s: float,
        traffic: pd.DataFrame | Iterable[TrafficWindow],
    ) -> SignalStateResult:
        if current_time_s < 0:
            raise ValueError("current_time_s must be non-negative")

        cycle = self.phase_model.cycle_seconds
        phase_position = current_time_s % cycle
        phase, transition, source_phase = self._phase_at(phase_position)
        recent = self._recent_traffic(traffic, current_time_s)
        evidence = self._evidence_by_approach(recent)

        approach_states: list[ApproachState] = []
        for approach in APPROACHES:
            released, stopped, flow = evidence.get(approach, (0.0, 0.0, 0.0))
            evidence_weight = released + self.stop_weight * stopped
            observed = max(flow, stopped, released)

            if source_phase is None or observed < self.min_evidence_weight:
                state = SignalState.UNKNOWN
                confidence = 0.0 if observed == 0 else min(0.5, observed / (observed + 2.0))
            else:
                phase_confidence = max(0.0, min(1.0, source_phase.confidence))
                evidence_confidence = min(
                    1.0,
                    evidence_weight / (evidence_weight + self.min_evidence_weight),
                )
                confidence = phase_confidence * evidence_confidence

                if confidence < self.min_confidence:
                    state = SignalState.UNKNOWN
                elif transition:
                    state = (
                        SignalState.YELLOW
                        if approach in source_phase.active_approaches
                        else SignalState.RED
                    )
                elif approach in source_phase.active_approaches:
                    state = (
                        SignalState.GREEN
                        if released > 0 and released >= self.stop_weight * stopped
                        else SignalState.UNKNOWN
                    )
                else:
                    state = SignalState.RED if stopped > 0 or flow > 0 else SignalState.UNKNOWN

            approach_states.append(
                ApproachState(
                    approach=approach,
                    state=state,
                    confidence=round(float(confidence), 4),
                    phase_id=phase.phase_id if phase is not None else None,
                    evidence_weight=round(float(evidence_weight), 4),
                )
            )

        return SignalStateResult(
            timestamp_s=float(current_time_s),
            cycle_phase_s=round(float(phase_position), 3),
            phase_id=phase.phase_id if phase is not None else None,
            transition=transition,
            phase_confidence=round(float(source_phase.confidence), 4) if source_phase else 0.0,
            approaches=tuple(approach_states),
        )

    def estimate_playback(self, path: Path, timestamps_s: Sequence[float]) -> list[SignalStateResult]:
        trajectories = load_trajectory_file(path)
        frame = trajectories_to_frame(trajectories)
        return [self.estimate(timestamp_s, frame) for timestamp_s in timestamps_s]

    def _phase_at(self, phase_position: float) -> tuple[Phase | None, bool, Phase | None]:
        phases = self.phase_model.phases
        if not phases:
            return None, True, None

        for index, phase in enumerate(phases):
            start = phase.phase_start % self.phase_model.cycle_seconds
            end = phase.phase_end % self.phase_model.cycle_seconds
            if self._in_interval(phase_position, start, end):
                next_phase = phases[(index + 1) % len(phases)] if len(phases) > 1 else None
                if next_phase is None:
                    transition = self._ending_yellow(phase_position, end)
                else:
                    next_start = next_phase.phase_start % self.phase_model.cycle_seconds
                    has_gap = abs((next_start - end) % self.phase_model.cycle_seconds) > 1e-9
                    transition = not has_gap and self._ending_yellow(phase_position, end)
                return phase, transition, phase

            next_phase = phases[(index + 1) % len(phases)] if len(phases) > 1 else None
            if next_phase is not None:
                next_start = next_phase.phase_start % self.phase_model.cycle_seconds
                if self._before_next_phase(phase_position, next_start):
                    return phase, True, phase

        return None, True, None

    def _in_interval(self, value: float, start: float, end: float) -> bool:
        if start <= end:
            return start <= value < end
        return value >= start or value < end

    def _ending_yellow(self, value: float, end: float) -> bool:
        if self.yellow_duration_seconds == 0:
            return False
        distance_to_end = (end - value) % self.phase_model.cycle_seconds
        return 0 < distance_to_end <= self.yellow_duration_seconds

    def _before_next_phase(self, value: float, next_start: float) -> bool:
        if self.yellow_duration_seconds == 0:
            return False
        distance = (next_start - value) % self.phase_model.cycle_seconds
        return 0 < distance <= self.yellow_duration_seconds

    def _recent_traffic(self, traffic: pd.DataFrame | Iterable[TrafficWindow], current_time_s: float):
        lower = current_time_s - self.recent_window_s
        if isinstance(traffic, pd.DataFrame):
            if traffic.empty:
                return traffic
            return traffic[(traffic["t_s"] >= lower) & (traffic["t_s"] <= current_time_s)]
        return [window for window in traffic if lower <= window.start_s <= current_time_s]

    def _evidence_by_approach(
        self,
        traffic: pd.DataFrame | Iterable[TrafficWindow],
    ) -> Mapping[str, tuple[float, float, float]]:
        evidence: dict[str, list[float]] = {approach: [0.0, 0.0, 0.0] for approach in APPROACHES}
        if isinstance(traffic, pd.DataFrame):
            for _, row in traffic.iterrows():
                approach = str(row.get("zone_in", ""))
                if approach not in evidence:
                    continue
                evidence[approach][0] += float(row.get("release_weight", 0.0) or 0.0)
                evidence[approach][1] += float(bool(row.get("stopped", False)))
                evidence[approach][2] += 1.0
        else:
            for window in traffic:
                approach = str(window.movement).split("->", 1)[0]
                if approach not in evidence:
                    continue
                evidence[approach][0] += float(window.release_weight)
                evidence[approach][1] += float(window.stopped_count)
                evidence[approach][2] += float(window.flow)
        return {key: tuple(value) for key, value in evidence.items()}


def result_to_json(result: SignalStateResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


__all__ = [
    "DEFAULT_YELLOW_DURATION_SECONDS",
    "ApproachState",
    "SignalState",
    "SignalStateEstimator",
    "SignalStateResult",
    "result_to_json",
]
