from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Sequence

import numpy as np

from app.core.event_cycle_estimator import estimate_event_cycle
from app.core.intersection_config import (
    IntersectionConfig,
    Movement,
    SignalHead,
)
from app.core.intersection_topology import SignalFamily
from app.core.models import EventType, TrajectoryEvent


@dataclass(frozen=True)
class CycleCandidate:
    period_seconds: float
    score: float
    movement_score: float
    separation_score: float
    aggregate_score: float = 0.0
    consistency_score: float = 0.0
    fragmentation_score: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MovementProfile:
    movement: str
    approach: str
    event_count: int
    observed_cycles: int
    presence_peak: float
    confidence: float
    activation_intervals: tuple[tuple[float, float], ...]
    mask: tuple[bool, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "movement": self.movement,
            "approach": self.approach,
            "event_count": self.event_count,
            "observed_cycles": self.observed_cycles,
            "presence_peak": round(self.presence_peak, 4),
            "confidence": round(self.confidence, 4),
            "activation_intervals": [
                [round(start, 2), round(end, 2)]
                for start, end in self.activation_intervals
            ],
        }


@dataclass(frozen=True)
class InferredSignalHead:
    id: str
    approach: str
    movement_ids: tuple[str, ...]
    additional: bool
    activation_intervals: tuple[tuple[float, float], ...]
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "approach": self.approach,
            "movement_ids": list(self.movement_ids),
            "additional": self.additional,
            "activation_intervals": [
                [round(start, 2), round(end, 2)]
                for start, end in self.activation_intervals
            ],
            "confidence": round(self.confidence, 4),
        }


@dataclass(frozen=True)
class SignalStage:
    stage_id: int
    phase_start: float
    phase_end: float
    active_heads: tuple[str, ...]
    active_movements: tuple[str, ...]
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return {
            "stage_id": self.stage_id,
            "phase_start": round(self.phase_start, 2),
            "phase_end": round(self.phase_end, 2),
            "active_heads": list(self.active_heads),
            "active_movements": list(self.active_movements),
            "confidence": round(self.confidence, 4),
        }


@dataclass(frozen=True)
class SignalPlan:
    cycle_seconds: float
    origin_timestamp_ms: int
    confidence: float
    cycle_candidates: tuple[CycleCandidate, ...]
    movement_profiles: tuple[MovementProfile, ...]
    signal_heads: tuple[InferredSignalHead, ...]
    stages: tuple[SignalStage, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "cycle_seconds": round(self.cycle_seconds, 3),
            "origin_timestamp_ms": self.origin_timestamp_ms,
            "confidence": round(self.confidence, 4),
            "cycle_candidates": [item.to_dict() for item in self.cycle_candidates],
            "movement_profiles": [item.to_dict() for item in self.movement_profiles],
            "signal_heads": [item.to_dict() for item in self.signal_heads],
            "stages": [item.to_dict() for item in self.stages],
        }

    def active_heads_at(self, phase_seconds: float) -> tuple[str, ...]:
        position = float(phase_seconds) % self.cycle_seconds
        for stage in self.stages:
            if _in_interval(
                position,
                stage.phase_start,
                stage.phase_end,
                self.cycle_seconds,
            ):
                return stage.active_heads
        return ()

    def to_intersection_config(
        self,
        *,
        intersection_id: str = "inferred-intersection",
    ) -> IntersectionConfig:
        movements = tuple(
            Movement.from_id(
                movement_id,
                kind=_movement_kind(movement_id),
            )
            for movement_id in _known_movements(self.movement_profiles)
        )
        known_ids = {movement.id for movement in movements}
        heads = tuple(
            SignalHead(
                id=head.id,
                approach=head.approach,
                movement_ids=tuple(
                    movement_id
                    for movement_id in head.movement_ids
                    if movement_id in known_ids
                ),
                additional=head.additional,
                arrows=tuple(
                    sorted(
                        {
                            _turn_direction(movement_id)
                            for movement_id in head.movement_ids
                            if movement_id in known_ids
                        }
                    )
                ),
            )
            for head in self.signal_heads
            if any(item in known_ids for item in head.movement_ids)
        )

        approaches = tuple(
            dict.fromkeys(
                movement.approach
                for movement in movements
            )
        )
        ns = tuple(item for item in approaches if item in {"N", "S"})
        ew = tuple(item for item in approaches if item in {"E", "W"})
        families: list[SignalFamily] = []
        if ns:
            families.append(SignalFamily("NS", ns))
        if ew:
            families.append(SignalFamily("EW", ew))
        family_conflicts = (("NS", "EW"),) if ns and ew else ()

        return IntersectionConfig(
            intersection_id=intersection_id,
            families=tuple(families),
            movements=movements,
            signal_heads=heads,
            family_conflicts=family_conflicts,
        )


