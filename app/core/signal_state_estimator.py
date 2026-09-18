from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import json
import math
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from app.core.models import EventType, TrajectoryEvent
from app.core.phase_discovery import APPROACHES
from app.core.preprocessing import load_trajectory_file


DEFAULT_YELLOW_DURATION_SECONDS = 2.0
DEFAULT_RECENT_WINDOW_SECONDS = 12.0
DEFAULT_MIN_PHASE_CONFIDENCE = 0.20
DEFAULT_MIN_TRAFFIC_CONFIDENCE = 0.12
DEFAULT_CONFLICT_PERSISTENCE_SECONDS = 3.0


class SignalState(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"
    RED_YELLOW = "RED_YELLOW"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ApproachState:
    approach: str
    state: SignalState
    probability: float = 0.0
    confidence: float = 0.0
    phase_id: int | None = None
    phase_confidence: float = 0.0
    traffic_evidence_confidence: float = 0.0
    evidence_weight: float = 0.0
    supporting_event_count: int = 0
    contradictory_event_count: int = 0

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
    traffic_evidence_confidence: float = 0.0
    approaches: tuple[ApproachState, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp_s": self.timestamp_s,
            "cycle_phase_s": self.cycle_phase_s,
            "phase_id": self.phase_id,
            "transition": self.transition,
            "phase_confidence": self.phase_confidence,
            "traffic_evidence_confidence": self.traffic_evidence_confidence,
            "approaches": [state.to_dict() for state in self.approaches],
        }


class SignalStateEstimator:
    """Probabilistic reconstruction of the current signal state.

    The phase model supplies the structural prior. RELEASE/CROSSING events
    supply recent traffic evidence. STOP, APPROACH and wait/stay are never
    used as direct RED evidence.

    Traffic evidence changes probability/confidence but does not instantly
    override a phase. This is an intentionally small non-HMM persistence
    mechanism: a conflicting event is observed, but the phase state remains
    stable until a sustained contradiction can matter at a later integration
    point.
    """

    def __init__(
        self,
        phase_model: object,
        *,
        recent_window_s: float = DEFAULT_RECENT_WINDOW_SECONDS,
        min_phase_confidence: float = DEFAULT_MIN_PHASE_CONFIDENCE,
        min_traffic_confidence: float = DEFAULT_MIN_TRAFFIC_CONFIDENCE,
        yellow_duration_seconds: float = DEFAULT_YELLOW_DURATION_SECONDS,
        conflict_persistence_seconds: float = DEFAULT_CONFLICT_PERSISTENCE_SECONDS,
        event_origin_ms: int | None = None,
    ) -> None:
        cycle = float(getattr(phase_model, "cycle_seconds", 0.0))
        if cycle <= 0:
            raise ValueError("phase model cycle must be positive")
        if recent_window_s <= 0:
            raise ValueError("recent_window_s must be positive")
        if not 0 < min_phase_confidence <= 1:
            raise ValueError("min_phase_confidence must be in (0, 1]")
        if not 0 <= min_traffic_confidence <= 1:
            raise ValueError("min_traffic_confidence must be in [0, 1]")
        if yellow_duration_seconds < 0 or yellow_duration_seconds >= cycle:
            raise ValueError("invalid yellow_duration_seconds")
        if conflict_persistence_seconds < 0:
            raise ValueError("conflict_persistence_seconds must be non-negative")

        self.phase_model = phase_model
        self.recent_window_s = float(recent_window_s)
        self.min_phase_confidence = float(min_phase_confidence)
        self.min_traffic_confidence = float(min_traffic_confidence)
        self.yellow_duration_seconds = float(yellow_duration_seconds)
        self.conflict_persistence_seconds = float(conflict_persistence_seconds)
        self.event_origin_ms = event_origin_ms

    def estimate(
        self,
        current_time_s: float,
        events: Sequence[TrajectoryEvent],
    ) -> SignalStateResult:
        if current_time_s < 0:
            raise ValueError("current_time_s must be non-negative")

        events = list(events)
        origin_ms = self._origin_ms(events)
        position = current_time_s % self.phase_model.cycle_seconds
        phase = self._phase_at(position)
        phase_confidence = self._phase_confidence(phase)
        recent = self._recent_events(events, current_time_s, origin_ms)
        traffic_confidence = self._traffic_confidence(recent)
        transition_kind = self._transition_kind(position, phase)

        active = set(getattr(phase, "active_approaches", ())) if phase else set()
        evidence = self._event_evidence(recent, active)

        states: list[ApproachState] = []
        for approach in APPROACHES:
            support, supporting, contradictory = evidence[approach]
            traffic_conf = self._approach_traffic_confidence(
                support,
                supporting,
                contradictory,
            )
            phase_active = approach in active

            if phase is None or phase_confidence < self.min_phase_confidence:
                state = SignalState.UNKNOWN
                probability = max(0.0, min(1.0, traffic_conf))
            else:
                state, probability = self._state_from_evidence(
                    phase_active=phase_active,
                    transition_kind=transition_kind,
                    support=support,
                    phase_confidence=phase_confidence,
                    traffic_confidence=traffic_conf,
                )

                if (
                    contradictory > 0
                    and self.conflict_persistence_seconds > 0
                    and self._conflict_is_short(
                        recent,
                        approach,
                        current_time_s,
                        origin_ms,
                    )
                    and transition_kind is None
                ):
                    # Keep the phase state; only confidence is reduced.
                    probability = min(probability, 0.55)
                    state = SignalState.GREEN if phase_active else SignalState.RED

            states.append(
                ApproachState(
                    approach=approach,
                    state=state,
                    probability=round(float(probability), 4),
                    confidence=round(float(probability), 4),
                    phase_id=getattr(phase, "phase_id", None),
                    phase_confidence=round(phase_confidence, 4),
                    traffic_evidence_confidence=round(traffic_conf, 4),
                    evidence_weight=round(support, 4),
                    supporting_event_count=supporting,
                    contradictory_event_count=contradictory,
                )
            )

        return SignalStateResult(
            timestamp_s=float(current_time_s),
            cycle_phase_s=round(float(position), 3),
            phase_id=getattr(phase, "phase_id", None),
            transition=transition_kind is not None,
            phase_confidence=round(phase_confidence, 4),
            traffic_evidence_confidence=round(traffic_confidence, 4),
            approaches=tuple(states),
        )

    def estimate_playback(
        self,
        path: Path,
        timestamps_s: Sequence[float],
    ) -> list[SignalStateResult]:
        trajectories = load_trajectory_file(path)
        events: list[TrajectoryEvent] = []
        from app.core.trajectory_events import extract_trajectory_events
        from app.core.trajectory_geometry import TrajectoryGeometry

        for trajectory in trajectories:
            events.extend(
                extract_trajectory_events(
                    trajectory,
                    TrajectoryGeometry(trajectory.detections),
                )
            )

        origin = min((event.timestamp_ms for event in events), default=None)
        estimator = SignalStateEstimator(
            self.phase_model,
            recent_window_s=self.recent_window_s,
            min_phase_confidence=self.min_phase_confidence,
            min_traffic_confidence=self.min_traffic_confidence,
            yellow_duration_seconds=self.yellow_duration_seconds,
            conflict_persistence_seconds=self.conflict_persistence_seconds,
            event_origin_ms=origin,
        )
        return [estimator.estimate(timestamp_s, events) for timestamp_s in timestamps_s]

    def _phase_at(self, position: float):
        for phase in tuple(getattr(self.phase_model, "phases", ())):
            start = float(phase.phase_start) % self.phase_model.cycle_seconds
            end = float(phase.phase_end) % self.phase_model.cycle_seconds
            if self._in_interval(position, start, end):
                return phase
        return None

    def _phase_confidence(self, phase) -> float:
        return (
            max(0.0, min(1.0, float(getattr(phase, "confidence", 0.0))))
            if phase is not None
            else 0.0
        )

    @staticmethod
    def _in_interval(value: float, start: float, end: float) -> bool:
        return start <= value < end if start <= end else value >= start or value < end

    def _transition_kind(self, position: float, phase) -> SignalState | None:
        if phase is None or self.yellow_duration_seconds == 0:
            return None
        start = float(phase.phase_start) % self.phase_model.cycle_seconds
        end = float(phase.phase_end) % self.phase_model.cycle_seconds
        distance_to_end = (end - position) % self.phase_model.cycle_seconds
        if 0 < distance_to_end <= self.yellow_duration_seconds:
            return SignalState.YELLOW
        distance_from_start = (position - start) % self.phase_model.cycle_seconds
        if 0 <= distance_from_start <= self.yellow_duration_seconds:
            return SignalState.RED_YELLOW
        return None

    def _origin_ms(self, events: Sequence[TrajectoryEvent]) -> int | None:
        # current_time_s is a timeline coordinate. Playback explicitly
        # supplies event_origin_ms when raw timestamps must be rebased.
        if self.event_origin_ms is not None:
            return self.event_origin_ms
        return min((event.timestamp_ms for event in events), default=None)

    def _recent_events(
        self,
        events: Sequence[TrajectoryEvent],
        current_time_s: float,
        origin_ms: int | None,
    ) -> list[TrajectoryEvent]:
        if origin_ms is None:
            return []
        now_ms = origin_ms + int(current_time_s * 1000)
        lower_ms = now_ms - int(self.recent_window_s * 1000)
        return [
            event
            for event in events
            if lower_ms <= event.timestamp_ms <= now_ms
            and event.event_type in {EventType.RELEASE, EventType.CROSSING}
        ]

    def _event_evidence(
        self,
        events: Sequence[TrajectoryEvent],
        active: set[str],
    ) -> dict[str, tuple[float, int, int]]:
        evidence = {approach: [0.0, 0, 0] for approach in APPROACHES}
        for event in events:
            if event.approach not in evidence:
                continue
            weight = (
                1.0 if event.event_type == EventType.RELEASE else 0.5
            ) * max(0.0, min(1.0, float(event.confidence)))
            evidence[event.approach][0] += weight
            if event.approach in active:
                evidence[event.approach][1] += 1
            else:
                evidence[event.approach][2] += 1

        # For each approach, events from its own group support it; events from
        # the opposing active group are contradictory evidence. A phase model
        # with no active group yields no direct signal-state conclusion.
        if active:
            for approach in APPROACHES:
                if approach in active:
                    evidence[approach][1] = sum(
                        1 for event in events if event.approach in active
                    )
                    evidence[approach][2] = sum(
                        1 for event in events if event.approach not in active
                    )
                else:
                    evidence[approach][1] = sum(
                        1 for event in events if event.approach not in active
                    )
                    evidence[approach][2] = sum(
                        1 for event in events if event.approach in active
                    )
        return {key: tuple(value) for key, value in evidence.items()}

    def _approach_traffic_confidence(
        self,
        support: float,
        supporting: int,
        contradictory: int,
    ) -> float:
        total = supporting + contradictory
        if total == 0:
            return 0.0
        density = min(1.0, support / 2.0)
        consistency = supporting / total
        return max(0.0, min(1.0, 0.65 * density + 0.35 * consistency))

    def _traffic_confidence(
        self,
        events: Sequence[TrajectoryEvent],
    ) -> float:
        if not events:
            return 0.0
        weight = sum(
            (
                1.0 if event.event_type == EventType.RELEASE else 0.5
            ) * max(0.0, min(1.0, float(event.confidence)))
            for event in events
        )
        return max(0.0, min(1.0, weight / 4.0))

    def _state_from_evidence(
        self,
        *,
        phase_active: bool,
        transition_kind: SignalState | None,
        support: float,
        phase_confidence: float,
        traffic_confidence: float,
    ) -> tuple[SignalState, float]:
        if transition_kind == SignalState.YELLOW:
            state = SignalState.YELLOW if phase_active else SignalState.RED
        elif transition_kind == SignalState.RED_YELLOW:
            state = SignalState.RED_YELLOW if phase_active else SignalState.RED
        else:
            state = SignalState.GREEN if phase_active else SignalState.RED

        support_term = min(1.0, support / 2.0)
        probability = 0.70 * phase_confidence + 0.30 * (
            support_term if phase_active else 1.0 - support_term
        )
        if traffic_confidence < self.min_traffic_confidence and support == 0:
            probability *= 0.50
        return state, max(0.0, min(1.0, probability))

    def _conflict_is_short(
        self,
        events: Sequence[TrajectoryEvent],
        approach: str,
        current_time_s: float,
        origin_ms: int | None,
    ) -> bool:
        if origin_ms is None:
            return False
        now_ms = origin_ms + int(current_time_s * 1000)
        conflict_times = [
            event.timestamp_ms
            for event in events
            if event.approach == approach
            and event.event_type in {EventType.RELEASE, EventType.CROSSING}
            and event.timestamp_ms <= now_ms
        ]
        if not conflict_times:
            return False
        return now_ms - min(conflict_times) < self.conflict_persistence_seconds * 1000


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
