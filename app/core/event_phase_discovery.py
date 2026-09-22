from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Sequence

import numpy as np

from app.core.models import EventType, TrajectoryEvent


@dataclass(frozen=True)
class PhaseGroup:
    name: str
    approaches: tuple[str, ...]


# Production inference treats every approach as an independent activation
# channel. Compatible approaches may overlap in time and are converted into
# ordered recurring stages afterwards.
DEFAULT_PHASE_GROUPS = (
    PhaseGroup("N", ("N",)),
    PhaseGroup("S", ("S",)),
    PhaseGroup("E", ("E",)),
    PhaseGroup("W", ("W",)),
)

VERTICAL_APPROACHES = frozenset({"N", "S"})
HORIZONTAL_APPROACHES = frozenset({"E", "W"})


@dataclass(frozen=True)
class EventPhaseProfile:
    group: str
    values: tuple[float, ...]
    event_counts: tuple[int, ...]
    cycle_count: int
    usable_event_count: int = 0
    observed_cycle_count: int = 0
    reliability: float = 0.0


@dataclass(frozen=True)
class MovementActivationCandidate:
    """Recurring movement interval excluded from the main approach mask."""

    approach: str
    movement: str
    phase_start: float
    phase_end: float
    repeatability: float
    stability: float
    usable_event_count: int
    observed_cycle_count: int
    score: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MovementSignalStage:
    """Conservatively promoted recurring signal interval for one movement."""

    movement_stage_id: int
    approach: str
    movement: str
    phase_start: float
    phase_end: float
    confidence: float
    repeatability: float
    stability: float
    supporting_event_count: int
    observed_cycle_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PhaseBoundaryRecovery:
    """Bins recovered from a reliable coarse conflict-family schedule."""

    axis: str
    phase_start: float
    phase_end: float
    active_approaches: tuple[str, ...]
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class EventPhase:
    """One non-overlapping recurring signal stage.

    active_approaches may contain one approach, a compatible overlap such as
    N+S, or any other set supported by a future/custom group configuration.
    Gaps between stages are intentionally left uncovered and mean UNKNOWN /
    clearance rather than an invented green state.
    """

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
    distinct_movement_candidates: tuple[
        MovementActivationCandidate, ...
    ] = ()
    movement_stages: tuple[MovementSignalStage, ...] = ()
    boundary_recoveries: tuple[PhaseBoundaryRecovery, ...] = ()
    boundary_recovered_fraction: float = 0.0

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
            "distinct_movement_candidates": [
                candidate.to_dict()
                for candidate in self.distinct_movement_candidates
            ],
            "movement_stages": [
                stage.to_dict()
                for stage in self.movement_stages
            ],
            "boundary_recoveries": [
                recovery.to_dict()
                for recovery in self.boundary_recoveries
            ],
            "boundary_recovered_fraction": (
                self.boundary_recovered_fraction
            ),
        }


