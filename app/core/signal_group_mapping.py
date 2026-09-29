from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from app.core.models import TrajectoryEvent
from app.core.signal_group_discovery import (
    SignalGroupDiscovery,
    SignalGroupDiscoveryResult,
    SignalGroupEvidence,
)
from app.core.signal_group_signature import (
    MovementPhaseSignature,
    build_movement_phase_signatures,
)


class SignalGroupMappingStatus(str, Enum):
    MAPPED = "mapped"
    UNMAPPED = "unmapped"


@dataclass(frozen=True)
class SignalGroupMappingEntry:
    """Deterministic movement-to-logical-group assignment.

    A mapped entry points to a logical signal group discovered from temporal
    evidence. An unmapped entry preserves an explicit insufficient-evidence
    result instead of fabricating a group.
    """

    movement_id: str
    approach: str | None
    group_id: str | None
    status: SignalGroupMappingStatus
    evidence: SignalGroupEvidence
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return {
            "movement_id": self.movement_id,
            "approach": self.approach,
            "group_id": self.group_id,
            "status": self.status.value,
            "evidence": self.evidence.value,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class SignalGroupModel:
    """Complete Stage 2 temporal-to-logical signal-group model."""

    cycle_seconds: float
    origin_timestamp_ms: int
    signatures: tuple[MovementPhaseSignature, ...]
    discovery: SignalGroupDiscoveryResult
    mapping: SignalGroupMapping

    def to_dict(self) -> dict[str, object]:
        return {
            "cycle_seconds": self.cycle_seconds,
            "origin_timestamp_ms": self.origin_timestamp_ms,
            "signatures": [signature.to_dict() for signature in self.signatures],
            "discovery": self.discovery.to_dict(),
            "mapping": self.mapping.to_dict(),
        }


@dataclass(frozen=True)
class SignalGroupMapping:
    """Stable movement-to-logical-group view of a discovery result."""

    entries: tuple[SignalGroupMappingEntry, ...]

    @property
    def movement_to_group(self) -> dict[str, str]:
        return {
            entry.movement_id: entry.group_id
            for entry in self.entries
            if entry.group_id is not None
        }

    @property
    def group_to_movements(self) -> dict[str, tuple[str, ...]]:
        groups: dict[str, list[str]] = {}
        for entry in self.entries:
            if entry.group_id is None:
                continue
            groups.setdefault(entry.group_id, []).append(entry.movement_id)
        return {
            group_id: tuple(movements)
            for group_id, movements in groups.items()
        }

    @property
    def unmapped_movements(self) -> tuple[str, ...]:
        return tuple(
            entry.movement_id
            for entry in self.entries
            if entry.group_id is None
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "movement_to_group": dict(self.movement_to_group),
            "group_to_movements": {
                group_id: list(movements)
                for group_id, movements in self.group_to_movements.items()
            },
            "unmapped_movements": list(self.unmapped_movements),
        }


def build_signal_group_mapping(
    result: SignalGroupDiscoveryResult,
) -> SignalGroupMapping:
    entries: list[SignalGroupMappingEntry] = []

    for group in result.groups:
        for movement_id in group.movement_ids:
            entries.append(
                SignalGroupMappingEntry(
                    movement_id=movement_id,
                    approach=group.approach,
                    group_id=group.group_id,
                    status=SignalGroupMappingStatus.MAPPED,
                    evidence=group.evidence,
                    confidence=group.confidence,
                )
            )

    for movement_id in result.insufficient_movements:
        entries.append(
            SignalGroupMappingEntry(
                movement_id=movement_id,
                approach=_movement_approach(movement_id),
                group_id=None,
                status=SignalGroupMappingStatus.UNMAPPED,
                evidence=SignalGroupEvidence.INSUFFICIENT_EVIDENCE,
                confidence=0.0,
            )
        )

    entries.sort(
        key=lambda entry: (
            entry.approach or "",
            entry.movement_id,
            entry.group_id or "",
        )
    )

    seen: set[str] = set()
    for entry in entries:
        if entry.movement_id in seen:
            raise ValueError(
                f"movement appears more than once in signal-group mapping: "
                f"{entry.movement_id}"
            )
        seen.add(entry.movement_id)

    return SignalGroupMapping(entries=tuple(entries))


def build_signal_group_model(
    events: Iterable[TrajectoryEvent],
    *,
    cycle_seconds: float,
    origin_timestamp_ms: int,
    bin_seconds: float = 1.0,
    min_cycle_presence: float = 0.35,
    dedupe_seconds: float = 2.0,
    equivalence_iou: float = 0.60,
    minimum_support_cycles: int = 3,
) -> SignalGroupModel:
    """Build signatures, logical groups, and the deterministic mapping."""

    signatures = build_movement_phase_signatures(
        tuple(events),
        cycle_seconds=cycle_seconds,
        origin_timestamp_ms=origin_timestamp_ms,
        bin_seconds=bin_seconds,
        min_cycle_presence=min_cycle_presence,
        dedupe_seconds=dedupe_seconds,
    )
    discovery = SignalGroupDiscovery(
        equivalence_iou=equivalence_iou,
        minimum_support_cycles=minimum_support_cycles,
    ).discover(signatures)
    mapping = build_signal_group_mapping(discovery)
    return SignalGroupModel(
        cycle_seconds=float(cycle_seconds),
        origin_timestamp_ms=int(origin_timestamp_ms),
        signatures=signatures,
        discovery=discovery,
        mapping=mapping,
    )


def _movement_approach(movement_id: str) -> str | None:
    text = str(movement_id).strip()
    if "->" not in text:
        return None
    approach = text.split("->", 1)[0].strip()
    return approach or None


__all__ = [
    "SignalGroupModel",
    "SignalGroupMapping",
    "SignalGroupMappingEntry",
    "SignalGroupMappingStatus",
    "build_signal_group_mapping",
    "build_signal_group_model",
]
