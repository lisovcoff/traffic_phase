from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Sequence

from app.core.event_phase_discovery import EventPhase
from app.core.reconstruction import (
    GOOD_MODEL_MIN_COVERAGE,
    GOOD_MODEL_MIN_CYCLE_CONFIDENCE,
    GOOD_MODEL_MIN_PHASE_CONFIDENCE,
    PARTIAL_MODEL_MIN_COVERAGE,
    PARTIAL_MODEL_MIN_CYCLE_CONFIDENCE,
    PARTIAL_MODEL_MIN_PHASE_CONFIDENCE,
    SessionReconstruction,
)


SIGNATURE_BINS = 60
CYCLE_TOLERANCE_SECONDS = 6.0
MIN_FAMILY_SIMILARITY = 0.82

_APPROACH_BITS = {
    "N": 1,
    "S": 2,
    "E": 4,
    "W": 8,
}
_BIT_APPROACHES = tuple(_APPROACH_BITS.items())


@dataclass(frozen=True)
class RegimeFamilyMember:
    analysis_segment_id: int
    physical_session_index: int
    regime_index: int
    model_quality: str
    cycle_seconds: float
    cycle_coverage: float
    similarity: float
    alignment_seconds: float

    def to_dict(self) -> dict[str, object]:
        return {
            "analysis_segment_id": self.analysis_segment_id,
            "physical_session_index": self.physical_session_index,
            "regime_index": self.regime_index,
            "model_quality": self.model_quality,
            "cycle_seconds": self.cycle_seconds,
            "cycle_coverage": self.cycle_coverage,
            "similarity": self.similarity,
            "alignment_seconds": self.alignment_seconds,
        }


@dataclass(frozen=True)
class RegimeFamilySummary:
    family_id: str
    cycle_seconds: float
    member_count: int
    reference_session_id: int
    members: tuple[RegimeFamilyMember, ...]
    similarity_mean: float
    consensus_coverage: float
    consensus_confidence: float
    model_quality: str
    consensus_phase_model: dict[str, object] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "family_id": self.family_id,
            "cycle_seconds": self.cycle_seconds,
            "member_count": self.member_count,
            "reference_session_id": self.reference_session_id,
            "members": [member.to_dict() for member in self.members],
            "similarity_mean": self.similarity_mean,
            "consensus_coverage": self.consensus_coverage,
            "consensus_confidence": self.consensus_confidence,
            "model_quality": self.model_quality,
            "consensus_phase_model": self.consensus_phase_model,
        }


@dataclass
class _FamilyWork:
    reference_id: int
    reference: SessionReconstruction
    reference_signature: tuple[int, ...]
    members: list[tuple[int, SessionReconstruction, int, float]]


def _phase_active_at(
    phase: EventPhase,
    position_s: float,
    cycle_seconds: float,
) -> bool:
    start = float(phase.phase_start) % cycle_seconds
    end = float(phase.phase_end) % cycle_seconds
    if abs(start - end) <= 1e-9:
        return True
    if start < end:
        return start <= position_s < end
    return position_s >= start or position_s < end


def _stage_bits(active_approaches: Sequence[str]) -> int:
    bits = 0
    for approach in active_approaches:
        bits |= _APPROACH_BITS.get(str(approach), 0)
    return bits


def _approaches_from_bits(bits: int) -> tuple[str, ...]:
    return tuple(
        approach
        for approach, value in _BIT_APPROACHES
        if bits & value
    )


def _session_signature(
    session: SessionReconstruction,
    *,
    bins: int = SIGNATURE_BINS,
) -> tuple[int, ...]:
    model = session.phase_model
    if model is None or bins <= 0:
        return ()
    cycle = float(model.cycle_seconds)
    if cycle <= 0:
        return ()
    signature: list[int] = []
    for index in range(bins):
        position = (index + 0.5) / bins * cycle
        active: tuple[str, ...] = ()
        for phase in model.phases:
            if _phase_active_at(phase, position, cycle):
                active = tuple(phase.active_approaches)
                break
        signature.append(_stage_bits(active))
    return tuple(signature)


