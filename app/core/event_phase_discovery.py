from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Sequence

import numpy as np

from app.core.models import EventType, TrajectoryEvent


@dataclass(frozen=True)
class PhaseGroup:
    name: str
    approaches: tuple[str, ...]


DEFAULT_PHASE_GROUPS = (
    PhaseGroup("NS", ("N", "S")),
    PhaseGroup("EW", ("E", "W")),
)


@dataclass(frozen=True)
class EventPhaseProfile:
    group: str
    values: tuple[float, ...]
    event_counts: tuple[int, ...]
    cycle_count: int


@dataclass(frozen=True)
class EventPhase:
    phase_id: int
    phase_start: float
    phase_end: float
    active_approaches: tuple[str, ...]
    confidence: float
    supporting_event_count: int
    contradictory_event_count: int
    members: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class EventPhaseDiscoveryResult:
    cycle_seconds: float
    bin_seconds: float
    phases: tuple[EventPhase, ...]
    profiles: tuple[EventPhaseProfile, ...]
    cycle_coverage: float
    overlap: float
    supporting_event_count: int
    contradictory_event_count: int
    origin_timestamp_ms: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "cycle_seconds": self.cycle_seconds,
            "bin_seconds": self.bin_seconds,
            "phases": [phase.to_dict() for phase in self.phases],
            "profiles": [asdict(profile) for profile in self.profiles],
            "cycle_coverage": self.cycle_coverage,
            "overlap": self.overlap,
            "supporting_event_count": self.supporting_event_count,
            "contradictory_event_count": self.contradictory_event_count,
            "origin_timestamp_ms": self.origin_timestamp_ms,
        }