class SignalPlanDiscovery:
    """Infer a recurring movement-level signal plan without a predeclared head map.

    This is deliberately additive to the existing production pipeline. It uses
    only RELEASE/CROSSING events, discovers the cycle from movement-specific
    periodicity, then clusters movements on each approach into physical-looking
    signal heads. A head with the largest recurring movement support is treated
    as primary; other temporally distinct clusters are additional sections.

    The result is an activation plan, not controller telemetry. Absence of a
    movement is not automatically treated as proof of RED.
    """

    def __init__(
        self,
        *,
        bin_seconds: float = 2.0,
        min_cycle_seconds: float = 20.0,
        max_cycle_seconds: float = 180.0,
        min_movement_events: int = 6,
        min_observed_cycles: int = 3,
        presence_threshold: float = 0.12,
        head_jaccard_threshold: float = 0.65,
    ) -> None:
        if bin_seconds <= 0:
            raise ValueError("bin_seconds must be positive")
        if min_cycle_seconds <= 0 or max_cycle_seconds <= min_cycle_seconds:
            raise ValueError("invalid cycle search range")
        if min_movement_events < 2:
            raise ValueError("min_movement_events must be at least 2")
        if min_observed_cycles < 2:
            raise ValueError("min_observed_cycles must be at least 2")
        if not 0 < presence_threshold < 1:
            raise ValueError("presence_threshold must be in (0, 1)")
        if not 0 < head_jaccard_threshold <= 1:
            raise ValueError("head_jaccard_threshold must be in (0, 1]")

        self.bin_seconds = float(bin_seconds)
        self.min_cycle_seconds = float(min_cycle_seconds)
        self.max_cycle_seconds = float(max_cycle_seconds)
        self.min_movement_events = int(min_movement_events)
        self.min_observed_cycles = int(min_observed_cycles)
        self.presence_threshold = float(presence_threshold)
        self.head_jaccard_threshold = float(head_jaccard_threshold)

    def discover(
        self,
        events: Iterable[TrajectoryEvent],
        *,
        cycle_seconds: float | None = None,
    ) -> SignalPlan:
        selected = self._select_events(events)
        if len(selected) < self.min_movement_events:
            raise ValueError(
                "insufficient RELEASE/CROSSING events for signal-plan discovery"
            )

        origin = min(event.timestamp_ms for event in selected)
        cycle_candidates = self._cycle_candidates(selected, origin)
        if cycle_seconds is None:
            if not cycle_candidates:
                raise ValueError("unable to estimate a recurring traffic cycle")
            cycle = cycle_candidates[0].period_seconds
        else:
            cycle = float(cycle_seconds)
            if cycle < 2 * self.bin_seconds:
                raise ValueError("cycle is too short for signal-plan discovery")
            cycle_candidates = tuple(
                [
                    CycleCandidate(
                        period_seconds=cycle,
                        score=1.0,
                        movement_score=1.0,
                        separation_score=1.0,
                        aggregate_score=1.0,
                        consistency_score=1.0,
                        fragmentation_score=1.0,
                    )
                ]
            )

        movement_profiles = self._movement_profiles(
            selected,
            origin_timestamp_ms=origin,
            cycle_seconds=cycle,
        )
        usable_profiles = tuple(
            item
            for item in movement_profiles
            if item.event_count >= self.min_movement_events
            and item.observed_cycles >= self.min_observed_cycles
            and any(item.mask)
        )
        if not usable_profiles:
            raise ValueError("no recurring movement profiles were discovered")

        heads = self._infer_heads(usable_profiles, cycle)
        stages = self._build_stages(
            heads,
            usable_profiles,
            cycle_seconds=cycle,
        )

        cycle_confidence = (
            float(cycle_candidates[0].score)
            if cycle_candidates
            else 0.0
        )
        profile_confidence = float(
            np.mean([profile.confidence for profile in usable_profiles])
        )
        head_confidence = float(
            np.mean([head.confidence for head in heads])
        )
        confidence = float(
            np.clip(
                0.45 * cycle_confidence
                + 0.35 * profile_confidence
                + 0.20 * head_confidence,
                0.0,
                1.0,
            )
        )

        return SignalPlan(
            cycle_seconds=cycle,
            origin_timestamp_ms=origin,
            confidence=round(confidence, 4),
            cycle_candidates=tuple(cycle_candidates[:8]),
            movement_profiles=usable_profiles,
            signal_heads=tuple(heads),
            stages=tuple(stages),
        )

    def _select_events(
        self,
        events: Iterable[TrajectoryEvent],
    ) -> list[TrajectoryEvent]:
        result = []
        # RELEASE is the only event here that directly represents a vehicle
        # restarting after a stop. CROSSING is intentionally excluded because
        # its timestamp may be a track-end/geometric observation rather than a
        # signal-related transition; treating it equally biases cycle origin
        # and period estimation.
        for event in events:
            if event.event_type is not EventType.RELEASE:
                continue
            movement = str(event.movement or "").strip()
            if "->" not in movement or movement.endswith("->UNKNOWN"):
                continue
            approach, destination = movement.split("->", 1)
            if not approach or not destination:
                continue
            if event.confidence <= 0.0:
                continue
            result.append(event)
        return sorted(
            result,
            key=lambda event: (
                event.timestamp_ms,
                event.movement,
                event.event_type.value,
            ),
        )

    def _cycle_candidates(
        self,
        events: Sequence[TrajectoryEvent],
        origin_timestamp_ms: int,
    ) -> list[CycleCandidate]:
        min_period = max(
            2 * self.bin_seconds,
            self.min_cycle_seconds,
        )
        max_period = min(
            self.max_cycle_seconds,
            max(
                min_period + self.bin_seconds,
                (
                    max(event.timestamp_ms for event in events)
                    - origin_timestamp_ms
                )
                / 1000.0
                / 2.0,
            ),
        )
        periods = np.arange(
            min_period,
            max_period + 0.001,
            self.bin_seconds,
        )

        # Use the existing family-level autocorrelation estimator as an
        # independent period prior. The movement-level evidence remains
        # decisive, but a candidate that agrees with both views should beat a
        # candidate that wins only because of sparse movement timing.
        aggregate_priors = self._aggregate_cycle_priors(events)

        candidates: list[CycleCandidate] = []
        for period in periods:
            metrics = self._score_period(
                events,
                origin_timestamp_ms=origin_timestamp_ms,
                cycle_seconds=float(period),
            )
            if metrics is None:
                continue
            (
                movement_score,
                separation_score,
                consistency_score,
                fragmentation_score,
                transition_score,
            ) = metrics

            aggregate_score = self._aggregate_cycle_support(
                float(period),
                aggregate_priors,
            )

            # Movement structure is the primary evidence. Aggregate
            # autocorrelation is retained as a diagnostic field, but is not
            # allowed to override a structurally simpler recurring plan.
            score = (
                0.50 * movement_score
                + 0.15 * separation_score
                + 0.15 * consistency_score
                + 0.15 * fragmentation_score
                + 0.05 * transition_score
            )
            # A tiny-transition preference is deliberately weak: it is a
            # regularizer, not a hard assumption about controller behavior.
            score += 0.02 * transition_score

            candidates.append(
                CycleCandidate(
                    period_seconds=float(period),
                    score=float(np.clip(score, 0.0, 1.0)),
                    movement_score=float(movement_score),
                    separation_score=float(separation_score),
                    aggregate_score=float(aggregate_score),
                    consistency_score=float(consistency_score),
                    fragmentation_score=float(fragmentation_score),
                )
            )

        candidates.sort(
            key=lambda item: (
                -item.score,
                -item.aggregate_score,
                -item.consistency_score,
                -item.separation_score,
                item.period_seconds,
            )
        )

        # Prefer a longer fundamental period when a shorter subharmonic has
        # essentially the same consensus score.
        if candidates:
            best = candidates[0]
            near_harmonics = [
                item
                for item in candidates
                if item.period_seconds > best.period_seconds
                and item.period_seconds
                / max(best.period_seconds, 1e-9)
                >= 1.8
                and item.period_seconds
                / max(best.period_seconds, 1e-9)
                <= 2.2
                and item.score >= best.score * 0.94
            ]
            if near_harmonics:
                best = max(
                    [best, *near_harmonics],
                    key=lambda item: item.period_seconds,
                )
                candidates.remove(best) if best in candidates[1:] else None
                candidates.insert(0, best)

        return candidates

    def _aggregate_cycle_priors(
        self,
        events: Sequence[TrajectoryEvent],
    ) -> tuple[tuple[float, float], ...]:
        try:
            estimate = estimate_event_cycle(
                events,
                sampling_seconds=self.bin_seconds,
                min_events=self.min_movement_events,
            )
        except (RuntimeError, ValueError):
            return ()

        return tuple(
            (
                float(candidate.period_seconds),
                float(candidate.score),
            )
            for candidate in estimate.estimate.candidate_periods
        )

    def _aggregate_cycle_support(
        self,
        period_seconds: float,
        priors: Sequence[tuple[float, float]],
    ) -> float:
        if not priors:
            return 0.0

        max_score = max(score for _, score in priors)
        if max_score <= 0:
            return 0.0

        # A smooth tolerance makes 98s receive meaningful support from a
        # strong 100s autocorrelation peak without hard snapping the period.
        tolerance = max(4.0, period_seconds * 0.04)
        return float(
            np.clip(
                max(
                    (
                        (score / max_score)
                        * np.exp(
                            -0.5
                            * ((period - period_seconds) / tolerance) ** 2
                        )
                        for period, score in priors
                    ),
                    default=0.0,
                ),
                0.0,
                1.0,
            )
        )

    def _score_period(
        self,
        events: Sequence[TrajectoryEvent],
        *,
        origin_timestamp_ms: int,
        cycle_seconds: float,
    ) -> tuple[float, float, float, float, float] | None:
        cycle_count = int(
            np.floor(
                (
                    max(event.timestamp_ms for event in events)
                    - origin_timestamp_ms
                )
                / 1000.0
                / cycle_seconds
            )
        ) + 1
        if cycle_count < self.min_observed_cycles:
            return None

        movement_times: dict[str, list[float]] = {}
        for event in events:
            movement_times.setdefault(event.movement, []).append(
                (event.timestamp_ms - origin_timestamp_ms) / 1000.0
            )

        weighted_scores: list[tuple[float, float]] = []
        weighted_consistency: list[tuple[float, float]] = []
        weighted_fragmentation: list[tuple[float, float]] = []
        movement_masks: dict[str, np.ndarray] = {}
        axis_masks: dict[str, np.ndarray] = {
            "NS": np.zeros(
                max(1, int(round(cycle_seconds / self.bin_seconds))),
                dtype=bool,
            ),
            "EW": np.zeros(
                max(1, int(round(cycle_seconds / self.bin_seconds))),
                dtype=bool,
            ),
        }

        for movement, times in movement_times.items():
            if len(times) < self.min_movement_events:
                continue
            matrix = self._movement_matrix(
                times,
                cycle_seconds=cycle_seconds,
                cycle_count=cycle_count,
            )
            observed_cycles = int(np.count_nonzero(matrix.sum(axis=1) > 0))
            if observed_cycles < self.min_observed_cycles:
                continue
            presence = self._smooth_circular(
                np.mean(matrix > 0, axis=0)
            )
            peak = float(np.max(presence))
            if peak <= 0:
                continue
            mask = _dominant_activation_mask(
                presence,
                threshold=max(
                    self.presence_threshold,
                    peak * 0.45,
                ),
                max_gap_bins=4,
            )
            if not np.any(mask):
                continue
            movement_masks[movement] = mask

            event_bins = np.mod(
                np.asarray(times) / self.bin_seconds,
                len(mask),
            ).astype(int)
            inside = float(np.mean(mask[event_bins]))
            compactness = float(
                np.clip(
                    (peak - float(np.mean(presence)))
                    / max(peak, 1e-9),
                    0.0,
                    1.0,
                )
            )
            support = float(
                min(
                    1.0,
                    observed_cycles / max(
                        1.0,
                        min(6, cycle_count),
                    ),
                )
            )
            movement_score = float(
                np.clip(
                    compactness
                    * inside
                    * (0.5 + 0.5 * support),
                    0.0,
                    1.0,
                )
            )
            weight = float(np.log1p(len(times)))
            weighted_scores.append((movement_score, weight))

            # Compare each populated cycle with the aggregate phase profile.
            # A real controller cycle should reproduce the same movement
            # geometry from cycle to cycle; a coincidental period tends to
            # scatter each cycle differently.
            consistency = self._movement_cycle_consistency(
                matrix,
                mask,
            )
            weighted_consistency.append((consistency, weight))

            active_runs = sum(
                1
                for start, end, active in _circular_runs(
                    [bool(item) for item in mask]
                )
                if active
            )
            fragmentation = 1.0 / max(1, active_runs)
            weighted_fragmentation.append((fragmentation, weight))

            approach = movement.split("->", 1)[0]
            axis = (
                "NS"
                if approach in {"N", "S"}
                else "EW"
                if approach in {"E", "W"}
                else None
            )
            if axis is not None:
                axis_masks[axis] |= mask

        if not weighted_scores:
            return None

        movement_score = float(
            np.average(
                np.asarray([score for score, _ in weighted_scores]),
                weights=np.asarray([weight for _, weight in weighted_scores]),
            )
        )
        consistency_score = float(
            np.average(
                np.asarray([score for score, _ in weighted_consistency]),
                weights=np.asarray([weight for _, weight in weighted_consistency]),
            )
            if weighted_consistency
            else 0.0
        )
        fragmentation_score = float(
            np.average(
                np.asarray([score for score, _ in weighted_fragmentation]),
                weights=np.asarray([weight for _, weight in weighted_fragmentation]),
            )
            if weighted_fragmentation
            else 0.0
        )

        union = axis_masks["NS"] | axis_masks["EW"]
        separation_score = (
            1.0
            if not np.any(union)
            else float(
                1.0
                - np.count_nonzero(axis_masks["NS"] & axis_masks["EW"])
                / max(1, np.count_nonzero(union))
            )
        )

        # Build a phase-label sequence from movement masks and count distinct
        # runs. Excessive fragmentation is evidence against the candidate.
        n_bins = len(union)
        phase_values: list[tuple[str, ...]] = []
        for index in range(n_bins):
            phase_values.append(
                tuple(
                    sorted(
                        movement
                        for movement, mask in movement_masks.items()
                        if mask[index]
                    )
                )
            )

        runs = _circular_runs(phase_values)
        transition_count = len(runs)
        transition_score = float(
            np.clip(
                1.0 / max(1.0, 1.0 + max(0, transition_count - 3)),
                0.0,
                1.0,
            )
        )

        return (
            movement_score,
            float(np.clip(separation_score, 0.0, 1.0)),
            consistency_score,
            fragmentation_score,
            transition_score,
        )

    def _movement_cycle_consistency(
        self,
        matrix: np.ndarray,
        aggregate_mask: np.ndarray,
    ) -> float:
        populated: list[np.ndarray] = []
        for row in matrix:
            row_mask = row > 0
            if not np.any(row_mask):
                continue
            # Compare against the aggregate activation mask using Jaccard.
            intersection = np.count_nonzero(row_mask & aggregate_mask)
            union = np.count_nonzero(row_mask | aggregate_mask)
            if union > 0:
                populated.append(intersection / union)

        if len(populated) < self.min_observed_cycles:
            return 0.0
        return float(np.clip(np.mean(populated), 0.0, 1.0))

    def _movement_profiles(
        self,
        events: Sequence[TrajectoryEvent],
        *,
        origin_timestamp_ms: int,
        cycle_seconds: float,
    ) -> list[MovementProfile]:
        movement_events: dict[str, list[TrajectoryEvent]] = {}
        for event in events:
            movement_events.setdefault(event.movement, []).append(event)

        profiles: list[MovementProfile] = []
        cycle_count = int(
            np.floor(
                (
                    max(event.timestamp_ms for event in events)
                    - origin_timestamp_ms
                )
                / 1000.0
                / cycle_seconds
            )
        ) + 1

        for movement, items in movement_events.items():
            if len(items) < self.min_movement_events:
                continue
            times = [
                (item.timestamp_ms - origin_timestamp_ms) / 1000.0
                for item in items
            ]
            matrix = self._movement_matrix(
                times,
                cycle_seconds=cycle_seconds,
                cycle_count=cycle_count,
            )
            observed_cycles = int(np.count_nonzero(matrix.sum(axis=1) > 0))
            presence = self._smooth_circular(
                np.mean(matrix > 0, axis=0)
            )
            peak = float(np.max(presence))
            if peak <= 0 or observed_cycles < self.min_observed_cycles:
                continue

            mask = presence >= max(
                self.presence_threshold,
                peak * 0.35,
            )
            mask = _fill_short_gaps_circular(mask, max_gaps=2)
            intervals = _mask_to_intervals(
                mask,
                bin_seconds=self.bin_seconds,
                cycle_seconds=cycle_seconds,
            )
            support = min(
                1.0,
                observed_cycles / max(1.0, min(6, cycle_count)),
            )
            confidence = float(
                np.clip(
                    0.55 * peak
                    + 0.25 * support
                    + 0.20 * np.mean(mask),
                    0.0,
                    1.0,
                )
            )
            approach = movement.split("->", 1)[0]
            profiles.append(
                MovementProfile(
                    movement=movement,
                    approach=approach,
                    event_count=len(items),
                    observed_cycles=observed_cycles,
                    presence_peak=peak,
                    confidence=confidence,
                    activation_intervals=tuple(intervals),
                    mask=tuple(bool(item) for item in mask),
                )
            )

        profiles.sort(
            key=lambda item: (
                item.approach,
                -item.event_count,
                item.movement,
            )
        )
        return profiles

    def _infer_heads(
        self,
        profiles: Sequence[MovementProfile],
        cycle_seconds: float,
    ) -> list[InferredSignalHead]:
        by_approach: dict[str, list[MovementProfile]] = {}
        for profile in profiles:
            by_approach.setdefault(profile.approach, []).append(profile)

        heads: list[InferredSignalHead] = []
        for approach, items in sorted(by_approach.items()):
            clusters: list[list[MovementProfile]] = []
            for profile in sorted(
                items,
                key=lambda item: (
                    -item.event_count,
                    item.movement,
                ),
            ):
                assigned = False
                for cluster in clusters:
                    reference = max(
                        cluster,
                        key=lambda item: item.event_count,
                    )
                    if _jaccard(reference.mask, profile.mask) >= self.head_jaccard_threshold:
                        cluster.append(profile)
                        assigned = True
                        break
                if not assigned:
                    clusters.append([profile])

            clusters.sort(
                key=lambda cluster: (
                    -sum(item.event_count for item in cluster),
                    min(item.movement for item in cluster),
                )
            )

            for cluster_index, cluster in enumerate(clusters):
                additional = cluster_index > 0
                suffix = f"_ADD_{cluster_index}"
                head_id = (
                    f"{approach}_MAIN"
                    if not additional
                    else f"{approach}{suffix}"
                )
                mask = np.zeros(
                    len(cluster[0].mask),
                    dtype=bool,
                )
                for profile in cluster:
                    mask |= np.asarray(profile.mask, dtype=bool)
                confidence = float(
                    np.mean([profile.confidence for profile in cluster])
                )
                heads.append(
                    InferredSignalHead(
                        id=head_id,
                        approach=approach,
                        movement_ids=tuple(
                            sorted(
                                item.movement
                                for item in cluster
                            )
                        ),
                        additional=additional,
                        activation_intervals=tuple(
                            _mask_to_intervals(
                                mask,
                                bin_seconds=self.bin_seconds,
                                cycle_seconds=cycle_seconds,
                            )
                        ),
                        confidence=confidence,
                    )
                )

        return heads

    def _build_stages(
        self,
        heads: Sequence[InferredSignalHead],
        profiles: Sequence[MovementProfile],
        *,
        cycle_seconds: float,
    ) -> list[SignalStage]:
        if not heads:
            return []

        n_bins = len(profiles[0].mask)
        head_masks: dict[str, np.ndarray] = {}
        for head in heads:
            mask = np.zeros(n_bins, dtype=bool)
            for profile in profiles:
                if profile.movement in head.movement_ids:
                    mask |= np.asarray(profile.mask, dtype=bool)
            head_masks[head.id] = mask

        stage_values: list[tuple[str, ...]] = []
        for index in range(n_bins):
            active = tuple(
                head.id
                for head in heads
                if head_masks[head.id][index]
            )
            stage_values.append(active)

        stage_values = _smooth_stage_values(stage_values, max_run_bins=2)
        runs = _circular_runs(stage_values)
        stages: list[SignalStage] = []
        stage_id = 1
        for start, end, active in runs:
            if not active:
                continue
            movement_ids = tuple(
                sorted(
                    {
                        movement_id
                        for head in heads
                        if head.id in active
                        for movement_id in head.movement_ids
                    }
                )
            )
            confidence = float(
                np.mean(
                    [
                        head.confidence
                        for head in heads
                        if head.id in active
                    ]
                )
            )
            stages.append(
                SignalStage(
                    stage_id=stage_id,
                    phase_start=start * self.bin_seconds,
                    phase_end=end * self.bin_seconds,
                    active_heads=tuple(active),
                    active_movements=movement_ids,
                    confidence=confidence,
                )
            )
            stage_id += 1

        return stages

    def _movement_matrix(
        self,
        times: Sequence[float],
        *,
        cycle_seconds: float,
        cycle_count: int,
    ) -> np.ndarray:
        n_bins = max(
            1,
            int(round(cycle_seconds / self.bin_seconds)),
        )
        matrix = np.zeros((cycle_count, n_bins), dtype=int)
        for time_s in times:
            cycle_id = min(
                cycle_count - 1,
                max(0, int(np.floor(time_s / cycle_seconds))),
            )
            phase = time_s % cycle_seconds
            bin_id = min(
                n_bins - 1,
                int(np.floor(phase / self.bin_seconds)),
            )
            matrix[cycle_id, bin_id] += 1
        return matrix

    def _smooth_circular(self, values: np.ndarray) -> np.ndarray:
        values = np.asarray(values, dtype=float)
        if values.size < 3:
            return values.copy()
        return (
            np.roll(values, 1)
            + 2.0 * values
            + np.roll(values, -1)
        ) / 4.0



