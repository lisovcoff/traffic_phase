from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.core.event_phase_discovery import (
    EventPhase,
    EventPhaseDiscoveryResult,
    MovementSignalStage,
)
from app.core.intersection_topology import (
    DEFAULT_INTERSECTION_TOPOLOGY,
    IntersectionTopology,
)
from app.core.models import EventType, TrajectoryEvent


@dataclass(frozen=True)
class RealtimePhaseTemplate:
    """Timestamp-independent recurring phase structure for one intersection."""

    cycle_seconds: float
    bin_seconds: float
    phases: tuple[EventPhase, ...]
    cycle_coverage: float = 1.0
    overlap: float = 0.0
    supporting_event_count: int = 0
    contradictory_event_count: int = 0
    movement_stages: tuple[MovementSignalStage, ...] = ()
    topology: IntersectionTopology = DEFAULT_INTERSECTION_TOPOLOGY

    @classmethod
    def from_phase_model(
        cls,
        phase_model: object,
        *,
        topology: IntersectionTopology | None = None,
    ) -> "RealtimePhaseTemplate":
        cycle_seconds = float(getattr(phase_model, "cycle_seconds", 0.0))
        bin_seconds = float(getattr(phase_model, "bin_seconds", 0.0))
        phases = tuple(getattr(phase_model, "phases", ()))
        if cycle_seconds <= 0:
            raise ValueError("phase template cycle must be positive")
        if bin_seconds <= 0:
            raise ValueError("phase template bin_seconds must be positive")
        if not phases:
            raise ValueError("phase template requires at least one phase")
        return cls(
            cycle_seconds=cycle_seconds,
            bin_seconds=bin_seconds,
            phases=phases,
            cycle_coverage=float(getattr(phase_model, "cycle_coverage", 1.0)),
            overlap=float(getattr(phase_model, "overlap", 0.0)),
            supporting_event_count=int(
                getattr(phase_model, "supporting_event_count", 0)
            ),
            contradictory_event_count=int(
                getattr(phase_model, "contradictory_event_count", 0)
            ),
            movement_stages=tuple(
                getattr(phase_model, "movement_stages", ())
            ),
            topology=topology or DEFAULT_INTERSECTION_TOPOLOGY,
        )

    def to_phase_model(self) -> EventPhaseDiscoveryResult:
        """Return an origin-free model for existing signal-state components."""
        return EventPhaseDiscoveryResult(
            cycle_seconds=self.cycle_seconds,
            bin_seconds=self.bin_seconds,
            phases=self.phases,
            profiles=(),
            cycle_coverage=self.cycle_coverage,
            overlap=self.overlap,
            supporting_event_count=self.supporting_event_count,
            contradictory_event_count=self.contradictory_event_count,
            origin_timestamp_ms=0,
            movement_stages=self.movement_stages,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "cycle_seconds": self.cycle_seconds,
            "bin_seconds": self.bin_seconds,
            "phases": [phase.to_dict() for phase in self.phases],
            "cycle_coverage": self.cycle_coverage,
            "overlap": self.overlap,
            "supporting_event_count": self.supporting_event_count,
            "contradictory_event_count": self.contradictory_event_count,
            "movement_stages": [
                stage.to_dict()
                for stage in self.movement_stages
            ],
        }

    def phase_at(self, position_s: float) -> EventPhase | None:
        value = position_s % self.cycle_seconds
        for phase in self.phases:
            start = phase.phase_start % self.cycle_seconds
            end = phase.phase_end % self.cycle_seconds
            inside = (
                start <= value < end
                if start <= end
                else value >= start or value < end
            )
            if inside:
                return phase
        return None

    def active_movements_at(
        self,
        position_s: float,
    ) -> tuple[MovementSignalStage, ...]:
        """Movement stages use the same cycle position as the main template."""
        value = position_s % self.cycle_seconds
        active: list[MovementSignalStage] = []
        for stage in self.movement_stages:
            start = stage.phase_start % self.cycle_seconds
            end = stage.phase_end % self.cycle_seconds
            inside = (
                start <= value < end
                if start <= end
                else value >= start or value < end
            )
            if inside:
                active.append(stage)
        return tuple(active)

    def group_for_approach(self, approach: str) -> tuple[str, ...] | None:
        """Return the configured stable synchronization family."""
        if not any(
            approach in phase.active_approaches
            for phase in self.phases
        ):
            return None
        family = self.topology.family_for_approach(approach)
        return (family,) if family is not None else (approach,)


@dataclass(frozen=True)
class PhaseSynchronization:
    status: str
    offset_seconds: float | None
    confidence: float
    evidence_count: int
    observed_group_count: int
    match_ratio: float = 0.0

    @property
    def synchronized(self) -> bool:
        return self.status == "SYNCHRONIZED"