def _rotated(
    signature: Sequence[int],
    shift: int,
) -> tuple[int, ...]:
    size = len(signature)
    if size == 0:
        return ()
    return tuple(
        signature[(index + shift) % size]
        for index in range(size)
    )


def _signature_similarity(
    left: Sequence[int],
    right: Sequence[int],
) -> float:
    if not left or len(left) != len(right):
        return 0.0
    exact = 0.0
    conflicting = 0.0
    missing = 0.0
    for a, b in zip(left, right):
        if a and b:
            if a == b:
                exact += 1.0
            else:
                conflicting += 1.0
        elif bool(a) != bool(b):
            missing += 1.0
    denominator = exact + conflicting + 0.25 * missing
    if denominator <= 0:
        return 0.0
    return exact / denominator


def _best_alignment(
    reference: Sequence[int],
    candidate: Sequence[int],
) -> tuple[int, float]:
    if not reference or len(reference) != len(candidate):
        return 0, 0.0
    best_shift = 0
    best_similarity = -1.0
    for shift in range(len(reference)):
        similarity = _signature_similarity(
            reference,
            _rotated(candidate, shift),
        )
        if similarity > best_similarity:
            best_similarity = similarity
            best_shift = shift
    return best_shift, max(0.0, best_similarity)


def _quality_rank(value: str) -> int:
    return {
        "GOOD": 3,
        "PARTIAL": 2,
        "INSUFFICIENT": 1,
    }.get(value, 0)


def _member_weight(session: SessionReconstruction) -> float:
    quality_weight = {
        "GOOD": 1.0,
        "PARTIAL": 0.75,
        "INSUFFICIENT": 0.45,
    }.get(session.model_quality, 0.35)
    return quality_weight * max(
        0.25,
        min(1.0, float(session.confidence)),
    )


def _phase_confidence(session: SessionReconstruction) -> float:
    model = session.phase_model
    if model is None or not model.phases:
        return 0.0
    return sum(
        float(phase.confidence)
        for phase in model.phases
    ) / len(model.phases)


def _family_quality(
    *,
    coverage: float,
    cycle_confidence: float,
    phase_confidence: float,
) -> str:
    if (
        coverage >= GOOD_MODEL_MIN_COVERAGE
        and cycle_confidence >= GOOD_MODEL_MIN_CYCLE_CONFIDENCE
        and phase_confidence >= GOOD_MODEL_MIN_PHASE_CONFIDENCE
    ):
        return "GOOD"
    if (
        coverage >= PARTIAL_MODEL_MIN_COVERAGE
        and cycle_confidence >= PARTIAL_MODEL_MIN_CYCLE_CONFIDENCE
        and phase_confidence >= PARTIAL_MODEL_MIN_PHASE_CONFIDENCE
    ):
        return "PARTIAL"
    return "INSUFFICIENT"


def _circular_runs(
    values: Sequence[int],
) -> list[tuple[int, int, int]]:
    size = len(values)
    if size == 0:
        return []
    runs: list[tuple[int, int, int]] = []
    start = 0
    current = values[0]
    for index in range(1, size):
        if values[index] != current:
            runs.append((start, index, current))
            start = index
            current = values[index]
    runs.append((start, size, current))

    if (
        len(runs) > 1
        and runs[0][2] != 0
        and runs[0][2] == runs[-1][2]
    ):
        first = runs.pop(0)
        last = runs.pop()
        runs.insert(
            0,
            (last[0], first[1], first[2]),
        )
    return runs


