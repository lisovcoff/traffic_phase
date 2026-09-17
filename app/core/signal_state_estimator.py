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
    """Turn the binary phase hypothesis into GREEN/YELLOW/RED states.

    Phase confidence is reported as a diagnostic value, but it is not used to replace
    a valid phase with four UNKNOWN states. Once the binary phase model has selected
    N/S or E/W as the active pair, the opposite pair is explicitly RED.
    """

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

    def estimate(self, current_time_s: float, traffic: pd.DataFrame | Iterable[TrafficWindow]) -> SignalStateResult:
        if current_time_s < 0:
            raise ValueError("current_time_s must be non-negative")

        cycle = self.phase_model.cycle_seconds
        phase_position = current_time_s % cycle
        phase, transition, source_phase = self._phase_at(phase_position)
        recent = self._recent_traffic(traffic, current_time_s)
        evidence = self._evidence_by_approach(recent)

        phase_confidence = (
            max(0.0, min(1.0, float(source_phase.confidence)))
            if source_phase is not None else 0.0
        )

        approach_states: list[ApproachState] = []
        for approach in APPROACHES:
            flow, _mean_wait, stopped_ratio, _green_evidence, _red_evidence = evidence.get(
                approach, (0.0, 0.0, 0.0, 0.0, 0.0)
            )
            evidence_weight = flow + self.stop_weight * stopped_ratio * flow

            if source_phase is None:
                state = SignalState.UNKNOWN
            elif transition:
                state = SignalState.YELLOW if approach in source_phase.active_approaches else SignalState.RED
            elif approach in source_phase.active_approaches:
                state = SignalState.GREEN
            else:
                state = SignalState.RED

            approach_states.append(
                ApproachState(
                    approach=approach,
                    state=state,
                    confidence=round(float(phase_confidence), 4),
                    phase_id=phase.phase_id if phase is not None else None,
                    evidence_weight=round(float(evidence_weight), 4),
                )
            )

        return SignalStateResult(
            timestamp_s=float(current_time_s),
            cycle_phase_s=round(float(phase_position), 3),
            phase_id=phase.phase_id if phase is not None else None,
            transition=transition,
            phase_confidence=round(phase_confidence, 4),
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
                    transition = self._ending_yellow(phase_position, end) or self._before_next_phase(phase_position, next_start)
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
    ) -> Mapping[str, tuple[float, float, float, float, float]]:
        evidence: dict[str, list[float]] = {
            approach: [0.0, 0.0, 0.0, 0.0, 0.0] for approach in APPROACHES
        }
        if isinstance(traffic, pd.DataFrame):
            for approach in APPROACHES:
                selected = traffic[traffic["zone_in"].astype(str) == approach]
                if selected.empty:
                    continue
                flow = float(len(selected))
                waits = pd.to_numeric(selected.get("wait_s"), errors="coerce").fillna(0.0)
                stopped = pd.to_numeric(selected.get("stopped"), errors="coerce").fillna(0.0)
                mean_wait = float(waits.mean())
                stopped_ratio = float(stopped.mean())
                flow_presence = min(1.0, flow / 3.0)
                delay_free = 1.0 - min(1.0, mean_wait / 20.0)
                green_evidence = flow_presence * (0.60 + 0.25 * delay_free + 0.15 * (1.0 - stopped_ratio))
                wait_pressure = min(1.0, mean_wait / 15.0)
                red_evidence = flow_presence * (0.40 * wait_pressure + 0.60 * stopped_ratio)
                evidence[approach] = [
                    flow,
                    mean_wait,
                    stopped_ratio,
                    float(max(0.0, min(1.0, green_evidence))),
                    float(max(0.0, min(1.0, red_evidence))),
                ]
        else:
            for window in traffic:
                approach = str(window.movement).split("->", 1)[0]
                if approach not in evidence:
                    continue
                flow = float(window.flow)
                mean_wait = float(window.mean_wait or 0.0)
                stopped_ratio = min(1.0, float(window.stopped_count) / max(flow, 1.0))
                flow_presence = min(1.0, flow / 3.0)
                delay_free = 1.0 - min(1.0, mean_wait / 20.0)
                green_evidence = flow_presence * (0.60 + 0.25 * delay_free + 0.15 * (1.0 - stopped_ratio))
                wait_pressure = min(1.0, mean_wait / 15.0)
                red_evidence = flow_presence * (0.40 * wait_pressure + 0.60 * stopped_ratio)
                evidence[approach][0] += flow
                evidence[approach][1] += mean_wait * flow
                evidence[approach][2] += stopped_ratio * flow
                evidence[approach][3] = max(evidence[approach][3], green_evidence)
                evidence[approach][4] = max(evidence[approach][4], red_evidence)
            for _approach, values in evidence.items():
                flow = values[0]
                if flow > 0:
                    values[1] /= flow
                    values[2] /= flow
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
