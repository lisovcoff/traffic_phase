from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable

from app.core.intersection_topology import (
    DEFAULT_FAMILY_APPROACHES,
    DEFAULT_INTERSECTION_TOPOLOGY,
    IntersectionTopology,
)
from app.core.models import EventType, TrajectoryEvent


# Backwards-compatible alias. Adaptive logic itself now uses topology.
AXIS_APPROACHES = DEFAULT_FAMILY_APPROACHES


class AdaptiveRealtimeMode(str, Enum):
    NORMAL = "NORMAL"
    SUSPECT = "SUSPECT"
    PHASE_EXTENSION = "PHASE_EXTENSION"
    LIVE_OVERRIDE = "LIVE_OVERRIDE"
    RECOVERY = "RECOVERY"


@dataclass(frozen=True)
class AdaptiveRealtimeDecision:
    mode: AdaptiveRealtimeMode
    expected_axis: str | None
    effective_axis: str | None
    observed_approaches: tuple[str, ...]
    confidence: float
    template_disagreement: bool
    reason: str | None
    expected_weight: float
    conflicting_weight: float
    conflicting_release_count: int
    extension_duration_seconds: float = 0.0
    extension_event_count: int = 0
    extension_peak_duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["mode"] = self.mode.value
        return data


class AdaptiveRealtimeOverride:
    """Conservative live override for temporary controller deviations.

    The validated phase template remains immutable. A live override is entered
    only after repeated RELEASE-dominant evidence from the orthogonal axis,
    away from an expected template boundary. It is therefore a temporary
    realtime hypothesis, not a learned replacement cycle.
    """

    RELEASE_WEIGHT = 1.0
    CROSSING_WEIGHT = 0.35

    def __init__(
        self,
        *,
        evidence_window_seconds: float = 8.0,
        boundary_guard_seconds: float = 3.0,
        suspect_persistence_seconds: float = 3.0,
        recovery_persistence_seconds: float = 3.0,
        min_conflicting_weight: float = 2.0,
        min_conflicting_releases: int = 2,
        min_recovery_weight: float = 2.0,
        min_recovery_releases: int = 2,
        dominance_margin: float = 0.75,
        stale_override_seconds: float = 6.0,
        min_extension_weight: float = 2.0,
        min_extension_releases: int = 2,
        extension_max_seconds: float | None = None,
        topology: IntersectionTopology | None = None,
    ) -> None:
        if evidence_window_seconds <= 0:
            raise ValueError("evidence_window_seconds must be positive")
        if boundary_guard_seconds < 0:
            raise ValueError("boundary_guard_seconds must be non-negative")
        if suspect_persistence_seconds < 0:
            raise ValueError("suspect_persistence_seconds must be non-negative")
        if recovery_persistence_seconds < 0:
            raise ValueError("recovery_persistence_seconds must be non-negative")
        if min_conflicting_weight <= 0 or min_recovery_weight <= 0:
            raise ValueError("adaptive evidence thresholds must be positive")
        if min_conflicting_releases < 1 or min_recovery_releases < 1:
            raise ValueError("adaptive release thresholds must be positive")
        if stale_override_seconds <= 0:
            raise ValueError("stale_override_seconds must be positive")
        if min_extension_weight <= 0:
            raise ValueError("min_extension_weight must be positive")
        if min_extension_releases < 1:
            raise ValueError("min_extension_releases must be positive")
        if extension_max_seconds is not None and extension_max_seconds <= 0:
            raise ValueError("extension_max_seconds must be positive")

        self.topology = topology or DEFAULT_INTERSECTION_TOPOLOGY
        self.evidence_window_seconds = float(evidence_window_seconds)
        self.boundary_guard_seconds = float(boundary_guard_seconds)
        self.suspect_persistence_seconds = float(
            suspect_persistence_seconds
        )
        self.recovery_persistence_seconds = float(
            recovery_persistence_seconds
        )
        self.min_conflicting_weight = float(min_conflicting_weight)
        self.min_conflicting_releases = int(min_conflicting_releases)
        self.min_recovery_weight = float(min_recovery_weight)
        self.min_recovery_releases = int(min_recovery_releases)
        self.dominance_margin = float(dominance_margin)
        self.stale_override_seconds = float(stale_override_seconds)
        self.min_extension_weight = float(min_extension_weight)
        self.min_extension_releases = int(min_extension_releases)
        self.extension_max_seconds = (
            float(extension_max_seconds)
            if extension_max_seconds is not None
            else None
        )

        self._mode = AdaptiveRealtimeMode.NORMAL
        self._suspect_axis: str | None = None
        self._suspect_since_ms: int | None = None
        self._override_axis: str | None = None
        self._recovery_since_ms: int | None = None
        self._last_override_evidence_ms: int | None = None
        self._extension_axis: str | None = None
        self._extension_started_ms: int | None = None
        self._extension_event_count = 0
        self._extension_peak_duration_seconds = 0.0

    @property
    def mode(self) -> AdaptiveRealtimeMode:
        return self._mode

    def reset(self) -> None:
        self._mode = AdaptiveRealtimeMode.NORMAL
        self._suspect_axis = None
        self._suspect_since_ms = None
        self._override_axis = None
        self._recovery_since_ms = None
        self._last_override_evidence_ms = None
        self._extension_axis = None
        self._extension_started_ms = None
        self._extension_event_count = 0
        self._extension_peak_duration_seconds = 0.0

    def mark_resynchronized(self) -> None:
        self.reset()

    def evaluate(
        self,
        *,
        timestamp_ms: int,
        cycle_position_s: float,
        phase: object | None,
        events: Iterable[TrajectoryEvent],
        cycle_seconds: float,
        phases: Iterable[object] | None = None,
    ) -> AdaptiveRealtimeDecision:
        expected_axis = self._phase_axis(phase)
        evidence = self._axis_evidence(events, timestamp_ms)
        expected_weight = (
            float(evidence[expected_axis]["weight"])
            if expected_axis is not None
            else 0.0
        )
        expected_releases = (
            int(evidence[expected_axis]["releases"])
            if expected_axis is not None
            else 0
        )
        conflicting_axis = self._dominant_conflicting_axis(
            expected_axis,
            evidence,
        )
        conflicting_weight = (
            float(evidence[conflicting_axis]["weight"])
            if conflicting_axis is not None
            else 0.0
        )
        conflicting_releases = (
            int(evidence[conflicting_axis]["releases"])
            if conflicting_axis is not None
            else 0
        )

        extension_axis, extension_elapsed_s = self._extension_candidate(
            phases,
            cycle_position_s,
            cycle_seconds,
            expected_axis,
        )
        extension_evidence = (
            evidence.get(extension_axis, {})
            if extension_axis is not None
            else {}
        )
        extension_weight = (
            float(extension_evidence.get("weight", 0.0))
            if extension_axis is not None
            else 0.0
        )
        extension_releases = (
            int(extension_evidence.get("releases", 0))
            if extension_axis is not None
            else 0
        )
        extension_seeded = self._has_pre_boundary_evidence(
            events,
            timestamp_ms,
            extension_axis,
            extension_elapsed_s,
        )
        strong_extension = (
            extension_axis is not None
            and extension_elapsed_s > 0.0
            and extension_elapsed_s <= cycle_seconds
            and extension_seeded
            and extension_weight >= self.min_extension_weight
            and extension_releases >= self.min_extension_releases
            and extension_weight
            >= expected_weight + self.dominance_margin
        )

        near_boundary = self._near_phase_boundary(
            phase,
            cycle_position_s,
            cycle_seconds,
        )
        same_pending = (
            self._mode == AdaptiveRealtimeMode.SUSPECT
            and self._suspect_axis == conflicting_axis
        )
        strong_conflict = (
            conflicting_axis is not None
            and conflicting_weight >= self.min_conflicting_weight
            and conflicting_releases >= self.min_conflicting_releases
            and conflicting_weight
            >= expected_weight + self.dominance_margin
            and (not near_boundary or same_pending)
        )

        if self._mode == AdaptiveRealtimeMode.NORMAL:
            if strong_extension:
                self._mode = AdaptiveRealtimeMode.SUSPECT
                self._suspect_axis = extension_axis
                self._suspect_since_ms = timestamp_ms
                self._extension_axis = extension_axis
                self._extension_started_ms = (
                    timestamp_ms
                    - int(round(extension_elapsed_s * 1000.0))
                )
                self._extension_event_count = extension_releases
            elif strong_conflict:
                self._mode = AdaptiveRealtimeMode.SUSPECT
                self._suspect_axis = conflicting_axis
                self._suspect_since_ms = timestamp_ms

        elif self._mode == AdaptiveRealtimeMode.SUSPECT:
            extension_pending = (
                self._extension_axis is not None
                and extension_axis == self._extension_axis
            )
            if extension_pending and strong_extension:
                if (
                    extension_releases >= self.min_extension_releases + 1
                    or (
                        self._suspect_since_ms is not None
                        and timestamp_ms - self._suspect_since_ms
                        >= int(self.suspect_persistence_seconds * 1000.0)
                    )
                ):
                    self._mode = AdaptiveRealtimeMode.PHASE_EXTENSION
                    self._extension_started_ms = (
                        timestamp_ms
                        - int(round(extension_elapsed_s * 1000.0))
                    )
                    self._extension_event_count = extension_releases
                    self._extension_peak_duration_seconds = max(
                        self._extension_peak_duration_seconds,
                        extension_elapsed_s,
                    )
                    self._recovery_since_ms = None
            elif self._suspect_axis == conflicting_axis and strong_conflict:
                if (
                    self._suspect_since_ms is not None
                    and timestamp_ms - self._suspect_since_ms
                    >= int(self.suspect_persistence_seconds * 1000.0)
                ):
                    self._mode = AdaptiveRealtimeMode.LIVE_OVERRIDE
                    self._override_axis = conflicting_axis
                    self._last_override_evidence_ms = timestamp_ms
                    self._recovery_since_ms = None
            else:
                self._mode = AdaptiveRealtimeMode.NORMAL
                self._suspect_axis = None
                self._suspect_since_ms = None
                self._extension_axis = None
                self._extension_started_ms = None
                self._extension_event_count = 0

        elif self._mode == AdaptiveRealtimeMode.PHASE_EXTENSION:
            current_extension_weight = (
                float(evidence[self._extension_axis]["weight"])
                if self._extension_axis is not None
                and self._extension_axis in evidence
                else 0.0
            )
            current_extension_releases = (
                int(evidence[self._extension_axis]["releases"])
                if self._extension_axis is not None
                and self._extension_axis in evidence
                else 0
            )
            opposing_weight = (
                float(evidence[expected_axis]["weight"])
                if expected_axis is not None
                and expected_axis in evidence
                and expected_axis != self._extension_axis
                else 0.0
            )
            opposing_releases = (
                int(evidence[expected_axis]["releases"])
                if expected_axis is not None
                and expected_axis in evidence
                and expected_axis != self._extension_axis
                else 0
            )
            sustained_opposing = (
                opposing_weight >= self.min_conflicting_weight
                and opposing_releases >= self.min_conflicting_releases
                and opposing_weight
                >= current_extension_weight - self.dominance_margin
            )
            if sustained_opposing:
                self._mode = AdaptiveRealtimeMode.RECOVERY
            elif (
                current_extension_weight < 1.0
                or current_extension_releases < 1
            ) and (
                self._last_override_evidence_ms is None
                or timestamp_ms - self._last_override_evidence_ms
                >= int(self.stale_override_seconds * 1000.0)
            ):
                self._mode = AdaptiveRealtimeMode.RECOVERY
            if (
                self._mode == AdaptiveRealtimeMode.PHASE_EXTENSION
                and self.extension_max_seconds is not None
                and extension_elapsed_s > self.extension_max_seconds
            ):
                self._mode = AdaptiveRealtimeMode.RECOVERY
            if self._mode == AdaptiveRealtimeMode.PHASE_EXTENSION:
                self._extension_event_count = max(
                    self._extension_event_count,
                    current_extension_releases,
                )
                self._extension_peak_duration_seconds = max(
                    self._extension_peak_duration_seconds,
                    extension_elapsed_s,
                )
                self._last_override_evidence_ms = timestamp_ms

        elif self._mode == AdaptiveRealtimeMode.LIVE_OVERRIDE:
            override_axis = self._override_axis
            override_weight = (
                float(evidence[override_axis]["weight"])
                if override_axis is not None
                else 0.0
            )
            override_releases = (
                int(evidence[override_axis]["releases"])
                if override_axis is not None
                else 0
            )
            if override_weight >= 1.0 and override_releases >= 1:
                self._last_override_evidence_ms = timestamp_ms

            aligned = (
                expected_axis is not None
                and expected_weight >= self.min_recovery_weight
                and expected_releases >= self.min_recovery_releases
                and expected_weight
                >= (
                    self._max_conflicting_weight(
                        expected_axis,
                        evidence,
                    )
                    + self.dominance_margin
                )
            )
            if aligned:
                if self._recovery_since_ms is None:
                    self._recovery_since_ms = timestamp_ms
                elif (
                    timestamp_ms - self._recovery_since_ms
                    >= int(
                        self.recovery_persistence_seconds * 1000.0
                    )
                ):
                    self._mode = AdaptiveRealtimeMode.RECOVERY
            else:
                self._recovery_since_ms = None
                if (
                    self._last_override_evidence_ms is not None
                    and timestamp_ms - self._last_override_evidence_ms
                    >= int(self.stale_override_seconds * 1000.0)
                ):
                    self._mode = AdaptiveRealtimeMode.RECOVERY

        elif self._mode == AdaptiveRealtimeMode.RECOVERY:
            pass

        effective_axis = (
            self._extension_axis
            if self._mode == AdaptiveRealtimeMode.PHASE_EXTENSION
            else (
                self._override_axis
                if self._mode == AdaptiveRealtimeMode.LIVE_OVERRIDE
                else expected_axis
            )
        )
        observed_approaches = self._observed_approaches(
            evidence,
            effective_axis,
        )

        if self._mode == AdaptiveRealtimeMode.PHASE_EXTENSION:
            effective_weight = (
                float(evidence[effective_axis]["weight"])
                if effective_axis is not None
                else 0.0
            )
            effective_releases = (
                int(evidence[effective_axis]["releases"])
                if effective_axis is not None
                else 0
            )
            confidence = min(
                1.0,
                max(
                    0.0,
                    0.45
                    + 0.10 * effective_releases
                    + 0.06 * effective_weight
                    - 0.08 * conflicting_weight,
                ),
            )
            reason = "confirmed_phase_extension"
        elif self._mode == AdaptiveRealtimeMode.LIVE_OVERRIDE:
            effective_weight = (
                float(evidence[effective_axis]["weight"])
                if effective_axis is not None
                else 0.0
            )
            effective_releases = (
                int(evidence[effective_axis]["releases"])
                if effective_axis is not None
                else 0
            )
            confidence = min(
                1.0,
                0.45
                + 0.15 * effective_releases
                + 0.08 * effective_weight,
            )
            reason = "persistent_release_outside_template"
        elif self._mode == AdaptiveRealtimeMode.SUSPECT:
            confidence = min(
                0.65,
                0.25
                + 0.10 * (
                    extension_releases
                    if self._extension_axis is not None
                    else conflicting_releases
                ),
            )
            reason = (
                "possible_phase_extension"
                if self._extension_axis is not None
                else "possible_template_deviation"
            )
        elif self._mode == AdaptiveRealtimeMode.RECOVERY:
            confidence = 0.0
            reason = "resynchronizing_after_live_override"
        else:
            confidence = 1.0
            reason = None

        return AdaptiveRealtimeDecision(
            mode=self._mode,
            expected_axis=expected_axis,
            effective_axis=effective_axis,
            observed_approaches=observed_approaches,
            confidence=round(float(confidence), 4),
            template_disagreement=self._mode
            in {
                AdaptiveRealtimeMode.SUSPECT,
                AdaptiveRealtimeMode.PHASE_EXTENSION,
                AdaptiveRealtimeMode.LIVE_OVERRIDE,
            },
            reason=reason,
            expected_weight=round(expected_weight, 4),
            conflicting_weight=round(conflicting_weight, 4),
            conflicting_release_count=conflicting_releases,
            extension_duration_seconds=round(
                self._extension_duration_seconds(timestamp_ms)
                if self._mode == AdaptiveRealtimeMode.PHASE_EXTENSION
                else 0.0,
                3,
            ),
            extension_event_count=(
                self._extension_event_count
                if self._mode == AdaptiveRealtimeMode.PHASE_EXTENSION
                else 0
            ),
            extension_peak_duration_seconds=round(
                self._extension_peak_duration_seconds,
                3,
            ),
        )

    def _has_pre_boundary_evidence(
        self,
        events: Iterable[TrajectoryEvent],
        timestamp_ms: int,
        extension_axis: str | None,
        extension_elapsed_s: float,
    ) -> bool:
        if extension_axis is None or extension_elapsed_s <= 0.0:
            return False
        boundary_ms = (
            int(timestamp_ms)
            - int(round(extension_elapsed_s * 1000.0))
        )
        lower_ms = boundary_ms - int(
            self.evidence_window_seconds * 1000.0
        )
        for event in events:
            if not lower_ms <= event.timestamp_ms <= boundary_ms:
                continue
            if event.event_type not in {
                EventType.RELEASE,
                EventType.CROSSING,
            }:
                continue
            if self._axis_for_approach(event.approach) == extension_axis:
                return True
        return False

    def _extension_duration_seconds(self, timestamp_ms: int) -> float:
        if self._extension_started_ms is None:
            return 0.0
        return max(
            0.0,
            (timestamp_ms - self._extension_started_ms) / 1000.0,
        )

    def _extension_candidate(
        self,
        phases: Iterable[object] | None,
        cycle_position_s: float,
        cycle_seconds: float,
        expected_axis: str | None,
    ) -> tuple[str | None, float]:
        if phases is None or cycle_seconds <= 0:
            return None, 0.0

        candidates: list[tuple[float, str]] = []
        for phase in phases:
            axis = self._phase_axis(phase)
            if axis is None:
                continue
            end = float(getattr(phase, "phase_end", 0.0)) % cycle_seconds
            elapsed = (float(cycle_position_s) - end) % cycle_seconds
            if elapsed <= 0.0:
                continue
            candidates.append((elapsed, axis))

        if not candidates:
            return None, 0.0

        elapsed, axis = min(candidates, key=lambda item: item[0])
        if expected_axis is not None and axis == expected_axis:
            return None, 0.0
        return axis, elapsed

    def _axis_evidence(
        self,
        events: Iterable[TrajectoryEvent],
        timestamp_ms: int,
    ) -> dict[str, dict[str, object]]:
        lower_ms = timestamp_ms - int(
            self.evidence_window_seconds * 1000.0
        )
        result: dict[str, dict[str, object]] = {
            axis: {
                "weight": 0.0,
                "releases": 0,
                "approach_weight": {
                    approach: 0.0
                    for approach in approaches
                },
                "approach_releases": {
                    approach: 0
                    for approach in approaches
                },
            }
            for axis, approaches in (
                (family.name, family.approaches)
                for family in self.topology.families
            )
        }
        for event in events:
            if not lower_ms <= event.timestamp_ms <= timestamp_ms:
                continue
            if event.event_type not in {
                EventType.RELEASE,
                EventType.CROSSING,
            }:
                continue
            axis = self._axis_for_approach(event.approach)
            if axis is None:
                continue
            weight = (
                self.RELEASE_WEIGHT
                if event.event_type == EventType.RELEASE
                else self.CROSSING_WEIGHT
            ) * max(0.0, min(1.0, float(event.confidence)))
            result[axis]["weight"] = (
                float(result[axis]["weight"]) + weight
            )
            approach_weight = result[axis]["approach_weight"]
            approach_weight[event.approach] = (
                float(approach_weight[event.approach]) + weight
            )
            if event.event_type == EventType.RELEASE:
                result[axis]["releases"] = (
                    int(result[axis]["releases"]) + 1
                )
                approach_releases = result[axis]["approach_releases"]
                approach_releases[event.approach] = (
                    int(approach_releases[event.approach]) + 1
                )
        return result

    def _observed_approaches(
        self,
        evidence: dict[str, dict[str, object]],
        axis: str | None,
    ) -> tuple[str, ...]:
        if axis is None:
            return ()
        weights = evidence[axis]["approach_weight"]
        releases = evidence[axis]["approach_releases"]
        return tuple(
            sorted(
                approach
                for approach in self.topology.approaches_for_family(axis)
                if (
                    float(weights[approach]) >= 1.0
                    and int(releases[approach]) >= 1
                )
            )
        )

    def _near_phase_boundary(
        self,
        phase: object | None,
        cycle_position_s: float,
        cycle_seconds: float,
    ) -> bool:
        if phase is None or cycle_seconds <= 0:
            return True
        start = float(getattr(phase, "phase_start", 0.0)) % cycle_seconds
        end = float(getattr(phase, "phase_end", 0.0)) % cycle_seconds
        position = float(cycle_position_s) % cycle_seconds
        since_start = (position - start) % cycle_seconds
        to_end = (end - position) % cycle_seconds
        return (
            min(since_start, to_end)
            <= self.boundary_guard_seconds
        )

    def _axis_for_approach(self, approach: str) -> str | None:
        return self.topology.family_for_approach(approach)

    def _phase_axis(self, phase: object | None) -> str | None:
        if phase is None:
            return None
        return self.topology.family_for_active_approaches(
            tuple(getattr(phase, "active_approaches", ()))
        )

    def _dominant_conflicting_axis(
        self,
        expected_axis: str | None,
        evidence: dict[str, dict[str, object]],
    ) -> str | None:
        candidates = self.topology.conflicting_families_for(
            expected_axis
        )
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda family: float(
                evidence.get(family, {}).get("weight", 0.0)
            ),
        )

    def _max_conflicting_weight(
        self,
        expected_axis: str | None,
        evidence: dict[str, dict[str, object]],
    ) -> float:
        return max(
            (
                float(
                    evidence.get(family, {}).get("weight", 0.0)
                )
                for family
                in self.topology.conflicting_families_for(
                    expected_axis
                )
            ),
            default=0.0,
        )


__all__ = [
    "AXIS_APPROACHES",
    "AdaptiveRealtimeDecision",
    "AdaptiveRealtimeMode",
    "AdaptiveRealtimeOverride",
]