def _consensus_signature(
    reference: SessionReconstruction,
    members: Sequence[
        tuple[int, SessionReconstruction, int, float]
    ],
) -> tuple[int, ...]:
    reference_signature = _session_signature(reference)
    if not reference_signature:
        return ()
    if len(members) == 1:
        return reference_signature

    aligned: list[
        tuple[tuple[int, ...], float]
    ] = []
    for _session_id, session, shift, _similarity in members:
        signature = _rotated(
            _session_signature(session),
            shift,
        )
        if signature:
            aligned.append(
                (signature, _member_weight(session))
            )
    if not aligned:
        return reference_signature

    result: list[int] = []
    total_weight = sum(weight for _sig, weight in aligned)
    for index in range(len(reference_signature)):
        votes: dict[int, float] = {}
        supporters: dict[int, int] = {}
        for signature, weight in aligned:
            label = signature[index]
            if not label:
                continue
            votes[label] = votes.get(label, 0.0) + weight
            supporters[label] = supporters.get(label, 0) + 1
        if not votes:
            result.append(0)
            continue
        winner = max(
            votes,
            key=lambda label: (
                votes[label],
                supporters[label],
                label,
            ),
        )
        support_fraction = (
            votes[winner] / total_weight
            if total_weight > 0
            else 0.0
        )
        if (
            supporters[winner] >= 2
            and support_fraction >= 0.35
        ):
            result.append(winner)
        else:
            result.append(0)
    return tuple(result)


def _consensus_phases(
    signature: Sequence[int],
    *,
    cycle_seconds: float,
    confidence: float,
    supporting_event_count: int,
    contradictory_event_count: int,
) -> list[dict[str, object]]:
    if not signature:
        return []
    bin_seconds = cycle_seconds / len(signature)
    runs = [
        run
        for run in _circular_runs(signature)
        if run[2]
    ]
    phases: list[dict[str, object]] = []
    for phase_id, (start, end, bits) in enumerate(
        runs,
        start=1,
    ):
        if start < end:
            phase_start = start * bin_seconds
            phase_end = end * bin_seconds
        else:
            phase_start = start * bin_seconds
            phase_end = end * bin_seconds
        approaches = _approaches_from_bits(bits)
        phases.append(
            {
                "phase_id": phase_id,
                "phase_start": round(
                    phase_start % cycle_seconds,
                    3,
                ),
                "phase_end": round(
                    phase_end % cycle_seconds,
                    3,
                ),
                "active_approaches": list(approaches),
                "confidence": round(confidence, 4),
                "supporting_event_count": (
                    supporting_event_count
                ),
                "contradictory_event_count": (
                    contradictory_event_count
                ),
                "members": list(approaches),
            }
        )
    return phases