class EventPhaseDiscovery:
    """Infer recurring signal stages from RELEASE/CROSSING evidence.

    Each configured group is inferred independently. The production defaults
    are N, S, E and W, so opposite approaches are not forced to start at the
    same time. Independent activation masks are then segmented into ordered
    non-overlapping stages such as {N} -> {N,S} -> UNKNOWN -> {E,W}.

    Sparse but repeatedly observed point evidence is deliberately handled by
    a conservative axis-envelope fallback. Weak/non-repeating evidence does
    not create a minimum-duration stage: the affected interval remains
    UNKNOWN instead.
    """

    RELEASE_WEIGHT = 1.0
    CROSSING_WEIGHT = 0.5
    MIN_GROUP_WEIGHT = 0.5
    UNCERTAIN_DURATION_PRIOR = 0.10
    MIN_GROUP_RELIABILITY = 0.35
    DIRECT_TEMPORAL_COVERAGE = 0.12
    PRESENCE_THRESHOLD_FRACTION = 0.20
    PRESENCE_ABSOLUTE_FLOOR = 0.08
    PRESENCE_DILATION_BINS = 1
    MAX_INTERNAL_GAP_BINS = 2
    MIN_MOVEMENT_REPEATABILITY = 0.35
    MIN_MOVEMENT_STABILITY = 0.60
    MIN_MOVEMENT_EVENTS = 6
    MOVEMENT_COMPATIBILITY_JACCARD = 0.60
    MAIN_AXIS_RESTORE_MIN_RECALL = 0.55
    MOVEMENT_STAGE_MIN_REPEATABILITY = 0.75
    MOVEMENT_STAGE_MIN_STABILITY = 0.85
    MOVEMENT_STAGE_MIN_EVENTS = 40
    MOVEMENT_STAGE_MIN_CYCLES = 8
    MOVEMENT_STAGE_MIN_OUTSIDE_SECONDS = 10.0
    MOVEMENT_STAGE_BOUNDARY_ALIGNMENT_SECONDS = 4.0
    MOVEMENT_STAGE_MIN_BOUNDARY_SEPARATION_SECONDS = 10.0
    MOVEMENT_STAGE_MAX_SEPARATE_OVERLAP = 0.25
    MOVEMENT_STAGE_MAX_CYCLE_FRACTION = 0.70
    BOUNDARY_RECOVERY_MIN_AXIS_RELIABILITY = 0.70
    BOUNDARY_RECOVERY_MIN_OBSERVED_CYCLES = 8
    BOUNDARY_RECOVERY_MAX_GAP_FRACTION = 0.20
    BOUNDARY_RECOVERY_MAX_SECONDS = 20.0

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

        all_approaches = [
            approach
            for group in groups
            for approach in group.approaches
        ]
        if len(set(all_approaches)) != len(all_approaches):
            raise ValueError(
                "an approach may belong to only one discovery group"
            )

        self.bin_seconds = float(bin_seconds)
        self.min_phase_bins = max(
            1,
            int(round(min_phase_seconds / bin_seconds)),
        )
        self.groups = tuple(groups)
        self.min_event_confidence = float(min_event_confidence)
        self._group_by_approach = {
            approach: group.name
            for group in self.groups
            for approach in group.approaches
        }
        self._group_index = {
            group.name: index
            for index, group in enumerate(self.groups)
        }

    def discover(
        self,
        events: Iterable[TrajectoryEvent],
        *,
        cycle_seconds: float,
    ) -> EventPhaseDiscoveryResult:
        events = list(events)
        selected = self._selected_events(events)
        if not selected:
            raise ValueError("no usable RELEASE/CROSSING events")
        origin_timestamp_ms = min(
            event.timestamp_ms
            for event in selected
        )
        raw_evidence, raw_counts = self._phase_matrices(
            selected,
            cycle_seconds=cycle_seconds,
            origin_timestamp_ms=origin_timestamp_ms,
        )

        (
            profiles,
            evidence,
            counts,
            distinct_movement_candidates,
        ) = self._build_phase_inputs(
            events,
            cycle_seconds=cycle_seconds,
        )
        (
            active_masks,
            raw_backed_groups,
        ) = self._activation_masks_with_sources(
            evidence,
            counts,
            fallback_evidence=raw_evidence,
            fallback_counts=raw_counts,
        )
        stages = self._stage_sets(active_masks)
        raw_observed_mask = self._observed_cycle_mask(raw_counts)
        coarse_axes = self._axis_envelopes(
            raw_evidence,
            raw_counts,
            raw_observed_mask,
        )
        (
            stages,
            boundary_recoveries,
            recovered_fraction,
        ) = self._recover_boundary_gaps(
            stages,
            coarse_axes=coarse_axes,
            raw_counts=raw_counts,
            observed_mask=raw_observed_mask,
            movement_candidates=distinct_movement_candidates,
            cycle_seconds=cycle_seconds,
        )
        stage_counts = self._stage_count_evidence(
            counts,
            raw_counts,
            raw_backed_groups,
        )
        phases = self._build_stages(
            stages,
            stage_counts,
            cycle_seconds,
        )
        if not phases:
            raise ValueError(
                "insufficient repeated evidence for a signal stage"
            )
        movement_stages = self._promote_movement_candidates(
            distinct_movement_candidates,
            phases,
            cycle_seconds=cycle_seconds,
        )
        coverage = self._cycle_coverage(
            phases,
            cycle_seconds,
        )
        return EventPhaseDiscoveryResult(
            cycle_seconds=float(cycle_seconds),
            bin_seconds=self.bin_seconds,
            phases=tuple(phases),
            profiles=tuple(profiles),
            cycle_coverage=round(coverage, 4),
            # EventPhase objects are disjoint recurring stages. Compatible
            # approach overlap is represented inside active_approaches.
            overlap=0.0,
            supporting_event_count=sum(
                phase.supporting_event_count
                for phase in phases
            ),
            contradictory_event_count=sum(
                phase.contradictory_event_count
                for phase in phases
            ),
            origin_timestamp_ms=origin_timestamp_ms,
            distinct_movement_candidates=tuple(
                distinct_movement_candidates
            ),
            movement_stages=tuple(movement_stages),
            boundary_recoveries=tuple(boundary_recoveries),
            boundary_recovered_fraction=round(
                recovered_fraction,
                4,
            ),
        )

    def _selected_events(
        self,
        events: Iterable[TrajectoryEvent],
    ) -> list[TrajectoryEvent]:
        return [
            event
            for event in events
            if event.event_type
            in {EventType.RELEASE, EventType.CROSSING}
            and event.confidence >= self.min_event_confidence
            and event.approach in self._group_by_approach
        ]

    def build_profiles(
        self,
        events: Iterable[TrajectoryEvent],
        *,
        cycle_seconds: float,
    ) -> tuple[
        list[EventPhaseProfile],
        np.ndarray,
        np.ndarray,
    ]:
        profiles, evidence, counts, _ = self._build_phase_inputs(
            events,
            cycle_seconds=cycle_seconds,
        )
        return profiles, evidence, counts

    def _build_phase_inputs(
        self,
        events: Iterable[TrajectoryEvent],
        *,
        cycle_seconds: float,
    ) -> tuple[
        list[EventPhaseProfile],
        np.ndarray,
        np.ndarray,
        list[MovementActivationCandidate],
    ]:
        if cycle_seconds < 2 * self.bin_seconds:
            raise ValueError(
                "cycle is too short for event phase discovery"
            )

        selected = self._selected_events(events)
        if not selected:
            raise ValueError("no usable RELEASE/CROSSING events")

        origin_ms = min(event.timestamp_ms for event in selected)
        (
            main_events,
            distinct_candidates,
        ) = self._select_main_movement_events(
            selected,
            cycle_seconds=cycle_seconds,
            origin_timestamp_ms=origin_ms,
        )
        if not main_events:
            raise ValueError("no usable main-movement phase evidence")

        evidence, counts = self._phase_matrices(
            main_events,
            cycle_seconds=cycle_seconds,
            origin_timestamp_ms=origin_ms,
        )

        observed_cycle_mask = self._observed_cycle_mask(counts)
        profiles = self._profiles_for_groups(
            evidence,
            counts,
            observed_cycle_mask,
        )
        profiles.extend(
            self._axis_compatibility_profiles(
                evidence,
                counts,
                observed_cycle_mask,
                existing_names={
                    profile.group
                    for profile in profiles
                },
            )
        )
        return (
            profiles,
            evidence,
            counts,
            distinct_candidates,
        )

    def _phase_matrices(
        self,
        events: Sequence[TrajectoryEvent],
        *,
        cycle_seconds: float,
        origin_timestamp_ms: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Build approach evidence matrices against one stable cycle origin."""
        if not events:
            raise ValueError("no usable phase evidence")

        n_bins = max(
            1,
            int(round(cycle_seconds / self.bin_seconds)),
        )
        cycle_ids = np.floor(
            (
                np.asarray(
                    [event.timestamp_ms for event in events],
                    dtype=float,
                )
                - origin_timestamp_ms
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
        for event, cycle_id in zip(events, cycle_ids):
            relative_s = (
                (event.timestamp_ms - origin_timestamp_ms) / 1000.0
            ) % cycle_seconds
            bin_id = min(
                int(relative_s / self.bin_seconds),
                n_bins - 1,
            )
            group_id = self._group_index[
                self._group_by_approach[event.approach]
            ]
            weight = (
                self.RELEASE_WEIGHT
                if event.event_type == EventType.RELEASE
                else self.CROSSING_WEIGHT
            )
            weight *= float(np.clip(event.confidence, 0.0, 1.0))
            evidence[cycle_id, group_id, bin_id] += weight
            counts[cycle_id, group_id, bin_id] += 1
        return evidence, counts

    def _select_main_movement_events(
        self,
        selected: Sequence[TrajectoryEvent],
        *,
        cycle_seconds: float,
        origin_timestamp_ms: int,
    ) -> tuple[
        list[TrajectoryEvent],
        list[MovementActivationCandidate],
    ]:
        """Keep the dominant compatible movement cluster for each approach.

        A secondary movement may be perfectly recurring yet obey a different
        signal window (for example a protected turn). Such a movement is
        retained as a distinct candidate for the later movement-specific
        stage, but it must not widen the main approach green interval.
        """
        n_bins = max(
            1,
            int(round(cycle_seconds / self.bin_seconds)),
        )
        cycle_ids = np.floor(
            (
                np.asarray(
                    [event.timestamp_ms for event in selected],
                    dtype=float,
                )
                - origin_timestamp_ms
            )
            / 1000.0
            / cycle_seconds
        ).astype(int)
        cycle_count = int(cycle_ids.max()) + 1

        by_approach: dict[
            str,
            dict[str, list[tuple[TrajectoryEvent, int, int]]],
        ] = {}
        for event, cycle_id in zip(selected, cycle_ids):
            relative_s = (
                (event.timestamp_ms - origin_timestamp_ms)
                / 1000.0
            ) % cycle_seconds
            bin_id = min(
                int(relative_s / self.bin_seconds),
                n_bins - 1,
            )
            movement = event.movement or f"{event.approach}->UNKNOWN"
            by_approach.setdefault(
                event.approach,
                {},
            ).setdefault(
                movement,
                [],
            ).append((event, int(cycle_id), bin_id))

        selected_movements: dict[str, set[str]] = {}
        distinct: list[MovementActivationCandidate] = []

        for approach, movement_items in by_approach.items():
            approach_cycles = {
                cycle_id
                for items in movement_items.values()
                for _event, cycle_id, _bin_id in items
            }
            total_approach_cycles = max(1, len(approach_cycles))
            records: list[dict[str, object]] = []

            for movement, items in movement_items.items():
                matrix = np.zeros(
                    (cycle_count, n_bins),
                    dtype=int,
                )
                for _event, cycle_id, bin_id in items:
                    matrix[cycle_id, bin_id] += 1

                movement_cycle_mask = matrix.sum(axis=1) > 0
                movement_cycles = int(
                    np.count_nonzero(movement_cycle_mask)
                )
                usable_events = int(matrix.sum())
                if movement_cycles:
                    presence = np.mean(
                        matrix[movement_cycle_mask] > 0,
                        axis=0,
                    )
                else:
                    presence = np.zeros(n_bins, dtype=float)

                mask = self._direct_presence_mask(presence)
                mask_bins = int(np.count_nonzero(mask))
                inside_events = int(matrix[:, mask].sum()) if mask_bins else 0
                repeatability = movement_cycles / total_approach_cycles
                stability = (
                    inside_events / usable_events
                    if usable_events
                    else 0.0
                )
                strong = (
                    movement_cycles >= 3
                    and usable_events >= self.MIN_MOVEMENT_EVENTS
                    and repeatability >= self.MIN_MOVEMENT_REPEATABILITY
                    and stability >= self.MIN_MOVEMENT_STABILITY
                    and mask_bins >= self.min_phase_bins
                )
                records.append(
                    {
                        "movement": movement,
                        "mask": mask,
                        "usable_events": usable_events,
                        "movement_cycles": movement_cycles,
                        "repeatability": float(repeatability),
                        "stability": float(stability),
                        "mask_bins": mask_bins,
                        "strong": strong,
                    }
                )

            strong_records = [
                record
                for record in records
                if bool(record["strong"])
            ]
            if not strong_records:
                # Preserve the old conservative reliability path when no
                # movement is strong enough to define a main signal window.
                selected_movements[approach] = set(movement_items)
                continue

            strong_total_events = max(
                1,
                sum(
                    int(record["usable_events"])
                    for record in strong_records
                ),
            )
            strong_total_mask_bins = max(
                1,
                sum(
                    int(record["mask_bins"])
                    for record in strong_records
                ),
            )
            for record in strong_records:
                volume_share = (
                    int(record["usable_events"])
                    / strong_total_events
                )
                coverage_share = (
                    int(record["mask_bins"])
                    / strong_total_mask_bins
                )
                # A main approach movement should explain a substantial share
                # of both traffic volume and the recurring activation window.
                # This prevents a narrow, exceptionally stable turn from
                # displacing the broader through movement on long archives.
                score = (
                    0.35 * float(record["repeatability"])
                    + 0.20 * float(record["stability"])
                    + 0.30 * volume_share
                    + 0.15 * coverage_share
                )
                record["score"] = float(score)

            primary = max(
                strong_records,
                key=lambda record: (
                    float(record["score"]),
                    int(record["usable_events"]),
                    str(record["movement"]),
                ),
            )
            primary_mask = np.asarray(
                primary["mask"],
                dtype=bool,
            )

            compatible: set[str] = set()
            for record in strong_records:
                mask = np.asarray(record["mask"], dtype=bool)
                union = int(np.count_nonzero(primary_mask | mask))
                intersection = int(
                    np.count_nonzero(primary_mask & mask)
                )
                jaccard = (
                    intersection / union
                    if union
                    else 0.0
                )
                if (
                    record is primary
                    or jaccard >= self.MOVEMENT_COMPATIBILITY_JACCARD
                ):
                    compatible.add(str(record["movement"]))
                    continue

                start_s, end_s = self._mask_interval_seconds(mask)
                distinct.append(
                    MovementActivationCandidate(
                        approach=approach,
                        movement=str(record["movement"]),
                        phase_start=start_s,
                        phase_end=end_s,
                        repeatability=round(
                            float(record["repeatability"]),
                            4,
                        ),
                        stability=round(
                            float(record["stability"]),
                            4,
                        ),
                        usable_event_count=int(
                            record["usable_events"]
                        ),
                        observed_cycle_count=int(
                            record["movement_cycles"]
                        ),
                        score=round(
                            float(record["score"]),
                            4,
                        ),
                    )
                )

            selected_movements[approach] = compatible

        main_events = [
            event
            for event in selected
            if (
                (event.movement or f"{event.approach}->UNKNOWN")
                in selected_movements.get(
                    event.approach,
                    {
                        event.movement
                        or f"{event.approach}->UNKNOWN"
                    },
                )
            )
        ]
        distinct.sort(
            key=lambda item: (
                item.approach,
                -item.score,
                item.movement,
            )
        )
        return main_events, distinct

    def _promote_movement_candidates(
        self,
        candidates: Sequence[MovementActivationCandidate],
        phases: Sequence[EventPhase],
        *,
        cycle_seconds: float,
    ) -> list[MovementSignalStage]:
        """Promote only strong movements with a distinct signal boundary.

        A narrow recurring traffic window inside a wider approach green is not
        enough by itself: sparse demand can create the same pattern. Promotion
        therefore requires evidence that the movement interval crosses a main
        approach boundary, occupies a mostly separate window, or shares one
        main boundary while the other boundary is materially separated.
        """
        n_bins = max(
            1,
            int(round(cycle_seconds / self.bin_seconds)),
        )
        promoted: list[MovementSignalStage] = []

        for candidate in candidates:
            if (
                candidate.repeatability
                < self.MOVEMENT_STAGE_MIN_REPEATABILITY
                or candidate.stability
                < self.MOVEMENT_STAGE_MIN_STABILITY
                or candidate.usable_event_count
                < self.MOVEMENT_STAGE_MIN_EVENTS
                or candidate.observed_cycle_count
                < self.MOVEMENT_STAGE_MIN_CYCLES
            ):
                continue

            # start == end is ambiguous here: the interval helper interprets
            # it as a full cycle, while realtime interval checks interpret it
            # as empty. Never publish that representation as a signal stage.
            if self._same_cycle_boundary(
                candidate.phase_start,
                candidate.phase_end,
                cycle_seconds,
            ):
                continue
            candidate_duration = (
                candidate.phase_end - candidate.phase_start
            ) % cycle_seconds
            if (
                candidate_duration
                >= cycle_seconds * self.MOVEMENT_STAGE_MAX_CYCLE_FRACTION
            ):
                # A movement-specific stage spanning most of the cycle is
                # more plausibly mixed demand / regime evidence than a
                # protected signal group. Keep it diagnostic only.
                continue

            candidate_mask = self._interval_mask(
                candidate.phase_start,
                candidate.phase_end,
                n_bins,
            )
            main_mask = np.zeros(n_bins, dtype=bool)
            for phase in phases:
                if candidate.approach not in phase.active_approaches:
                    continue
                main_mask |= self._interval_mask(
                    phase.phase_start,
                    phase.phase_end,
                    n_bins,
                )

            candidate_bins = int(np.count_nonzero(candidate_mask))
            main_bins = int(np.count_nonzero(main_mask))
            if candidate_bins <= 0 or main_bins <= 0:
                continue

            if not self._movement_interval_is_distinct(
                candidate,
                candidate_mask,
                main_mask,
                cycle_seconds=cycle_seconds,
            ):
                continue

            support_factor = min(
                1.0,
                candidate.usable_event_count
                / max(
                    1.0,
                    candidate.observed_cycle_count * 2.0,
                ),
            )
            confidence = float(
                np.clip(
                    0.45 * candidate.repeatability
                    + 0.35 * candidate.stability
                    + 0.20 * support_factor,
                    0.0,
                    1.0,
                )
            )
            promoted.append(
                MovementSignalStage(
                    movement_stage_id=len(promoted) + 1,
                    approach=candidate.approach,
                    movement=candidate.movement,
                    phase_start=candidate.phase_start,
                    phase_end=candidate.phase_end,
                    confidence=round(confidence, 4),
                    repeatability=candidate.repeatability,
                    stability=candidate.stability,
                    supporting_event_count=(
                        candidate.usable_event_count
                    ),
                    observed_cycle_count=(
                        candidate.observed_cycle_count
                    ),
                )
            )

        return promoted

    def _movement_interval_is_distinct(
        self,
        candidate: MovementActivationCandidate,
        candidate_mask: np.ndarray,
        main_mask: np.ndarray,
        *,
        cycle_seconds: float,
    ) -> bool:
        candidate_bins = int(np.count_nonzero(candidate_mask))
        if candidate_bins <= 0:
            return False

        overlap_bins = int(
            np.count_nonzero(candidate_mask & main_mask)
        )
        overlap_fraction = overlap_bins / candidate_bins
        if (
            overlap_fraction
            <= self.MOVEMENT_STAGE_MAX_SEPARATE_OVERLAP
        ):
            return True

        main_start, main_end = self._mask_interval_seconds(main_mask)
        if self._same_cycle_boundary(
            main_start,
            main_end,
            cycle_seconds,
        ):
            return False

        start_delta = self._signed_cycle_delta(
            candidate.phase_start,
            main_start,
            cycle_seconds,
        )
        end_delta = self._signed_cycle_delta(
            candidate.phase_end,
            main_end,
            cycle_seconds,
        )

        # A candidate materially crossing outside the main approach green has
        # direct temporal evidence that it is not merely a sparse subset.
        if (
            start_delta
            <= -self.MOVEMENT_STAGE_MIN_OUTSIDE_SECONDS
            or end_delta
            >= self.MOVEMENT_STAGE_MIN_OUTSIDE_SECONDS
        ):
            return True

        # Protected early/late substages often share one main-green boundary
        # but terminate well before, or begin well after, the other. Requiring
        # boundary alignment avoids promoting ordinary density windows such as
        # the Chicherina straight-flow examples.
        aligned_start = (
            abs(start_delta)
            <= self.MOVEMENT_STAGE_BOUNDARY_ALIGNMENT_SECONDS
        )
        aligned_end = (
            abs(end_delta)
            <= self.MOVEMENT_STAGE_BOUNDARY_ALIGNMENT_SECONDS
        )
        ends_materially_early = (
            end_delta
            <= -self.MOVEMENT_STAGE_MIN_BOUNDARY_SEPARATION_SECONDS
        )
        starts_materially_late = (
            start_delta
            >= self.MOVEMENT_STAGE_MIN_BOUNDARY_SEPARATION_SECONDS
        )
        return (
            aligned_start
            and ends_materially_early
        ) or (
            aligned_end
            and starts_materially_late
        )

    @staticmethod
    def _same_cycle_boundary(
        left: float,
        right: float,
        cycle_seconds: float,
    ) -> bool:
        if cycle_seconds <= 0:
            return left == right
        return abs(
            (left - right) % cycle_seconds
        ) < 1e-9

    @staticmethod
    def _signed_cycle_delta(
        value: float,
        reference: float,
        cycle_seconds: float,
    ) -> float:
        delta = (value - reference) % cycle_seconds
        if delta > cycle_seconds / 2.0:
            delta -= cycle_seconds
        return float(delta)

    def _interval_mask(
        self,
        start_s: float,
        end_s: float,
        n_bins: int,
    ) -> np.ndarray:
        mask = np.zeros(n_bins, dtype=bool)
        start = int(
            round(start_s / self.bin_seconds)
        ) % n_bins
        end = int(
            round(end_s / self.bin_seconds)
        ) % n_bins
        for index in self._interval_indices(
            start,
            end,
            n_bins,
        ):
            mask[index] = True
        return mask

    def _mask_interval_seconds(
        self,
        mask: np.ndarray,
    ) -> tuple[float, float]:
        true_runs = [
            (start, end)
            for start, end, value
            in self._circular_runs(mask.tolist())
            if bool(value)
        ]
        if not true_runs:
            return 0.0, 0.0
        start, end = max(
            true_runs,
            key=lambda run: self._run_length(
                run[0],
                run[1],
                len(mask),
            ),
        )
        return (
            round(start * self.bin_seconds, 2),
            round(end * self.bin_seconds, 2),
        )

    @staticmethod
    def _observed_cycle_mask(
        counts: np.ndarray,
    ) -> np.ndarray:
        return (
            counts.sum(axis=(1, 2))
            > 0
        )

    @staticmethod
    def _group_reliability_stats(
        counts: np.ndarray,
        observed_cycle_mask: np.ndarray,
    ) -> list[
        tuple[int, int, float]
    ]:
        total_observed_cycles = int(
            observed_cycle_mask.sum()
        )
        if total_observed_cycles <= 0:
            return [
                (0, 0, 0.0)
                for _ in range(
                    counts.shape[1]
                )
            ]

        observed_counts = counts[
            observed_cycle_mask
        ]
        stats: list[
            tuple[int, int, float]
        ] = []
        for group_id in range(
            counts.shape[1]
        ):
            events_per_cycle = (
                observed_counts[
                    :,
                    group_id,
                    :,
                ].sum(axis=1)
            )
            usable_event_count = int(
                events_per_cycle.sum()
            )
            group_observed_cycles = int(
                np.count_nonzero(
                    events_per_cycle > 0
                )
            )
            cycle_support = (
                group_observed_cycles
                / total_observed_cycles
            )
            event_support = min(
                1.0,
                usable_event_count
                / total_observed_cycles,
            )
            reliability = float(
                np.clip(
                    cycle_support
                    * event_support,
                    0.0,
                    1.0,
                )
            )
            stats.append(
                (
                    usable_event_count,
                    group_observed_cycles,
                    round(
                        reliability,
                        4,
                    ),
                )
            )
        return stats

    def _profiles_for_groups(
        self,
        evidence: np.ndarray,
        counts: np.ndarray,
        observed_cycle_mask: np.ndarray,
    ) -> list[EventPhaseProfile]:
        observed_evidence = evidence[
            observed_cycle_mask
        ]
        observed_counts = counts[
            observed_cycle_mask
        ]
        observed_cycle_count = int(
            observed_cycle_mask.sum()
        )
        reliability_stats = (
            self._group_reliability_stats(
                counts,
                observed_cycle_mask,
            )
        )

        profiles: list[
            EventPhaseProfile
        ] = []
        for group_id, group in enumerate(
            self.groups
        ):
            (
                usable_events,
                group_cycles,
                reliability,
            ) = reliability_stats[
                group_id
            ]
            profiles.append(
                EventPhaseProfile(
                    group=group.name,
                    values=tuple(
                        np.round(
                            np.median(
                                observed_evidence[
                                    :,
                                    group_id,
                                    :,
                                ],
                                axis=0,
                            ),
                            6,
                        )
                    ),
                    event_counts=tuple(
                        np.median(
                            observed_counts[
                                :,
                                group_id,
                                :,
                            ],
                            axis=0,
                        )
                        .astype(int)
                        .tolist()
                    ),
                    cycle_count=(
                        observed_cycle_count
                    ),
                    usable_event_count=(
                        usable_events
                    ),
                    observed_cycle_count=(
                        group_cycles
                    ),
                    reliability=reliability,
                )
            )
        return profiles

    def _axis_group_indices(
        self,
    ) -> dict[str, list[int]]:
        result = {
            "NS": [],
            "EW": [],
        }
        for index, group in enumerate(
            self.groups
        ):
            approaches = set(
                group.approaches
            )
            if (
                approaches
                and approaches
                <= VERTICAL_APPROACHES
            ):
                result["NS"].append(index)
            elif (
                approaches
                and approaches
                <= HORIZONTAL_APPROACHES
            ):
                result["EW"].append(index)
        return result

    def _axis_compatibility_profiles(
        self,
        evidence: np.ndarray,
        counts: np.ndarray,
        observed_cycle_mask: np.ndarray,
        *,
        existing_names: set[str],
    ) -> list[EventPhaseProfile]:
        axis_indices = (
            self._axis_group_indices()
        )
        result: list[
            EventPhaseProfile
        ] = []
        total_observed = int(
            observed_cycle_mask.sum()
        )
        for name in ("NS", "EW"):
            indices = axis_indices[
                name
            ]
            if (
                not indices
                or name in existing_names
            ):
                continue
            axis_evidence = (
                evidence[
                    :,
                    indices,
                    :,
                ].sum(axis=1)
            )
            axis_counts = (
                counts[
                    :,
                    indices,
                    :,
                ].sum(axis=1)
            )
            observed_evidence = (
                axis_evidence[
                    observed_cycle_mask
                ]
            )
            observed_counts = (
                axis_counts[
                    observed_cycle_mask
                ]
            )
            events_per_cycle = (
                observed_counts.sum(
                    axis=1
                )
            )
            usable = int(
                events_per_cycle.sum()
            )
            observed = int(
                np.count_nonzero(
                    events_per_cycle > 0
                )
            )
            reliability = (
                (
                    observed
                    / total_observed
                )
                * min(
                    1.0,
                    usable
                    / total_observed,
                )
                if total_observed
                else 0.0
            )
            result.append(
                EventPhaseProfile(
                    group=name,
                    values=tuple(
                        np.round(
                            np.median(
                                observed_evidence,
                                axis=0,
                            ),
                            6,
                        )
                    ),
                    event_counts=tuple(
                        np.median(
                            observed_counts,
                            axis=0,
                        )
                        .astype(int)
                        .tolist()
                    ),
                    cycle_count=(
                        total_observed
                    ),
                    usable_event_count=(
                        usable
                    ),
                    observed_cycle_count=(
                        observed
                    ),
                    reliability=round(
                        float(reliability),
                        4,
                    ),
                )
            )
        return result

    def _presence_mask_for_group(
        self,
        counts: np.ndarray,
        observed_mask: np.ndarray,
        group_id: int,
    ) -> np.ndarray:
        n_bins = counts.shape[-1]
        if not np.any(observed_mask):
            return np.zeros(n_bins, dtype=bool)
        observed_counts = counts[observed_mask]
        group_rows = observed_counts[:, group_id, :]
        present_rows = group_rows[group_rows.sum(axis=1) > 0]
        if len(present_rows) <= 0:
            return np.zeros(n_bins, dtype=bool)
        presence = np.mean(present_rows > 0, axis=0)
        return self._direct_presence_mask(presence)

    def _activation_masks_with_sources(
        self,
        evidence: np.ndarray,
        counts: np.ndarray,
        *,
        fallback_evidence: np.ndarray | None = None,
        fallback_counts: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Infer approach masks inside a raw, movement-agnostic axis prior.

        The NS/EW schedule is estimated before movement isolation from every
        usable RELEASE/CROSSING event. Movement-specific evidence may refine
        N versus S (or E versus W), but it cannot move an approach into the
        orthogonal conflict-family window. If movement filtering places most
        evidence outside that window, raw same-approach evidence is used as a
        recovery source inside the coarse family window.
        """
        observed_mask = self._observed_cycle_mask(counts)
        reliability_stats = self._group_reliability_stats(
            counts,
            observed_mask,
        )
        fallback_evidence = (
            evidence
            if fallback_evidence is None
            else fallback_evidence
        )
        fallback_counts = (
            counts
            if fallback_counts is None
            else fallback_counts
        )
        fallback_observed_mask = self._observed_cycle_mask(
            fallback_counts
        )
        fallback_reliability_stats = self._group_reliability_stats(
            fallback_counts,
            fallback_observed_mask,
        )

        n_groups = len(self.groups)
        n_bins = counts.shape[-1]
        result = np.zeros((n_groups, n_bins), dtype=bool)
        raw_backed = np.zeros(n_groups, dtype=bool)
        coarse_axes = self._axis_envelopes(
            fallback_evidence,
            fallback_counts,
            fallback_observed_mask,
        )

        for group_id, group in enumerate(self.groups):
            reliability = float(reliability_stats[group_id][2])
            fallback_reliability = float(
                fallback_reliability_stats[group_id][2]
            )
            direct = (
                self._presence_mask_for_group(
                    counts,
                    observed_mask,
                    group_id,
                )
                if reliability >= self.MIN_GROUP_RELIABILITY
                else np.zeros(n_bins, dtype=bool)
            )
            raw_direct = (
                self._presence_mask_for_group(
                    fallback_counts,
                    fallback_observed_mask,
                    group_id,
                )
                if fallback_reliability >= self.MIN_GROUP_RELIABILITY
                else np.zeros(n_bins, dtype=bool)
            )

            axis_name = self._axis_name(group.approaches)
            coarse_axis = coarse_axes.get(axis_name)
            if coarse_axis is None:
                # Custom/non-orthogonal group configurations keep the old
                # independent conservative behaviour.
                direct_coverage = (
                    int(np.count_nonzero(direct))
                    / max(1, n_bins)
                )
                if direct_coverage >= self.DIRECT_TEMPORAL_COVERAGE:
                    result[group_id] = direct
                continue

            constrained_direct = direct & coarse_axis
            constrained_raw = raw_direct & coarse_axis
            direct_bins = int(np.count_nonzero(direct))
            constrained_direct_bins = int(
                np.count_nonzero(constrained_direct)
            )
            constrained_raw_bins = int(
                np.count_nonzero(constrained_raw)
            )
            axis_precision = (
                constrained_direct_bins / direct_bins
                if direct_bins
                else 0.0
            )

            if constrained_direct_bins >= self.min_phase_bins:
                # Keep movement-isolated timing when it actually belongs to
                # the coarse conflict family. A badly displaced primary
                # movement is not allowed to create orthogonal overlap.
                if axis_precision >= self.MAIN_AXIS_RESTORE_MIN_RECALL:
                    result[group_id] = constrained_direct
                    continue

            if constrained_raw_bins >= self.min_phase_bins:
                result[group_id] = constrained_raw
                raw_backed[group_id] = True
                continue

            if (
                fallback_reliability >= self.MIN_GROUP_RELIABILITY
                and int(np.count_nonzero(coarse_axis))
                >= self.min_phase_bins
            ):
                # Sparse same-approach evidence still inherits the recurring
                # raw axis window rather than becoming an invented orthogonal
                # activation.
                result[group_id] = coarse_axis
                raw_backed[group_id] = True

        return result, raw_backed

    def _axis_schedule_stats(
        self,
        counts: np.ndarray,
        observed_mask: np.ndarray,
    ) -> dict[str, tuple[int, float]]:
        axis_indices = self._axis_group_indices()
        result: dict[str, tuple[int, float]] = {}
        for axis in ("NS", "EW"):
            indices = axis_indices[axis]
            if not indices:
                continue
            axis_counts = counts[:, indices, :].sum(
                axis=1,
                keepdims=True,
            )
            usable, observed, reliability = (
                self._group_reliability_stats(
                    axis_counts,
                    observed_mask,
                )[0]
            )
            _ = usable
            result[axis] = (
                int(observed),
                float(reliability),
            )
        return result

    @staticmethod
    def _stage_axis(
        active: Sequence[str],
    ) -> str | None:
        values = set(active)
        if values and values <= VERTICAL_APPROACHES:
            return "NS"
        if values and values <= HORIZONTAL_APPROACHES:
            return "EW"
        return None

    def _recover_boundary_gaps(
        self,
        stages: Sequence[tuple[str, ...]],
        *,
        coarse_axes: dict[str, np.ndarray],
        raw_counts: np.ndarray,
        observed_mask: np.ndarray,
        movement_candidates: Sequence[MovementActivationCandidate],
        cycle_seconds: float,
    ) -> tuple[
        list[tuple[str, ...]],
        list[PhaseBoundaryRecovery],
        float,
    ]:
        """Recover only cross-family boundary gaps with repeated evidence.

        The raw NS/EW schedule uses every usable RELEASE/CROSSING event and
        therefore estimates conflict-family boundaries more robustly than an
        individual approach mask. We use it only when both families recur in
        enough cycles, only for bounded gaps between *different* families, and
        never across a distinct movement candidate. Internal N -> N+S gaps
        remain UNKNOWN because filling them could erase a real staggered or
        protected stage.
        """
        result = list(stages)
        n_bins = len(result)
        if (
            n_bins <= 0
            or "NS" not in coarse_axes
            or "EW" not in coarse_axes
        ):
            return result, [], 0.0

        stats = self._axis_schedule_stats(
            raw_counts,
            observed_mask,
        )
        if any(
            axis not in stats
            or stats[axis][0]
            < self.BOUNDARY_RECOVERY_MIN_OBSERVED_CYCLES
            or stats[axis][1]
            < self.BOUNDARY_RECOVERY_MIN_AXIS_RELIABILITY
            for axis in ("NS", "EW")
        ):
            return result, [], 0.0

        max_gap_seconds = min(
            self.BOUNDARY_RECOVERY_MAX_SECONDS,
            cycle_seconds
            * self.BOUNDARY_RECOVERY_MAX_GAP_FRACTION,
        )
        max_gap_bins = max(
            1,
            int(
                round(
                    max_gap_seconds
                    / self.bin_seconds
                )
            ),
        )
        candidate_mask = np.zeros(
            n_bins,
            dtype=bool,
        )
        for candidate in movement_candidates:
            candidate_mask |= self._interval_mask(
                candidate.phase_start,
                candidate.phase_end,
                n_bins,
            )

        confidence = min(
            stats["NS"][1],
            stats["EW"][1],
        )
        recoveries: list[PhaseBoundaryRecovery] = []
        recovered_bins = 0

        for start, end, active in self._circular_runs(
            list(stages)
        ):
            if active:
                continue
            indices = self._interval_indices(
                start,
                end,
                n_bins,
            )
            if (
                not indices
                or len(indices) > max_gap_bins
                or any(candidate_mask[index] for index in indices)
            ):
                continue

            previous = result[
                (start - 1) % n_bins
            ]
            following = result[
                end % n_bins
            ]
            previous_axis = self._stage_axis(previous)
            following_axis = self._stage_axis(following)
            if (
                previous_axis is None
                or following_axis is None
                or previous_axis == following_axis
            ):
                continue

            coarse_assignment: list[str] = []
            valid = True
            for index in indices:
                if coarse_axes[previous_axis][index]:
                    axis = previous_axis
                elif coarse_axes[following_axis][index]:
                    axis = following_axis
                else:
                    valid = False
                    break
                coarse_assignment.append(axis)
            if not valid:
                continue

            axis_sequence: list[str] = []
            for axis in coarse_assignment:
                if not axis_sequence or axis_sequence[-1] != axis:
                    axis_sequence.append(axis)
            if axis_sequence not in (
                [previous_axis],
                [following_axis],
                [previous_axis, following_axis],
            ):
                continue

            if axis_sequence == [previous_axis, following_axis]:
                coarse_split = next(
                    index
                    for index, axis in enumerate(coarse_assignment)
                    if axis == following_axis
                )
            elif axis_sequence == [previous_axis]:
                coarse_split = len(indices)
            else:
                coarse_split = 0

            # The coarse two-family optimizer has a duration-balance prior.
            # In a traffic-silent boundary gap that prior must not stretch
            # one phase all the way to the opposite observed edge. Keep the
            # coarse split only when it is reasonably central; otherwise use
            # the midpoint between the last observed stage and the next one.
            midpoint_split = len(indices) // 2
            split_tolerance = max(1, len(indices) // 4)
            split = (
                coarse_split
                if abs(coarse_split - midpoint_split)
                <= split_tolerance
                else midpoint_split
            )
            if len(indices) >= 2:
                split = min(
                    len(indices) - 1,
                    max(1, split),
                )

            assignments: list[
                tuple[int, str, tuple[str, ...]]
            ] = []
            for offset, index in enumerate(indices):
                if offset < split:
                    assignments.append(
                        (
                            index,
                            previous_axis,
                            tuple(previous),
                        )
                    )
                else:
                    assignments.append(
                        (
                            index,
                            following_axis,
                            tuple(following),
                        )
                    )

            for index, _axis, stage in assignments:
                result[index] = stage
            recovered_bins += len(assignments)

            segment_start = 0
            while segment_start < len(assignments):
                axis = assignments[segment_start][1]
                stage = assignments[segment_start][2]
                segment_end = segment_start + 1
                while (
                    segment_end < len(assignments)
                    and assignments[segment_end][1] == axis
                    and assignments[segment_end][2] == stage
                ):
                    segment_end += 1
                first_index = assignments[segment_start][0]
                last_index = assignments[segment_end - 1][0]
                recovery_end = (
                    last_index + 1
                ) % n_bins
                recoveries.append(
                    PhaseBoundaryRecovery(
                        axis=axis,
                        phase_start=round(
                            first_index * self.bin_seconds,
                            2,
                        ),
                        phase_end=round(
                            recovery_end * self.bin_seconds,
                            2,
                        ),
                        active_approaches=stage,
                        confidence=round(
                            confidence,
                            4,
                        ),
                    )
                )
                segment_start = segment_end

        return (
            result,
            recoveries,
            recovered_bins / max(1, n_bins),
        )

    def _independent_activation_masks(
        self,
        evidence: np.ndarray,
        counts: np.ndarray,
        *,
        fallback_evidence: np.ndarray | None = None,
        fallback_counts: np.ndarray | None = None,
    ) -> np.ndarray:
        masks, _raw_backed = self._activation_masks_with_sources(
            evidence,
            counts,
            fallback_evidence=fallback_evidence,
            fallback_counts=fallback_counts,
        )
        return masks

    @staticmethod
    def _stage_count_evidence(
        filtered_counts: np.ndarray,
        raw_counts: np.ndarray,
        raw_backed_groups: np.ndarray,
    ) -> np.ndarray:
        """Use raw counts only for groups whose main mask required recovery."""
        cycle_count = max(
            filtered_counts.shape[0],
            raw_counts.shape[0],
        )
        group_count = filtered_counts.shape[1]
        bin_count = filtered_counts.shape[2]
        effective = np.zeros(
            (cycle_count, group_count, bin_count),
            dtype=int,
        )
        effective[
            : filtered_counts.shape[0],
            :,
            :,
        ] = filtered_counts
        for group_id, use_raw in enumerate(raw_backed_groups):
            if use_raw:
                effective[:, group_id, :] = 0
                effective[
                    : raw_counts.shape[0],
                    group_id,
                    :,
                ] = raw_counts[:, group_id, :]
        return effective

    @staticmethod
    def _axis_name(
        approaches: Sequence[str],
    ) -> str | None:
        values = set(approaches)
        if (
            values
            and values
            <= VERTICAL_APPROACHES
        ):
            return "NS"
        if (
            values
            and values
            <= HORIZONTAL_APPROACHES
        ):
            return "EW"
        return None

    def _axis_envelopes(
        self,
        evidence: np.ndarray,
        counts: np.ndarray,
        observed_mask: np.ndarray,
    ) -> dict[str, np.ndarray]:
        axis_indices = (
            self._axis_group_indices()
        )
        if (
            not axis_indices["NS"]
            or not axis_indices["EW"]
        ):
            return {}

        axis_evidence = np.stack(
            [
                evidence[
                    :,
                    axis_indices["NS"],
                    :,
                ].sum(axis=1),
                evidence[
                    :,
                    axis_indices["EW"],
                    :,
                ].sum(axis=1),
            ],
            axis=1,
        )
        axis_counts = np.stack(
            [
                counts[
                    :,
                    axis_indices["NS"],
                    :,
                ].sum(axis=1),
                counts[
                    :,
                    axis_indices["EW"],
                    :,
                ].sum(axis=1),
            ],
            axis=1,
        )
        if not np.any(
            observed_mask
        ):
            return {}

        profile = np.median(
            axis_evidence[
                observed_mask
            ],
            axis=0,
        )
        reliability_stats = (
            self._group_reliability_stats(
                axis_counts,
                observed_mask,
            )
        )
        reliabilities = np.asarray(
            [
                item[2]
                for item
                in reliability_stats
            ],
            dtype=float,
        )
        weighted = (
            self._reliability_weighted_profiles(
                profile,
                reliabilities,
            )
        )
        states = (
            self._best_two_group_schedule(
                weighted,
                reliabilities,
            )
        )
        return {
            "NS": states == 0,
            "EW": states == 1,
        }

    def _direct_presence_mask(
        self,
        presence: np.ndarray,
    ) -> np.ndarray:
        values = np.asarray(
            presence,
            dtype=float,
        )
        if (
            values.size == 0
            or float(
                np.max(values)
            )
            <= 0.0
        ):
            return np.zeros_like(
                values,
                dtype=bool,
            )

        dilated = values.copy()
        for shift in range(
            1,
            self.PRESENCE_DILATION_BINS
            + 1,
        ):
            dilated = np.maximum(
                dilated,
                np.roll(
                    values,
                    shift,
                ),
            )
            dilated = np.maximum(
                dilated,
                np.roll(
                    values,
                    -shift,
                ),
            )

        threshold = max(
            self.PRESENCE_ABSOLUTE_FLOOR,
            float(
                np.max(dilated)
            )
            * self.PRESENCE_THRESHOLD_FRACTION,
        )
        mask = (
            dilated
            >= threshold
        )
        mask = self._fill_short_false_runs(
            mask,
            self.MAX_INTERNAL_GAP_BINS,
        )
        return self._longest_true_run(
            mask
        )

    @staticmethod
    def _circular_runs(
        values: Sequence[object],
    ) -> list[
        tuple[int, int, object]
    ]:
        size = len(values)
        if size == 0:
            return []
        transitions = [
            index
            for index in range(size)
            if values[index]
            != values[
                index - 1
            ]
        ]
        if not transitions:
            return [
                (
                    0,
                    0,
                    values[0],
                )
            ]
        result: list[
            tuple[
                int,
                int,
                object,
            ]
        ] = []
        for offset, start in enumerate(
            transitions
        ):
            end = transitions[
                (
                    offset + 1
                )
                % len(
                    transitions
                )
            ]
            result.append(
                (
                    start,
                    end,
                    values[start],
                )
            )
        return result

    @staticmethod
    def _run_length(
        start: int,
        end: int,
        size: int,
    ) -> int:
        value = (
            end - start
        ) % size
        return (
            value
            if value
            else size
        )

    def _fill_short_false_runs(
        self,
        mask: np.ndarray,
        max_gap: int,
    ) -> np.ndarray:
        result = np.asarray(
            mask,
            dtype=bool,
        ).copy()
        if (
            max_gap <= 0
            or not np.any(result)
            or np.all(result)
        ):
            return result
        runs = self._circular_runs(
            result.tolist()
        )
        for start, end, value in runs:
            length = self._run_length(
                start,
                end,
                len(result),
            )
            if (
                value is False
                and length
                <= max_gap
            ):
                for index in (
                    self._interval_indices(
                        start,
                        end,
                        len(result),
                    )
                ):
                    result[
                        index
                    ] = True
        return result

    def _longest_true_run(
        self,
        mask: np.ndarray,
    ) -> np.ndarray:
        result = np.zeros_like(
            mask,
            dtype=bool,
        )
        runs = [
            (start, end)
            for start, end, value
            in self._circular_runs(
                mask.tolist()
            )
            if bool(value)
        ]
        if not runs:
            return result
        start, end = max(
            runs,
            key=lambda run: (
                self._run_length(
                    run[0],
                    run[1],
                    len(mask),
                )
            ),
        )
        for index in self._interval_indices(
            start,
            end,
            len(mask),
        ):
            result[index] = True
        return result

    def _reliability_weighted_profiles(
        self,
        profile: np.ndarray,
        reliabilities: np.ndarray,
    ) -> np.ndarray:
        weighted = np.asarray(
            profile,
            dtype=float,
        ).copy()
        n_bins = weighted.shape[1]
        uniform = np.full(
            n_bins,
            1.0
            / max(1, n_bins),
            dtype=float,
        )

        for group_index in range(
            weighted.shape[0]
        ):
            reliability = float(
                np.clip(
                    reliabilities[
                        group_index
                    ],
                    0.0,
                    1.0,
                )
            )
            total = float(
                np.sum(
                    weighted[
                        group_index
                    ]
                )
            )
            shape = (
                weighted[
                    group_index
                ]
                / total
                if total > 0.0
                else uniform
            )
            shrunk_shape = (
                reliability
                * shape
                + (
                    1.0
                    - reliability
                )
                * uniform
            )
            group_weight = (
                self.MIN_GROUP_WEIGHT
                + (
                    1.0
                    - self.MIN_GROUP_WEIGHT
                )
                * reliability
            )
            weighted[
                group_index
            ] = (
                shrunk_shape
                * group_weight
            )

        return weighted

    def _best_two_group_schedule(
        self,
        profile: np.ndarray,
        reliabilities: np.ndarray,
    ) -> np.ndarray:
        first = profile[0]
        second = profile[1]
        n_bins = len(first)
        if (
            n_bins
            < 2
            * self.min_phase_bins
        ):
            raise ValueError(
                "cycle is too short for two signal phases"
            )

        best_score = -np.inf
        best_start = 0
        best_length = (
            self.min_phase_bins
        )
        schedule_reliability = float(
            np.min(reliabilities)
            if len(reliabilities)
            else 0.0
        )
        uncertainty = 1.0 - float(
            np.clip(
                schedule_reliability,
                0.0,
                1.0,
            )
        )
        first_doubled = np.r_[
            first,
            first,
        ]
        second_doubled = np.r_[
            second,
            second,
        ]
        first_prefix = np.r_[
            0.0,
            np.cumsum(
                first_doubled
            ),
        ]
        second_prefix = np.r_[
            0.0,
            np.cumsum(
                second_doubled
            ),
        ]
        total_second = float(
            second_prefix[
                n_bins
            ]
        )

        for start in range(n_bins):
            for length in range(
                self.min_phase_bins,
                n_bins
                - self.min_phase_bins
                + 1,
            ):
                end = (
                    start
                    + length
                )
                first_inside = (
                    first_prefix[end]
                    - first_prefix[
                        start
                    ]
                )
                second_inside = (
                    second_prefix[end]
                    - second_prefix[
                        start
                    ]
                )
                score = (
                    first_inside
                    + total_second
                    - second_inside
                )
                half_cycle_bins = (
                    n_bins
                    / 2.0
                )
                duration_balance = (
                    1.0
                    - (
                        abs(
                            length
                            - half_cycle_bins
                        )
                        / max(
                            1.0,
                            half_cycle_bins,
                        )
                    )
                )
                score += (
                    self.UNCERTAIN_DURATION_PRIOR
                    * uncertainty
                    * duration_balance
                )
                if score > best_score:
                    best_score = score
                    best_start = start
                    best_length = length

        states = np.ones(
            n_bins,
            dtype=np.int8,
        )
        states[
            (
                best_start
                + np.arange(
                    best_length
                )
            )
            % n_bins
        ] = 0
        return states

    def _stage_sets(
        self,
        active_masks: np.ndarray,
    ) -> list[tuple[str, ...]]:
        n_bins = (
            active_masks.shape[1]
        )
        stages: list[
            tuple[str, ...]
        ] = []
        for bin_id in range(
            n_bins
        ):
            active: set[str] = set()
            for group_id, group in enumerate(
                self.groups
            ):
                if active_masks[
                    group_id,
                    bin_id,
                ]:
                    active.update(
                        group.approaches
                    )

            # Orthogonal vehicle approaches are treated as conflicting.
            # If noisy evidence activates both axes in the same bin, the
            # conservative answer is UNKNOWN, not an invented green stage.
            if (
                active
                & VERTICAL_APPROACHES
                and active
                & HORIZONTAL_APPROACHES
            ):
                stages.append(())
            else:
                stages.append(
                    tuple(
                        approach
                        for approach
                        in (
                            "N",
                            "S",
                            "E",
                            "W",
                        )
                        if approach
                        in active
                    )
                )

        # Tiny active runs are more likely to be weak event noise than a
        # physical recurring stage. Convert them to UNKNOWN rather than
        # stretching them to min_phase_seconds.
        for start, end, value in self._circular_runs(
            stages
        ):
            if not value:
                continue
            length = self._run_length(
                start,
                end,
                n_bins,
            )
            if (
                length
                < self.min_phase_bins
            ):
                for index in self._interval_indices(
                    start,
                    end,
                    n_bins,
                ):
                    stages[index] = ()
        return stages

    def _build_stages(
        self,
        stages: Sequence[tuple[str, ...]],
        counts: np.ndarray,
        cycle_seconds: float,
    ) -> list[EventPhase]:
        observed_cycle_mask = (
            self._observed_cycle_mask(
                counts
            )
        )
        reliability_stats = (
            self._group_reliability_stats(
                counts,
                observed_cycle_mask,
            )
        )
        group_reliability = {
            approach: float(
                reliability_stats[
                    group_id
                ][2]
            )
            for group_id, group
            in enumerate(
                self.groups
            )
            for approach
            in group.approaches
        }

        result: list[
            EventPhase
        ] = []
        phase_id = 1
        for start, end, active in self._circular_runs(
            list(stages)
        ):
            active = tuple(active)
            if not active:
                continue
            indices = self._interval_indices(
                start,
                end,
                counts.shape[-1],
            )
            active_group_indices = [
                group_id
                for group_id, group
                in enumerate(
                    self.groups
                )
                if set(
                    group.approaches
                )
                & set(active)
            ]
            inactive_group_indices = [
                group_id
                for group_id
                in range(
                    len(
                        self.groups
                    )
                )
                if group_id
                not in active_group_indices
            ]
            supporting = int(
                counts[
                    :,
                    active_group_indices,
                    :,
                ][
                    :,
                    :,
                    indices,
                ].sum()
            )
            contradictory = int(
                counts[
                    :,
                    inactive_group_indices,
                    :,
                ][
                    :,
                    :,
                    indices,
                ].sum()
            ) if inactive_group_indices else 0
            total = (
                supporting
                + contradictory
            )
            consistency = (
                supporting
                / total
                if total
                else 0.0
            )
            reliability = (
                float(
                    np.mean(
                        [
                            group_reliability.get(
                                approach,
                                0.0,
                            )
                            for approach
                            in active
                        ]
                    )
                )
                if active
                else 0.0
            )
            confidence = float(
                np.clip(
                    consistency
                    * reliability,
                    0.0,
                    1.0,
                )
            )
            result.append(
                EventPhase(
                    phase_id=phase_id,
                    phase_start=round(
                        start
                        * self.bin_seconds,
                        2,
                    ),
                    phase_end=round(
                        end
                        * self.bin_seconds,
                        2,
                    ),
                    active_approaches=active,
                    confidence=round(
                        confidence,
                        4,
                    ),
                    supporting_event_count=(
                        supporting
                    ),
                    contradictory_event_count=(
                        contradictory
                    ),
                    members=active,
                )
            )
            phase_id += 1
        return result

    @staticmethod
    def _interval_indices(
        start: int,
        end: int,
        size: int,
    ) -> list[int]:
        if start == end:
            return list(
                range(size)
            )
        if start < end:
            return list(
                range(
                    start,
                    end,
                )
            )
        return (
            list(
                range(
                    start,
                    size,
                )
            )
            + list(
                range(
                    0,
                    end,
                )
            )
        )

    @staticmethod
    def _cycle_coverage(
        phases: Sequence[EventPhase],
        cycle_seconds: float,
    ) -> float:
        covered = 0.0
        for phase in phases:
            if (
                phase.phase_start
                <= phase.phase_end
            ):
                covered += (
                    phase.phase_end
                    - phase.phase_start
                )
            else:
                covered += (
                    cycle_seconds
                    - phase.phase_start
                    + phase.phase_end
                )
        return min(
            1.0,
            max(
                0.0,
                covered
                / cycle_seconds,
            ),
        )


def discover_event_phases(
    events: Iterable[TrajectoryEvent],
    cycle_seconds: float,
) -> EventPhaseDiscoveryResult:
    return EventPhaseDiscovery().discover(
        events,
        cycle_seconds=cycle_seconds,
    )