def _known_movements(
    profiles: Sequence[MovementProfile],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            profile.movement
            for profile in profiles
            if "->" in profile.movement
            and not profile.movement.endswith("->UNKNOWN")
        )
    )


def _movement_kind(movement_id: str) -> str:
    approach, destination = movement_id.split("->", 1)
    if approach == destination:
        return "uturn"
    if {approach, destination} in (
        {"N", "S"},
        {"E", "W"},
    ):
        return "through"
    return "turn"


def _turn_direction(movement_id: str) -> str:
    approach, destination = movement_id.split("->", 1)
    right_turns = {
        ("N", "W"),
        ("E", "S"),
        ("S", "E"),
        ("W", "N"),
    }
    left_turns = {
        ("N", "E"),
        ("E", "N"),
        ("S", "W"),
        ("W", "S"),
    }
    if (approach, destination) in right_turns:
        return "right"
    if (approach, destination) in left_turns:
        return "left"
    if (approach, destination) in {("N", "S"), ("S", "N"), ("E", "W"), ("W", "E")}:
        return "straight"
    return "uturn"


def _in_interval(
    value: float,
    start: float,
    end: float,
    cycle: float,
) -> bool:
    value %= cycle
    start %= cycle
    end %= cycle
    if start == end:
        return True
    if start < end:
        return start <= value < end
    return value >= start or value < end


