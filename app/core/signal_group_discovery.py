from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.core.signal_group_signature import (
    CircularInterval,
    MovementPhaseSignature,
    SignalGroupRelation,
    compare_movement_signatures,
)


class SignalGroupEvidence(str, Enum):
    SUPPORTED = "supported"
    STRUCTURAL_HYPOTHESIS = "structural_hypothesis"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class SignalGroupCandidate:
    """One conservative logical signal-group hypothesis for one approach."""

    group_id: str
    approach: str
    intervals: tuple[CircularInterval, ...]
    movement_ids: tuple[str, ...]
    evidence: SignalGroupEvidence
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return {
            "group_id": self.group_id,
            "approach": self.approach,
            "intervals": [
                {
                    "start": interval.start,
                    "end": interval.end,
                    "cycle_seconds": interval.cycle_seconds,
                }
                for interval in self.intervals
            ],
            "movement_ids": list(self.movement_ids),
            "evidence": self.evidence.value,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class SignalGroupRelationEvidence:
    left_movement: str
    right_movement: str
    relation: SignalGroupRelation
    approach: str

    def to_dict(self) -> dict[str, object]:
        return {
            "left_movement": self.left_movement,
            "right_movement": self.right_movement,
            "relation": self.relation.value,
            "approach": self.approach,
        }


@dataclass(frozen=True)
class SignalGroupDiscoveryResult:
    """Approach-local logical groups plus explicit unresolved evidence."""

    groups: tuple[SignalGroupCandidate, ...]
    relations: tuple[SignalGroupRelationEvidence, ...]
    insufficient_movements: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "groups": [group.to_dict() for group in self.groups],
            "relations": [relation.to_dict() for relation in self.relations],
            "insufficient_movements": list(self.insufficient_movements),
        }


class SignalGroupDiscovery:
    """Build deterministic logical signal groups from phase signatures.

    This is intentionally a small first-stage model selector. EQUIVALENT
    signatures may share a group; containment and overlap remain evidence
    about structure and do not force a merge. Physical signal-head count is
    outside the model.
    """

    def __init__(
        self,
        *,
        equivalence_iou: float = 0.60,
        minimum_support_cycles: int = 3,
    ) -> None:
        if not 0.0 < equivalence_iou <= 1.0:
            raise ValueError("equivalence_iou must be in (0, 1]")
        if minimum_support_cycles < 1:
            raise ValueError("minimum_support_cycles must be positive")
        self.equivalence_iou = float(equivalence_iou)
        self.minimum_support_cycles = int(minimum_support_cycles)

    def discover(
        self,
        signatures: tuple[MovementPhaseSignature, ...]
        | list[MovementPhaseSignature],
    ) -> SignalGroupDiscoveryResult:
        ordered = tuple(
            sorted(
                signatures,
                key=lambda item: (item.approach, item.movement),
            )
        )
        usable = tuple(
            item
            for item in ordered
            if item.is_sufficient and item.active_intervals
        )
        insufficient = tuple(
            sorted(
                item.movement
                for item in ordered
                if not item.is_sufficient or not item.active_intervals
            )
        )

        relations: list[SignalGroupRelationEvidence] = []
        for index, left in enumerate(usable):
            for right in usable[index + 1 :]:
                relation = compare_movement_signatures(
                    left,
                    right,
                    equivalence_iou=self.equivalence_iou,
                    minimum_support_cycles=self.minimum_support_cycles,
                )
                relations.append(
                    SignalGroupRelationEvidence(
                        left_movement=left.movement,
                        right_movement=right.movement,
                        relation=relation,
                        approach=(
                            left.approach
                            if left.approach == right.approach
                            else f"{left.approach}|{right.approach}"
                        ),
                    )
                )

        groups: list[list[MovementPhaseSignature]] = []
        for signature in usable:
            assigned = False
            for group in groups:
                relation = compare_movement_signatures(
                    signature,
                    group[0],
                    equivalence_iou=self.equivalence_iou,
                    minimum_support_cycles=self.minimum_support_cycles,
                )
                if relation is SignalGroupRelation.EQUIVALENT:
                    group.append(signature)
                    assigned = True
                    break
            if not assigned:
                groups.append([signature])

        candidates: list[SignalGroupCandidate] = []
        for index, group in enumerate(groups, start=1):
            representative = group[0]
            confidence = min(
                min(item.repeatability for item in group),
                min(item.boundary_stability for item in group),
            )
            candidates.append(
                SignalGroupCandidate(
                    group_id=f"{representative.approach}:SG{index}",
                    approach=representative.approach,
                    intervals=representative.active_intervals,
                    movement_ids=tuple(item.movement for item in group),
                    evidence=SignalGroupEvidence.SUPPORTED,
                    confidence=max(0.0, min(1.0, confidence)),
                )
            )

        return SignalGroupDiscoveryResult(
            groups=tuple(candidates),
            relations=tuple(relations),
            insufficient_movements=insufficient,
        )


__all__ = [
    "SignalGroupCandidate",
    "SignalGroupDiscovery",
    "SignalGroupDiscoveryResult",
    "SignalGroupEvidence",
    "SignalGroupRelationEvidence",
]