class RealtimePhaseSynchronizer:
    """Online circular matching of live events to a known phase template.

    offset_seconds maps an absolute realtime timestamp to cycle position:
    cycle_position = (timestamp_seconds + offset_seconds) % cycle_seconds.

    The synchronizer only consumes evidence passed to ingest. It has no
    access to future events and stores a fixed-size score vector rather than
    retaining an unbounded event history.
    """

    def __init__(
        self,
        template: RealtimePhaseTemplate,
        *,
        min_evidence_events: int = 6,
        min_match_ratio: float = 0.80,
        resolution_seconds: float | None = None,
        fixed_origin_ms: int | None = None,
    ) -> None:
        if min_evidence_events < 1:
            raise ValueError("min_evidence_events must be positive")
        if not 0.0 < min_match_ratio <= 1.0:
            raise ValueError("min_match_ratio must be in (0, 1]")

        self.template = template
        self.min_evidence_events = int(min_evidence_events)
        self.min_match_ratio = float(min_match_ratio)
        resolution = (
            min(2.0, template.bin_seconds)
            if resolution_seconds is None
            else float(resolution_seconds)
        )
        if resolution <= 0:
            raise ValueError("resolution_seconds must be positive")
        self.resolution_seconds = resolution

        candidate_count = max(
            1,
            int(round(template.cycle_seconds / resolution)),
        )
        self._candidates = tuple(
            index * template.cycle_seconds / candidate_count
            for index in range(candidate_count)
        )
        self._scores = [0.0] * len(self._candidates)
        self._matched_weights = [0.0] * len(self._candidates)
        self._total_weight = 0.0
        self._evidence_count = 0
        self._groups: set[tuple[str, ...]] = set()
        self._fixed_offset_seconds = (
            (-fixed_origin_ms / 1000.0) % template.cycle_seconds
            if fixed_origin_ms is not None
            else None
        )

    @property
    def evidence_count(self) -> int:
        return self._evidence_count

    def reset(self) -> None:
        self._scores = [0.0] * len(self._candidates)
        self._matched_weights = [0.0] * len(self._candidates)
        self._total_weight = 0.0
        self._evidence_count = 0
        self._groups.clear()

    def ingest(self, event: TrajectoryEvent) -> PhaseSynchronization:
        if event.event_type not in {EventType.RELEASE, EventType.CROSSING}:
            return self.snapshot()

        group = self.template.group_for_approach(event.approach)
        if group is None:
            return self.snapshot()

        weight = (
            1.0 if event.event_type == EventType.RELEASE else 0.5
        ) * max(0.0, min(1.0, float(event.confidence)))
        if weight <= 0:
            return self.snapshot()

        self._evidence_count += 1
        self._groups.add(group)
        self._total_weight += weight
        timestamp_s = event.timestamp_ms / 1000.0

        for index, offset in enumerate(self._candidates):
            position = (timestamp_s + offset) % self.template.cycle_seconds
            phase = self.template.phase_at(position)
            matched = (
                phase is not None
                and event.approach in phase.active_approaches
            )
            if matched:
                centrality = self._phase_centrality(phase, position)
                self._scores[index] += weight * (1.0 + 0.20 * centrality)
                self._matched_weights[index] += weight
            else:
                self._scores[index] -= weight

        return self.snapshot()

    def ingest_many(
        self,
        events: Iterable[TrajectoryEvent],
    ) -> PhaseSynchronization:
        state = self.snapshot()
        for event in events:
            state = self.ingest(event)
        return state

    def snapshot(self) -> PhaseSynchronization:
        if self._fixed_offset_seconds is not None:
            return PhaseSynchronization(
                status="SYNCHRONIZED",
                offset_seconds=round(self._fixed_offset_seconds, 3),
                confidence=1.0,
                evidence_count=self._evidence_count,
                observed_group_count=len(self._groups),
                match_ratio=1.0,
            )

        if not self._scores or self._total_weight <= 0:
            return PhaseSynchronization(
                status="WARMUP",
                offset_seconds=None,
                confidence=0.0,
                evidence_count=self._evidence_count,
                observed_group_count=len(self._groups),
                match_ratio=0.0,
            )

        best_index = max(
            range(len(self._scores)),
            key=self._scores.__getitem__,
        )
        match_ratio = self._matched_weights[best_index] / self._total_weight
        evidence_factor = min(
            1.0,
            self._evidence_count / max(1, self.min_evidence_events),
        )
        group_factor = min(1.0, len(self._groups) / 2.0)
        confidence = max(
            0.0,
            min(
                1.0,
                match_ratio * evidence_factor * group_factor,
            ),
        )
        synchronized = (
            self._evidence_count >= self.min_evidence_events
            and len(self._groups) >= 2
            and match_ratio >= self.min_match_ratio
        )
        return PhaseSynchronization(
            status="SYNCHRONIZED" if synchronized else "WARMUP",
            offset_seconds=(
                round(self._candidates[best_index], 3)
                if synchronized
                else None
            ),
            confidence=round(confidence, 4),
            evidence_count=self._evidence_count,
            observed_group_count=len(self._groups),
            match_ratio=round(match_ratio, 4),
        )

    def cycle_position_s(
        self,
        timestamp_ms: int,
        synchronization: PhaseSynchronization | None = None,
    ) -> float | None:
        state = synchronization or self.snapshot()
        if not state.synchronized or state.offset_seconds is None:
            return None
        return round(
            (
                timestamp_ms / 1000.0
                + state.offset_seconds
            )
            % self.template.cycle_seconds,
            3,
        )

    def _phase_centrality(
        self,
        phase: EventPhase,
        position_s: float,
    ) -> float:
        cycle = self.template.cycle_seconds
        start = phase.phase_start % cycle
        end = phase.phase_end % cycle
        duration = (end - start) % cycle
        if duration <= 0:
            duration = cycle
        progress = (position_s - start) % cycle
        if progress > duration:
            return 0.0
        edge_distance = min(progress, duration - progress)
        return max(
            0.0,
            min(1.0, edge_distance / max(duration / 2.0, 1e-9)),
        )


__all__ = [
    "PhaseSynchronization",
    "RealtimePhaseSynchronizer",
    "RealtimePhaseTemplate",
]