def _jaccard(left: Sequence[bool], right: Sequence[bool]) -> float:
    a = np.asarray(left, dtype=bool)
    b = np.asarray(right, dtype=bool)
    union = int(np.count_nonzero(a | b))
    if union == 0:
        return 0.0
    return float(np.count_nonzero(a & b) / union)


def _fill_short_gaps_circular(
    mask: np.ndarray,
    *,
    max_gaps: int,
) -> np.ndarray:
    values = np.asarray(mask, dtype=bool).copy()
    if values.size == 0 or max_gaps <= 0:
        return values
    for _ in range(max_gaps):
        values = values | (
            ~values
            & np.roll(values, 1)
            & np.roll(values, -1)
        )
    return values


def _dominant_activation_mask(
    presence: np.ndarray,
    *,
    threshold: float,
    max_gap_bins: int,
) -> np.ndarray:
    values = np.asarray(presence, dtype=float)
    if values.size == 0:
        return np.zeros(0, dtype=bool)
    mask = values >= float(threshold)
    mask = _fill_short_gaps_circular(mask, max_gaps=max_gap_bins)
    if np.any(mask):
        return mask
    result = np.zeros_like(mask, dtype=bool)
    result[int(np.argmax(values))] = True
    return result


def _smooth_stage_values(
    values: Sequence[tuple[str, ...]],
    *,
    max_run_bins: int,
) -> list[tuple[str, ...]]:
    result = list(values)
    n = len(result)
    if n < 3 or max_run_bins <= 0:
        return result

    for _ in range(max_run_bins):
        runs = _circular_runs(result)
        for start, end, value in runs:
            length = end - start if start <= end else (n - start) + end
            if length > max_run_bins:
                continue
            previous = result[(start - 1) % n]
            following = result[end % n]
            replacement = following if following == previous else (
                previous if len(previous) >= len(following) else following
            )
            index = start
            for _ in range(length):
                result[index] = replacement
                index = (index + 1) % n
    return result


