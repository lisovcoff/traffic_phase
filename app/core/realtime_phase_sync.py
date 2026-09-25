from __future__ import annotations

from collections import Counter, deque
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
        min_family_evidence_weight: float = 1.0,
        min_family_match_ratio: float = 0.75,
        min_family_weight_share: float = 0.20,
        min_candidate_margin: float = 0.001,
        incompatible_match_ratio: float = 0.60,
        min_observation_span_seconds: float = 12.0,
        evidence_history_size: int = 64,
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
        if min_family_evidence_weight <= 0:
            raise ValueError("min_family_evidence_weight must be positive")
        if not 0.0 < min_family_match_ratio <= 1.0:
            raise ValueError("min_family_match_ratio must be in (0, 1]")
        if not 0.0 < min_family_weight_share <= 0.5:
            raise ValueError("min_family_weight_share must be in (0, 0.5]")
        if min_candidate_margin < 0:
            raise ValueError("min_candidate_margin must be non-negative")
        if not 0.0 < incompatible_match_ratio < min_match_ratio:
            raise ValueError("incompatible_match_ratio must be below min_match_ratio")
        if min_observation_span_seconds < 0:
            raise ValueError("min_observation_span_seconds must be non-negative")
        if evidence_history_size < min_evidence_events:
            raise ValueError("evidence_history_size must cover min_evidence_events")
        self.resolution_seconds = resolution
        self.min_family_evidence_weight = float(min_family_evidence_weight)
        self.min_family_match_ratio = float(min_family_match_ratio)
        self.min_family_weight_share = float(min_family_weight_share)
        self.min_candidate_margin = float(min_candidate_margin)
        self.incompatible_match_ratio = float(incompatible_match_ratio)
        self.min_observation_span_seconds = float(min_observation_span_seconds)
        self.evidence_history_size = int(evidence_history_size)

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
        self._evidence: deque[TrajectoryEvent] = deque(maxlen=self.evidence_history_size)
        self._seen_event_fingerprints: deque[str] = deque(maxlen=self.evidence_history_size)
        self._status = "WARMUP"
        self._locked_offset_seconds: float | None = None
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
        self._evidence.clear()
        self._seen_event_fingerprints.clear()
        self._status = "WARMUP"
        self._locked_offset_seconds = None

    def enter_recovery(self) -> None:
        """Require fresh arrived evidence after a synchronization break."""
        if self._fixed_offset_seconds is not None:
            return
        self.reset()
        self._status = "RECOVERY"

    def ingest(self, event: TrajectoryEvent) -> PhaseSynchronization:
        if event.event_type not in {EventType.RELEASE, EventType.CROSSING}:
            return self.snapshot()

        group = self.template.group_for_approach(event.approach)
        if group is None:
            self._status = "INCOMPATIBLE"
            return self.snapshot()

        fingerprint = self._event_fingerprint(event)
        if fingerprint in self._seen_event_fingerprints:
            return self.snapshot()

        weight = self._event_weight(event)
        if weight <= 0:
            return self.snapshot()

        if self._status == "RECOVERY":
            self._status = "WARMUP"
            self._locked_offset_seconds = None

        self._seen_event_fingerprints.append(fingerprint)
        self._evidence.append(event)
        self._evidence_count = len(self._evidence)
        return self._rescore()

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

        if self._status == "RECOVERY":
            return PhaseSynchronization(
                status="RECOVERY",
                offset_seconds=None,
                confidence=0.0,
                evidence_count=self._evidence_count,
                observed_group_count=len(self._groups),
                match_ratio=0.0,
            )

        if not self._evidence or self._total_weight <= 0:
            return PhaseSynchronization(
                status=self._status,
                offset_seconds=None,
                confidence=0.0,
                evidence_count=self._evidence_count,
                observed_group_count=len(self._groups),
                match_ratio=0.0,
            )

        best_index = max(range(len(self._scores)), key=self._scores.__getitem__)
        ranked = sorted(self._scores, reverse=True)
        second_score = ranked[1] if len(ranked) > 1 else ranked[0]
        match_ratio = self._matched_weights[best_index] / max(self._total_weight, 1e-9)
        candidate_margin = (
            (self._scores[best_index] - second_score)
            / max(self._total_weight, 1e-9)
        )

        family_weights, family_matches = self._family_match_statistics(best_index)
        required_families = self._required_families()
        family_ratios = {
            family: family_matches[family] / max(family_weights[family], 1e-9)
            for family in required_families
        }
        family_shares = {
            family: family_weights[family] / max(self._total_weight, 1e-9)
            for family in required_families
        }
        family_ready = all(
            family_weights[family] >= self.min_family_evidence_weight
            and family_ratios[family] >= self.min_family_match_ratio
            and family_shares[family] >= self.min_family_weight_share
            for family in required_families
        )
        group_ready = (
            len(self._groups) >= len(required_families)
            if required_families
            else bool(self._groups)
        )
        observation_span = (
            max(event.timestamp_ms for event in self._evidence)
            - min(event.timestamp_ms for event in self._evidence)
        ) / 1000.0
        span_ready = observation_span >= self.min_observation_span_seconds

        evidence_factor = min(
            1.0,
            self._evidence_count / max(1, self.min_evidence_events),
        )
        group_factor = (
            min(1.0, len(self._groups) / max(1, len(required_families)))
            if required_families else 1.0
        )
        family_factor = min(family_ratios.values()) if family_ratios else 1.0
        margin_factor = min(
            1.0,
            candidate_margin / max(self.min_candidate_margin, 1e-9),
        )
        confidence = max(
            0.0,
            min(
                1.0,
                match_ratio
                * evidence_factor
                * group_factor
                * family_factor
                * margin_factor,
            ),
        )

        synchronized = (
            self._evidence_count >= self.min_evidence_events
            and group_ready
            and family_ready
            and span_ready
            and match_ratio >= self.min_match_ratio
            and candidate_margin >= self.min_candidate_margin
        )
        if synchronized:
            self._status = "SYNCHRONIZED"
            self._locked_offset_seconds = self._candidates[best_index]
        elif (
            self._evidence_count >= self.min_evidence_events
            and group_ready
            and span_ready
            and all(
                family_weights[family] >= self.min_family_evidence_weight
                for family in required_families
            )
            and match_ratio < self.incompatible_match_ratio
        ):
            self._status = "INCOMPATIBLE"
            self._locked_offset_seconds = None
        else:
            self._status = "WARMUP"
            self._locked_offset_seconds = None

        return PhaseSynchronization(
            status=self._status,
            offset_seconds=(
                round(self._locked_offset_seconds, 3)
                if self._status == "SYNCHRONIZED"
                else None
            ),
            confidence=round(confidence, 4),
            evidence_count=self._evidence_count,
            observed_group_count=len(self._groups),
            match_ratio=round(match_ratio, 4),
        )

    def _rescore(self) -> PhaseSynchronization:
        self._scores = [0.0] * len(self._candidates)
        self._matched_weights = [0.0] * len(self._candidates)
        self._total_weight = 0.0
        self._evidence_count = len(self._evidence)
        self._groups = {
            group
            for event in self._evidence
            for group in (self.template.group_for_approach(event.approach),)
            if group is not None
        }
        for event in self._evidence:
            weight = self._event_weight(event)
            if weight <= 0:
                continue
            self._total_weight += weight
            timestamp_s = event.timestamp_ms / 1000.0
            for index, offset in enumerate(self._candidates):
                position = (timestamp_s + offset) % self.template.cycle_seconds
                phase = self.template.phase_at(position)
                if phase is not None and event.approach in phase.active_approaches:
                    centrality = self._phase_centrality(phase, position)
                    self._scores[index] += weight * (1.0 + 0.20 * centrality)
                    self._matched_weights[index] += weight
                else:
                    self._scores[index] -= weight
        return self.snapshot()

    def _family_match_statistics(
        self,
        best_index: int,
    ) -> tuple[Counter[str], Counter[str]]:
        weights: Counter[str] = Counter()
        matches: Counter[str] = Counter()
        offset = self._candidates[best_index]
        for event in self._evidence:
            family = self.template.group_for_approach(event.approach)
            if not family:
                continue
            name = family[0]
            weight = self._event_weight(event)
            weights[name] += weight
            position = (event.timestamp_ms / 1000.0 + offset) % self.template.cycle_seconds
            phase = self.template.phase_at(position)
            if phase is not None and event.approach in phase.active_approaches:
                matches[name] += weight
        return weights, matches

    def _required_families(self) -> tuple[str, ...]:
        return tuple(
            family.name
            for family in self.template.topology.families
            if self.template.topology.conflicting_families_for(family.name)
        )

    @staticmethod
    def _event_weight(event: TrajectoryEvent) -> float:
        return (
            1.0 if event.event_type == EventType.RELEASE else 0.5
        ) * max(0.0, min(1.0, float(event.confidence)))

    @staticmethod
    def _event_fingerprint(event: TrajectoryEvent) -> str:
        return "|".join(map(str, (
            event.event_type.value,
            int(event.timestamp_ms),
            event.approach,
            event.movement,
            round(float(event.confidence), 6),
            event.quality,
        )))

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
