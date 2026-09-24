from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence

from app.core.event_phase_discovery import EventPhaseDiscoveryResult


DEFAULT_REGIME_SIGNATURE_SAMPLES = 60
DEFAULT_REGIME_MATCH_THRESHOLD = 0.93
DEFAULT_REGIME_SWITCH_CONFIRMATIONS = 2
DEFAULT_MAX_REMEMBERED_REGIMES = 12


def _phase_label_at(
    model: EventPhaseDiscoveryResult,
    position_s: float,
) -> tuple[str, ...] | None:
    cycle = float(model.cycle_seconds)
    value = float(position_s) % cycle
    for phase in model.phases:
        start = float(phase.phase_start) % cycle
        end = float(phase.phase_end) % cycle
        inside = (
            start <= value < end
            if start <= end
            else value >= start or value < end
        )
        if inside:
            return tuple(sorted(phase.active_approaches))
    return None


def _phase_signature(
    model: EventPhaseDiscoveryResult,
    *,
    samples: int,
) -> tuple[tuple[str, ...] | None, ...]:
    cycle = float(model.cycle_seconds)
    return tuple(
        _phase_label_at(
            model,
            (index + 0.5) * cycle / samples,
        )
        for index in range(samples)
    )


def phase_model_similarity(
    left: EventPhaseDiscoveryResult,
    right: EventPhaseDiscoveryResult,
    *,
    samples: int = DEFAULT_REGIME_SIGNATURE_SAMPLES,
) -> float:
    """Rotation-invariant similarity for recurring phase structures.

    Historical absolute phase origin is deliberately ignored. Cycle length,
    known phase labels and determined coverage must still agree closely.
    UNKNOWN gaps do not become invented phases merely to improve the match.
    """
    if samples < 12:
        raise ValueError("regime signature requires at least 12 samples")

    left_cycle = float(left.cycle_seconds)
    right_cycle = float(right.cycle_seconds)
    if left_cycle <= 0 or right_cycle <= 0:
        return 0.0

    cycle_tolerance = max(
        6.0,
        0.08 * max(left_cycle, right_cycle),
    )
    cycle_delta = abs(left_cycle - right_cycle)
    if cycle_delta > cycle_tolerance:
        return 0.0
    cycle_score = max(
        0.0,
        1.0 - cycle_delta / cycle_tolerance,
    )

    left_signature = _phase_signature(left, samples=samples)
    right_signature = _phase_signature(right, samples=samples)
    left_known = sum(item is not None for item in left_signature)
    right_known = sum(item is not None for item in right_signature)
    min_known = min(left_known, right_known)
    if min_known <= 0:
        return 0.0

    minimum_shared = max(4, int(round(min_known * 0.60)))
    coverage_score = max(
        0.0,
        1.0
        - abs(
            float(left.cycle_coverage)
            - float(right.cycle_coverage)
        ),
    )

    best = 0.0
    for shift in range(samples):
        shared = 0
        matching = 0
        for index, left_label in enumerate(left_signature):
            right_label = right_signature[(index + shift) % samples]
            if left_label is None or right_label is None:
                continue
            shared += 1
            if left_label == right_label:
                matching += 1

        if shared < minimum_shared:
            continue
        phase_score = matching / shared
        overlap_score = min(1.0, shared / min_known)
        score = (
            0.75 * phase_score
            + 0.10 * overlap_score
            + 0.10 * coverage_score
            + 0.05 * cycle_score
        )
        best = max(best, score)

    return round(max(0.0, min(1.0, best)), 4)


@dataclass
class RememberedRegime:
    regime_id: str
    phase_model: EventPhaseDiscoveryResult
    confirmations: int
    first_seen_timestamp_ms: int
    last_seen_timestamp_ms: int
    model_quality: str
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return {
            "regime_id": self.regime_id,
            "cycle_seconds": round(
                float(self.phase_model.cycle_seconds),
                3,
            ),
            "cycle_coverage": round(
                float(self.phase_model.cycle_coverage),
                4,
            ),
            "phase_count": len(self.phase_model.phases),
            "confirmations": self.confirmations,
            "first_seen_timestamp_ms": self.first_seen_timestamp_ms,
            "last_seen_timestamp_ms": self.last_seen_timestamp_ms,
            "model_quality": self.model_quality,
            "confidence": round(float(self.confidence), 4),
        }