def _mask_to_intervals(
    mask: Sequence[bool],
    *,
    bin_seconds: float,
    cycle_seconds: float,
) -> list[tuple[float, float]]:
    values = np.asarray(mask, dtype=bool)
    n = len(values)
    if n == 0 or not np.any(values):
        return []
    if np.all(values):
        return [(0.0, cycle_seconds)]

    runs = _circular_runs([bool(item) for item in values])
    return [
        (
            start * bin_seconds,
            min(end * bin_seconds, cycle_seconds),
        )
        for start, end, active in runs
        if active
    ]


def _circular_runs(
    values: Sequence[object],
) -> list[tuple[int, int, object]]:
    n = len(values)
    if n == 0:
        return []

    runs: list[tuple[int, int, object]] = []
    start = 0
    current = values[0]
    for index in range(1, n):
        if values[index] != current:
            runs.append((start, index, current))
            start = index
            current = values[index]
    runs.append((start, n, current))

    if len(runs) > 1 and runs[0][2] == runs[-1][2]:
        first = runs[0]
        last = runs[-1]
        runs = [
            (last[0], first[1], first[2]),
            *runs[1:-1],
        ]
    return runs


__all__ = [
    "CycleCandidate",
    "InferredSignalHead",
    "MovementProfile",
    "SignalPlan",
    "SignalPlanDiscovery",
    "SignalStage",
]