class EventPhaseDiscovery:
    """Infer recurring green intervals from real traffic events.

    Only RELEASE and CROSSING are evidence. STOP, APPROACH and trajectory
    wait/stay values never directly contribute to a green/red decision.

    Events are assigned to absolute cycles before modulo projection. Evidence
    is accumulated only in the event's own time bin; no temporal window is
    applied around a boundary. This prevents previous-phase/previous-cycle
    observations from leaking into the next phase.
    """

    RELEASE_WEIGHT = 1.0
    CROSSING_WEIGHT = 0.5

    def __init__(
        self,
        *,
        bin_seconds: float = 2.0,
        min_phase_seconds: float = 8.0,
        groups: Sequence[PhaseGroup] = DEFAULT_PHASE_GROUPS,
        min_event_confidence: float = 0.0,
    ) -> None:
        if bin_seconds <= 0 or min_phase_seconds < bin_seconds:
            raise ValueError("invalid phase-discovery timing parameters")
        if len(groups) < 2:
            raise ValueError("at least two phase groups are required")
        if min_event_confidence < 0 or min_event_confidence > 1:
            raise ValueError("min_event_confidence must be in [0, 1]")
        names = [group.name for group in groups]
        if len(set(names)) != len(names):
            raise ValueError("phase group names must be unique")

        self.bin_seconds = float(bin_seconds)
        self.min_phase_bins = max(1, int(round(min_phase_seconds / bin_seconds)))
        self.groups = tuple(groups)
        self.min_event_confidence = float(min_event_confidence)
        self._group_by_approach = {
            approach: group.name
            for group in self.groups
            for approach in group.approaches
        }
        self._group_index = {
            group.name: index for index, group in enumerate(self.groups)
        }

    def discover(
        self,
        events: Iterable[TrajectoryEvent],
        *,
        cycle_seconds: float,
    ) -> EventPhaseDiscoveryResult:
        events = list(events)
        selected = [
            event
            for event in events
            if event.event_type in {EventType.RELEASE, EventType.CROSSING}
            and event.confidence >= self.min_event_confidence
            and event.approach in self._group_by_approach
        ]
        if not selected:
            raise ValueError("no usable RELEASE/CROSSING events")
        origin_timestamp_ms = min(event.timestamp_ms for event in selected)

        profiles, evidence, counts = self.build_profiles(
            events,
            cycle_seconds=cycle_seconds,
        )
        states = self._best_schedule(evidence)
        phases = self._build_phases(
            states,
            counts,
            cycle_seconds,
        )
        coverage = self._cycle_coverage(phases, cycle_seconds)
        return EventPhaseDiscoveryResult(
            cycle_seconds=float(cycle_seconds),
            bin_seconds=self.bin_seconds,
            phases=tuple(phases),
            profiles=tuple(profiles),
            cycle_coverage=round(coverage, 4),
            overlap=0.0,
            supporting_event_count=sum(
                phase.supporting_event_count for phase in phases
            ),
            contradictory_event_count=sum(
                phase.contradictory_event_count for phase in phases
            ),
            origin_timestamp_ms=origin_timestamp_ms,
        )

    def build_profiles(
        self,
        events: Iterable[TrajectoryEvent],
        *,
        cycle_seconds: float,
    ) -> tuple[list[EventPhaseProfile], np.ndarray, np.ndarray]:
        if cycle_seconds < 2 * self.bin_seconds:
            raise ValueError("cycle is too short for event phase discovery")

        selected = [
            event
            for event in events
            if event.event_type in {EventType.RELEASE, EventType.CROSSING}
            and event.confidence >= self.min_event_confidence
            and event.approach in self._group_by_approach
        ]
        if not selected:
            raise ValueError("no usable RELEASE/CROSSING events")

        n_bins = max(1, int(round(cycle_seconds / self.bin_seconds)))
        start_ms = min(event.timestamp_ms for event in selected)
        cycle_ids = np.floor(
            (
                np.asarray(
                    [event.timestamp_ms for event in selected],
                    dtype=float,
                )
                - start_ms
            )
            / 1000.0
            / cycle_seconds
        ).astype(int)
        cycle_count = int(cycle_ids.max()) + 1

        evidence = np.zeros(
            (cycle_count, len(self.groups), n_bins),
            dtype=float,
        )
        counts = np.zeros(
            (cycle_count, len(self.groups), n_bins),
            dtype=int,
        )

        for event, cycle_id in zip(selected, cycle_ids):
            relative_s = ((event.timestamp_ms - start_ms) / 1000.0) % cycle_seconds
            bin_id = min(int(relative_s / self.bin_seconds), n_bins - 1)
            group_id = self._group_index[self._group_by_approach[event.approach]]
            weight = (
                self.RELEASE_WEIGHT
                if event.event_type == EventType.RELEASE
                else self.CROSSING_WEIGHT
            )
            weight *= float(np.clip(event.confidence, 0.0, 1.0))
            evidence[cycle_id, group_id, bin_id] += weight
            counts[cycle_id, group_id, bin_id] += 1

        profiles: list[EventPhaseProfile] = []
        for group_id, group in enumerate(self.groups):
            profiles.append(
                EventPhaseProfile(
                    group=group.name,
                    values=tuple(
                        np.round(
                            np.median(evidence[:, group_id, :], axis=0),
                            6,
                        )
                    ),
                    event_counts=tuple(
                        np.median(
                            counts[:, group_id, :],
                            axis=0,
                        ).astype(int).tolist()
                    ),
                    cycle_count=cycle_count,
                )
            )
        return profiles, evidence, counts

    def _best_schedule(self, evidence: np.ndarray) -> np.ndarray:
        profile = np.median(evidence, axis=0)
        if len(self.groups) == 2:
            return self._best_two_group_schedule(profile)

        states = np.argmax(profile, axis=0).astype(np.int8)
        return self._merge_short_runs(states)

    def _best_two_group_schedule(self, profile: np.ndarray) -> np.ndarray:
        first = profile[0]
        second = profile[1]
        n_bins = len(first)
        if n_bins < 2 * self.min_phase_bins:
            raise ValueError("cycle is too short for two signal phases")

        best_score = -np.inf
        best_start = 0
        best_length = self.min_phase_bins
        first_doubled = np.r_[first, first]
        second_doubled = np.r_[second, second]
        first_prefix = np.r_[0.0, np.cumsum(first_doubled)]
        second_prefix = np.r_[0.0, np.cumsum(second_doubled)]
        total_second = float(second_prefix[n_bins])

        for start in range(n_bins):
            for length in range(
                self.min_phase_bins,
                n_bins - self.min_phase_bins + 1,
            ):
                end = start + length
                first_inside = first_prefix[end] - first_prefix[start]
                second_inside = second_prefix[end] - second_prefix[start]
                score = first_inside + total_second - second_inside
                if score > best_score:
                    best_score = score
                    best_start = start
                    best_length = length

        states = np.ones(n_bins, dtype=np.int8)
        states[(best_start + np.arange(best_length)) % n_bins] = 0
        return states

    def _merge_short_runs(self, states: np.ndarray) -> np.ndarray:
        result = states.copy()
        for _ in range(len(result)):
            transitions = np.flatnonzero(result != np.roll(result, 1))
            if len(transitions) <= 1:
                return result
            changed = False
            for start in transitions:
                previous = (start - 1) % len(result)
                state = result[start]
                end = start
                while result[end] == state:
                    end = (end + 1) % len(result)
                    if end == start:
                        break
                length = (end - start) % len(result)
                if length and length < self.min_phase_bins:
                    if start < end:
                        result[start:end] = result[previous]
                    else:
                        result[start:] = result[previous]
                        result[:end] = result[previous]
                    changed = True
                    break
            if not changed:
                return result
        return result

    def _build_phases(
        self,
        states: np.ndarray,
        counts: np.ndarray,
        cycle_seconds: float,
    ) -> list[EventPhase]:
        transitions = [
            index
            for index in range(len(states))
            if states[index] != states[index - 1]
        ]
        if not transitions:
            return []

        if len(self.groups) == 2 and len(transitions) != 2:
            if len(transitions) > 2:
                # Keep the two strongest boundaries in the robust profile.
                transitions = transitions[:2]
            elif len(transitions) == 1:
                transitions.append(
                    (transitions[0] + len(states) // 2) % len(states)
                )
                transitions.sort()

        phases: list[EventPhase] = []
        boundary_count = (
            2 if len(self.groups) == 2 else len(transitions)
        )
        for offset in range(boundary_count):
            start_idx = transitions[offset]
            end_idx = transitions[(offset + 1) % len(transitions)]
            state = int(states[start_idx])
            phases.append(
                self._make_phase(
                    phase_id=offset + 1,
                    start_idx=start_idx,
                    end_idx=end_idx,
                    state=state,
                    counts=counts,
                    cycle_seconds=cycle_seconds,
                )
            )
        return phases

    def _make_phase(
        self,
        *,
        phase_id: int,
        start_idx: int,
        end_idx: int,
        state: int,
        counts: np.ndarray,
        cycle_seconds: float,
    ) -> EventPhase:
        indices = self._interval_indices(
            start_idx,
            end_idx,
            counts.shape[-1],
        )
        group_counts = counts[:, state, indices].sum(axis=(0, 1))
        contradiction_counts = counts[
            :,
            [index for index in range(len(self.groups)) if index != state],
            indices,
        ].sum()

        supporting = int(group_counts)
        contradictory = int(contradiction_counts)
        total = supporting + contradictory
        confidence = supporting / total if total else 0.0
        group = self.groups[state]

        return EventPhase(
            phase_id=phase_id,
            phase_start=round(start_idx * self.bin_seconds, 2),
            phase_end=round(end_idx * self.bin_seconds, 2),
            active_approaches=group.approaches,
            confidence=round(float(np.clip(confidence, 0.0, 1.0)), 4),
            supporting_event_count=supporting,
            contradictory_event_count=contradictory,
            members=tuple(group.approaches),
        )

    @staticmethod
    def _interval_indices(start: int, end: int, size: int) -> list[int]:
        if start == end:
            return list(range(size))
        if start < end:
            return list(range(start, end))
        return list(range(start, size)) + list(range(0, end))

    @staticmethod
    def _cycle_coverage(
        phases: Sequence[EventPhase],
        cycle_seconds: float,
    ) -> float:
        covered = 0.0
        for phase in phases:
            if phase.phase_start <= phase.phase_end:
                covered += phase.phase_end - phase.phase_start
            else:
                covered += cycle_seconds - phase.phase_start + phase.phase_end
        return min(1.0, max(0.0, covered / cycle_seconds))


def discover_event_phases(
    events: Iterable[TrajectoryEvent],
    cycle_seconds: float,
) -> EventPhaseDiscoveryResult:
    return EventPhaseDiscovery().discover(events, cycle_seconds=cycle_seconds)