@dataclass(frozen=True)
class RegimeObservation:
    candidate_regime_id: str | None
    similarity: float
    pending_confirmations: int
    switch: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class OnlineRegimeMemory:
    """Bounded in-memory catalogue of repeatedly observed signal regimes.

    A candidate must first satisfy the existing reconstruction quality
    contract. This class only answers whether that already-usable candidate
    matches a remembered regime and whether a different regime has repeated
    enough times to justify a switch.
    """

    def __init__(
        self,
        *,
        match_threshold: float = DEFAULT_REGIME_MATCH_THRESHOLD,
        switch_confirmations: int = DEFAULT_REGIME_SWITCH_CONFIRMATIONS,
        max_regimes: int = DEFAULT_MAX_REMEMBERED_REGIMES,
        signature_samples: int = DEFAULT_REGIME_SIGNATURE_SAMPLES,
    ) -> None:
        if not 0.0 < match_threshold <= 1.0:
            raise ValueError("match_threshold must be in (0, 1]")
        if switch_confirmations < 2:
            raise ValueError(
                "switch_confirmations must be at least 2"
            )
        if max_regimes < 1:
            raise ValueError("max_regimes must be positive")
        if signature_samples < 12:
            raise ValueError(
                "signature_samples must be at least 12"
            )

        self.match_threshold = float(match_threshold)
        self.switch_confirmations = int(switch_confirmations)
        self.max_regimes = int(max_regimes)
        self.signature_samples = int(signature_samples)
        self._entries: list[RememberedRegime] = []
        self._current_regime_id: str | None = None
        self._pending_regime_id: str | None = None
        self._pending_confirmations = 0
        self._switch_count = 0
        self._last_switch_reason: str | None = None

    @property
    def current_regime_id(self) -> str | None:
        return self._current_regime_id

    @property
    def switch_count(self) -> int:
        return self._switch_count

    @property
    def entries(self) -> tuple[RememberedRegime, ...]:
        return tuple(self._entries)

    def seed(
        self,
        phase_model: EventPhaseDiscoveryResult,
        *,
        timestamp_ms: int,
        model_quality: str = "SEEDED",
        confidence: float = 1.0,
    ) -> str:
        regime_id, _similarity = self._remember(
            phase_model,
            timestamp_ms=int(timestamp_ms),
            model_quality=model_quality,
            confidence=confidence,
        )
        if self._current_regime_id is None:
            self._current_regime_id = regime_id
        return regime_id

    def observe_candidate(
        self,
        phase_model: EventPhaseDiscoveryResult,
        *,
        timestamp_ms: int,
        model_quality: str,
        confidence: float,
    ) -> RegimeObservation:
        regime_id, similarity = self._remember(
            phase_model,
            timestamp_ms=int(timestamp_ms),
            model_quality=model_quality,
            confidence=confidence,
        )
        if regime_id is None:
            self._clear_pending()
            return RegimeObservation(
                candidate_regime_id=None,
                similarity=0.0,
                pending_confirmations=0,
                switch=False,
                reason="regime_memory_capacity_reached",
            )

        if self._current_regime_id is None:
            self._current_regime_id = regime_id
            self._clear_pending()
            return RegimeObservation(
                candidate_regime_id=regime_id,
                similarity=similarity,
                pending_confirmations=0,
                switch=False,
                reason="initial_regime_selected",
            )

        if regime_id == self._current_regime_id:
            self._clear_pending()
            return RegimeObservation(
                candidate_regime_id=regime_id,
                similarity=similarity,
                pending_confirmations=0,
                switch=False,
                reason="current_regime_reconfirmed",
            )

        if self._pending_regime_id == regime_id:
            self._pending_confirmations += 1
        else:
            self._pending_regime_id = regime_id
            self._pending_confirmations = 1

        if self._pending_confirmations < self.switch_confirmations:
            return RegimeObservation(
                candidate_regime_id=regime_id,
                similarity=similarity,
                pending_confirmations=self._pending_confirmations,
                switch=False,
                reason="alternative_regime_pending_confirmation",
            )

        previous = self._current_regime_id
        self._current_regime_id = regime_id
        self._switch_count += 1
        self._last_switch_reason = (
            f"repeated_regime_candidate:{previous}->{regime_id}"
        )
        confirmations = self._pending_confirmations
        self._clear_pending()
        return RegimeObservation(
            candidate_regime_id=regime_id,
            similarity=similarity,
            pending_confirmations=confirmations,
            switch=True,
            reason="alternative_regime_confirmed",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "current_regime_id": self._current_regime_id,
            "regime_count": len(self._entries),
            "pending_regime_id": self._pending_regime_id,
            "pending_confirmations": self._pending_confirmations,
            "switch_confirmations_required": self.switch_confirmations,
            "switch_count": self._switch_count,
            "last_switch_reason": self._last_switch_reason,
            "regimes": [entry.to_dict() for entry in self._entries],
        }

    def _remember(
        self,
        phase_model: EventPhaseDiscoveryResult,
        *,
        timestamp_ms: int,
        model_quality: str,
        confidence: float,
    ) -> tuple[str | None, float]:
        match = self._best_match(phase_model)
        if match is not None:
            entry, similarity = match
            entry.phase_model = phase_model
            entry.confirmations += 1
            entry.last_seen_timestamp_ms = int(timestamp_ms)
            entry.model_quality = str(model_quality)
            entry.confidence = float(confidence)
            return entry.regime_id, similarity

        if len(self._entries) >= self.max_regimes:
            return None, 0.0

        regime_id = f"R{len(self._entries) + 1}"
        self._entries.append(
            RememberedRegime(
                regime_id=regime_id,
                phase_model=phase_model,
                confirmations=1,
                first_seen_timestamp_ms=int(timestamp_ms),
                last_seen_timestamp_ms=int(timestamp_ms),
                model_quality=str(model_quality),
                confidence=float(confidence),
            )
        )
        return regime_id, 1.0

    def _best_match(
        self,
        phase_model: EventPhaseDiscoveryResult,
    ) -> tuple[RememberedRegime, float] | None:
        best_entry = None
        best_similarity = 0.0
        for entry in self._entries:
            similarity = phase_model_similarity(
                phase_model,
                entry.phase_model,
                samples=self.signature_samples,
            )
            if similarity > best_similarity:
                best_entry = entry
                best_similarity = similarity

        if (
            best_entry is None
            or best_similarity < self.match_threshold
        ):
            return None
        return best_entry, best_similarity

    def _clear_pending(self) -> None:
        self._pending_regime_id = None
        self._pending_confirmations = 0


__all__ = [
    "OnlineRegimeMemory",
    "RegimeObservation",
    "RememberedRegime",
    "phase_model_similarity",
]