def build_regime_families(
    sessions: Sequence[SessionReconstruction],
) -> tuple[RegimeFamilySummary, ...]:
    eligible = [
        (index, session)
        for index, session in enumerate(sessions, start=1)
        if (
            session.status == "ok"
            and session.phase_model is not None
            and session.cycle is not None
            and session.phase_model.phases
        )
    ]
    if not eligible:
        return ()

    ordered = sorted(
        eligible,
        key=lambda item: (
            -_quality_rank(item[1].model_quality),
            -float(item[1].phase_model.cycle_coverage),
            -float(item[1].confidence),
            item[0],
        ),
    )
    families: list[_FamilyWork] = []

    for session_id, session in ordered:
        signature = _session_signature(session)
        if not signature:
            continue
        cycle = float(session.phase_model.cycle_seconds)
        best_family: _FamilyWork | None = None
        best_shift = 0
        best_similarity = -1.0
        for family in families:
            reference_cycle = float(
                family.reference.phase_model.cycle_seconds
            )
            if (
                abs(cycle - reference_cycle)
                > CYCLE_TOLERANCE_SECONDS
            ):
                continue
            shift, similarity = _best_alignment(
                family.reference_signature,
                signature,
            )
            if similarity > best_similarity:
                best_similarity = similarity
                best_shift = shift
                best_family = family

        if (
            best_family is None
            or best_similarity < MIN_FAMILY_SIMILARITY
        ):
            families.append(
                _FamilyWork(
                    reference_id=session_id,
                    reference=session,
                    reference_signature=signature,
                    members=[
                        (
                            session_id,
                            session,
                            0,
                            1.0,
                        )
                    ],
                )
            )
            continue

        best_family.members.append(
            (
                session_id,
                session,
                best_shift,
                best_similarity,
            )
        )

    families.sort(
        key=lambda family: min(
            member[0]
            for member in family.members
        )
    )
    summaries: list[RegimeFamilySummary] = []

    for family_index, family in enumerate(
        families,
        start=1,
    ):
        family_id = f"F{family_index}"
        members = sorted(
            family.members,
            key=lambda item: item[0],
        )
        cycle_seconds = float(
            median(
                float(session.phase_model.cycle_seconds)
                for _id, session, _shift, _similarity in members
            )
        )
        signature = _consensus_signature(
            family.reference,
            members,
        )
        coverage = (
            sum(bool(value) for value in signature)
            / len(signature)
            if signature
            else 0.0
        )
        confidence = float(
            median(
                float(session.confidence)
                for _id, session, _shift, _similarity in members
            )
        )
        cycle_confidence = float(
            median(
                float(session.cycle.estimate.confidence)
                for _id, session, _shift, _similarity in members
            )
        )
        phase_confidence = float(
            median(
                _phase_confidence(session)
                for _id, session, _shift, _similarity in members
            )
        )
        quality = _family_quality(
            coverage=coverage,
            cycle_confidence=cycle_confidence,
            phase_confidence=phase_confidence,
        )
        supporting = sum(
            int(session.phase_model.supporting_event_count)
            for _id, session, _shift, _similarity in members
        )
        contradictory = sum(
            int(session.phase_model.contradictory_event_count)
            for _id, session, _shift, _similarity in members
        )
        phases = _consensus_phases(
            signature,
            cycle_seconds=cycle_seconds,
            confidence=confidence,
            supporting_event_count=supporting,
            contradictory_event_count=contradictory,
        )
        consensus_model = (
            {
                "model_type": "cross_session_regime_consensus",
                "cycle_seconds": round(cycle_seconds, 4),
                "bin_seconds": round(
                    cycle_seconds / SIGNATURE_BINS,
                    4,
                ),
                "origin_timestamp_ms": 0,
                "confidence": round(confidence, 4),
                "supporting_event_count": supporting,
                "contradictory_event_count": contradictory,
                "cycle_coverage": round(coverage, 4),
                "overlap": 0.0,
                "phases": phases,
                "stages": phases,
                "movement_stages": [],
            }
            if phases
            else None
        )
        member_payloads = tuple(
            RegimeFamilyMember(
                analysis_segment_id=session_id,
                physical_session_index=(
                    session.session_index
                ),
                regime_index=session.regime_index,
                model_quality=session.model_quality,
                cycle_seconds=float(
                    session.phase_model.cycle_seconds
                ),
                cycle_coverage=float(
                    session.phase_model.cycle_coverage
                ),
                similarity=round(similarity, 4),
                alignment_seconds=round(
                    shift
                    / SIGNATURE_BINS
                    * cycle_seconds,
                    3,
                ),
            )
            for (
                session_id,
                session,
                shift,
                similarity,
            ) in members
        )
        summaries.append(
            RegimeFamilySummary(
                family_id=family_id,
                cycle_seconds=round(cycle_seconds, 4),
                member_count=len(members),
                reference_session_id=family.reference_id,
                members=member_payloads,
                similarity_mean=round(
                    sum(
                        similarity
                        for _id, _session, _shift, similarity
                        in members
                    )
                    / len(members),
                    4,
                ),
                consensus_coverage=round(coverage, 4),
                consensus_confidence=round(confidence, 4),
                model_quality=quality,
                consensus_phase_model=consensus_model,
            )
        )

    return tuple(summaries)
