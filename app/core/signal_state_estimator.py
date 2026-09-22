from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import json
import math
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from app.core.intersection_topology import (
    DEFAULT_INTERSECTION_TOPOLOGY,
    IntersectionTopology,
)
from app.core.models import EventType, TrajectoryEvent
from app.core.preprocessing import load_trajectory_file


# The steady yellow interval is fixed separately from the pre-green
# red+yellow interval. Keeping them distinct prevents UI-only transition
# semantics and makes backend timing explicit.
DEFAULT_YELLOW_DURATION_SECONDS = 3.0
DEFAULT_RED_YELLOW_DURATION_SECONDS = 2.0
DEFAULT_RECENT_WINDOW_SECONDS = 12.0
DEFAULT_MIN_PHASE_CONFIDENCE = 0.20
DEFAULT_MIN_TRAFFIC_CONFIDENCE = 0.12
DEFAULT_CONFLICT_PERSISTENCE_SECONDS = 3.0
APPROACHES = DEFAULT_INTERSECTION_TOPOLOGY.approaches


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
    yellow_duration_seconds: float = DEFAULT_YELLOW_DURATION_SECONDS
    red_yellow_duration_seconds: float = DEFAULT_RED_YELLOW_DURATION_SECONDS
    approaches: tuple[ApproachState, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp_s": self.timestamp_s,
            "cycle_phase_s": self.cycle_phase_s,
            "phase_id": self.phase_id,
            "transition": self.transition,
            "phase_confidence": self.phase_confidence,
            "traffic_evidence_confidence": self.traffic_evidence_confidence,
            "yellow_duration_seconds": self.yellow_duration_seconds,
            "red_yellow_duration_seconds": self.red_yellow_duration_seconds,
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
        red_yellow_duration_seconds: float = DEFAULT_RED_YELLOW_DURATION_SECONDS,
        conflict_persistence_seconds: float = DEFAULT_CONFLICT_PERSISTENCE_SECONDS,
        event_origin_ms: int | None = None,
        topology: IntersectionTopology | None = None,
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
        if (
            red_yellow_duration_seconds < 0
            or red_yellow_duration_seconds >= cycle
        ):
            raise ValueError("invalid red_yellow_duration_seconds")
        if conflict_persistence_seconds < 0:
            raise ValueError("conflict_persistence_seconds must be non-negative")

        self.phase_model = phase_model
        self.topology = topology or DEFAULT_INTERSECTION_TOPOLOGY
        self.recent_window_s = float(recent_window_s)
        self.min_phase_confidence = float(min_phase_confidence)
        self.min_traffic_confidence = float(min_traffic_confidence)
        self.yellow_duration_seconds = float(yellow_duration_seconds)
        self.red_yellow_duration_seconds = float(
            red_yellow_duration_seconds
        )
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
        active = (
            set(getattr(phase, "active_approaches", ()))
            if phase
            else set()
        )
        evidence = self._event_evidence(recent, active)
        transition_kinds = {
            approach: self._transition_kind_for_approach(
                position,
                phase,
                approach,
            )
            for approach in self.topology.approaches
        }

        states: list[ApproachState] = []
        for approach in self.topology.approaches:
            support, supporting, contradictory = evidence[approach]
            traffic_conf = self._approach_traffic_confidence(
                support,
                supporting,
                contradictory,
            )
            phase_active = approach in active
            transition_kind = transition_kinds[approach]

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
                        active,
                        current_time_s,
                        origin_ms,
                    )
                    and transition_kind is None
                ):
                    # Keep the structural stage state; only confidence falls.
                    probability = min(probability, 0.55)
                    state = (
                        SignalState.GREEN
                        if phase_active
                        else SignalState.RED
                    )

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
            transition=any(
                kind is not None
                for kind in transition_kinds.values()
            ),
            phase_confidence=round(phase_confidence, 4),
            traffic_evidence_confidence=round(traffic_confidence, 4),
            yellow_duration_seconds=self.yellow_duration_seconds,
            red_yellow_duration_seconds=self.red_yellow_duration_seconds,
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
            red_yellow_duration_seconds=self.red_yellow_duration_seconds,
            conflict_persistence_seconds=self.conflict_persistence_seconds,
            event_origin_ms=origin,
            topology=self.topology,
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

    def _transition_kind_for_approach(
        self,
        position: float,
        phase,
        approach: str,
    ) -> SignalState | None:
        """Apply transitions to an approach, not to the whole stage.

        When {N} becomes {N,S}, N remains GREEN while only S enters its
        RED_YELLOW/start transition. Likewise an approach that remains active
        in the next stage is not turned YELLOW at the internal stage boundary.
        """
        if (
            phase is None
            or (
                self.yellow_duration_seconds == 0
                and self.red_yellow_duration_seconds == 0
            )
            or approach not in getattr(phase, "active_approaches", ())
        ):
            return None

        cycle = self.phase_model.cycle_seconds
        start = float(phase.phase_start) % cycle
        end = float(phase.phase_end) % cycle
        epsilon = min(0.001, max(1e-6, cycle / 1_000_000.0))

        previous_phase = self._phase_at((start - epsilon) % cycle)
        next_phase = self._phase_at((end + epsilon) % cycle)
        previous_active = (
            approach in getattr(previous_phase, "active_approaches", ())
            if previous_phase is not None
            else False
        )
        next_active = (
            approach in getattr(next_phase, "active_approaches", ())
            if next_phase is not None
            else False
        )

        distance_to_end = (end - position) % cycle
        if (
            not next_active
            and 0 < distance_to_end <= self.yellow_duration_seconds
        ):
            return SignalState.YELLOW

        distance_from_start = (position - start) % cycle
        if (
            not previous_active
            and self.red_yellow_duration_seconds > 0
            and 0 <= distance_from_start < self.red_yellow_duration_seconds
        ):
            return SignalState.RED_YELLOW
        return None

    def _origin_ms(self, events: Sequence[TrajectoryEvent]) -> int:
        """Resolve the raw timestamp origin used by the phase model."""
        if self.event_origin_ms is not None:
            return int(self.event_origin_ms)
        return int(getattr(self.phase_model, "origin_timestamp_ms", 0) or 0)

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

    def _approaches_conflict(self, left: str, right: str) -> bool:
        return self.topology.approaches_conflict(left, right)

    def _events_conflict(
        self,
        left: TrajectoryEvent,
        right: TrajectoryEvent,
    ) -> bool:
        return self.topology.movements_conflict(
            left.movement,
            right.movement,
            left_approach=left.approach,
            right_approach=right.approach,
        )

    def _event_conflicts_with_active_flow(
        self,
        event: TrajectoryEvent,
        events: Sequence[TrajectoryEvent],
        active: set[str],
    ) -> bool:
        active_events = [
            other
            for other in events
            if (
                other.approach in active
                and other.approach != event.approach
            )
        ]
        if active_events:
            relevant = [
                other
                for other in active_events
                if self._approaches_conflict(
                    event.approach,
                    other.approach,
                )
            ]
            if relevant:
                return any(
                    self._events_conflict(event, other)
                    for other in relevant
                )
            return False
        return any(
            self._approaches_conflict(event.approach, approach)
            for approach in active
        )

    @staticmethod
    def _event_weight(event: TrajectoryEvent) -> float:
        return (
            1.0 if event.event_type == EventType.RELEASE else 0.5
        ) * max(0.0, min(1.0, float(event.confidence)))

    def _event_evidence(
        self,
        events: Sequence[TrajectoryEvent],
        active: set[str],
    ) -> dict[str, tuple[float, int, int]]:
        """Score observed flow against the configured conflict topology.

        Silence and STOP are never RED/GREEN evidence. Family conflicts are
        the conservative fallback; explicit movement compatibility can
        suppress a false contradiction when geometry is known.
        """
        result: dict[str, tuple[float, int, int]] = {}
        for approach in self.topology.approaches:
            own_events = [
                event
                for event in events
                if event.approach == approach
            ]

            if approach in active:
                support_events = own_events
                if own_events:
                    contradiction_events = [
                        event
                        for event in events
                        if (
                            event.approach != approach
                            and self._approaches_conflict(
                                approach,
                                event.approach,
                            )
                            and any(
                                self._events_conflict(own, event)
                                for own in own_events
                            )
                        )
                    ]
                else:
                    contradiction_events = [
                        event
                        for event in events
                        if self._approaches_conflict(
                            approach,
                            event.approach,
                        )
                    ]
            else:
                support_events = [
                    event
                    for event in events
                    if (
                        event.approach in active
                        and self._approaches_conflict(
                            approach,
                            event.approach,
                        )
                    )
                ]
                contradiction_events = [
                    event
                    for event in own_events
                    if self._event_conflicts_with_active_flow(
                        event,
                        events,
                        active,
                    )
                ]

            support_weight = sum(
                self._event_weight(event)
                for event in support_events
            )
            result[approach] = (
                support_weight,
                len(support_events),
                len(contradiction_events),
            )
        return result

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
        active: set[str],
        current_time_s: float,
        origin_ms: int,
    ) -> bool:
        conflict_times_s = [
            (event.timestamp_ms - origin_ms) / 1000.0
            for event in events
            if (
                (
                    self._approaches_conflict(approach, event.approach)
                    if approach in active
                    else event.approach == approach
                )
                and event.event_type
                in {EventType.RELEASE, EventType.CROSSING}
                and (event.timestamp_ms - origin_ms) / 1000.0
                <= current_time_s
            )
        ]
        if not conflict_times_s:
            return False
        return (
            current_time_s - min(conflict_times_s)
            < self.conflict_persistence_seconds
        )


def result_to_json(result: SignalStateResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


__all__ = [
    "DEFAULT_RED_YELLOW_DURATION_SECONDS",
    "DEFAULT_YELLOW_DURATION_SECONDS",
    "ApproachState",
    "SignalState",
    "SignalStateEstimator",
    "SignalStateResult",
    "result_to_json",
]
