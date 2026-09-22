from __future__ import annotations

from dataclasses import dataclass
from math import floor
from statistics import median
from typing import Sequence

from app.core.event_phase_discovery import (
    EventPhase,
    EventPhaseDiscovery,
    EventPhaseDiscoveryResult,
)
from app.core.models import EventType, TrajectoryEvent
from app.core.reconstruction import (
    GOOD_MODEL_MIN_COVERAGE,
    GOOD_MODEL_MIN_CYCLE_CONFIDENCE,
    GOOD_MODEL_MIN_PHASE_CONFIDENCE,
    PARTIAL_MODEL_MIN_COVERAGE,
    PARTIAL_MODEL_MIN_CYCLE_CONFIDENCE,
    PARTIAL_MODEL_MIN_PHASE_CONFIDENCE,
    SessionReconstruction,
    phase_model_ambiguity_reason,
)


SIGNATURE_BINS = 60
CYCLE_TOLERANCE_SECONDS = 6.0
MIN_FAMILY_SIMILARITY = 0.82
MIN_WEAK_COARSE_SIMILARITY = 0.82
MIN_WEAK_FINE_SIMILARITY = 0.45
AMBIGUOUS_FAMILY_SCORE_MARGIN = 0.03

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
    coarse_similarity: float
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
            "coarse_similarity": self.coarse_similarity,
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
    consensus_model_quality: str
    model_quality: str
    consensus_phase_model: dict[str, object] | None
    pooled_event_count: int
    pooled_cycle_count: int
    pooled_coverage: float | None
    pooled_confidence: float | None
    pooled_model_quality: str | None
    pooled_phase_model: dict[str, object] | None
    pooled_movement_candidate_count: int
    pooled_movement_stage_count: int
    pooling_status: str

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
            "consensus_model_quality": self.consensus_model_quality,
            "model_quality": self.model_quality,
            "consensus_phase_model": self.consensus_phase_model,
            "pooled_event_count": self.pooled_event_count,
            "pooled_cycle_count": self.pooled_cycle_count,
            "pooled_coverage": self.pooled_coverage,
            "pooled_confidence": self.pooled_confidence,
            "pooled_model_quality": self.pooled_model_quality,
            "pooled_phase_model": self.pooled_phase_model,
            "pooled_movement_candidate_count": (
                self.pooled_movement_candidate_count
            ),
            "pooled_movement_stage_count": (
                self.pooled_movement_stage_count
            ),
            "pooling_status": self.pooling_status,
        }


@dataclass
class _FamilyWork:
    reference_id: int
    reference: SessionReconstruction
    reference_signature: tuple[int, ...]
    reference_axis_signature: tuple[int, ...]
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


def _raw_axis_signature(
    session: SessionReconstruction,
    events: Sequence[TrajectoryEvent],
    *,
    bins: int = SIGNATURE_BINS,
) -> tuple[int, ...]:
    model = session.phase_model
    if model is None or bins <= 0:
        return ()
    cycle = float(model.cycle_seconds)
    if cycle <= 0:
        return ()
    counts = [
        [0.0 for _ in range(bins)],
        [0.0 for _ in range(bins)],
    ]
    origin_ms = int(model.origin_timestamp_ms)
    for event in events:
        if event.event_type not in {
            EventType.RELEASE,
            EventType.CROSSING,
        }:
            continue
        if event.approach in {"N", "S"}:
            axis_index = 0
        elif event.approach in {"E", "W"}:
            axis_index = 1
        else:
            continue
        position = (
            ((event.timestamp_ms - origin_ms) / 1000.0)
            % cycle
        )
        bin_index = min(
            bins - 1,
            int(position / cycle * bins),
        )
        weight = float(event.confidence)
        if event.event_type == EventType.CROSSING:
            weight *= 0.5
        counts[axis_index][bin_index] += max(0.0, weight)

    dilated = [values[:] for values in counts]
    for axis_index in range(2):
        for index in range(bins):
            dilated[axis_index][index] = max(
                counts[axis_index][index],
                counts[axis_index][(index - 1) % bins],
                counts[axis_index][(index + 1) % bins],
            )

    signature: list[int] = []
    for index in range(bins):
        ns = dilated[0][index]
        ew = dilated[1][index]
        if ns <= 0.0 and ew <= 0.0:
            signature.append(0)
        elif ns >= ew:
            signature.append(1)
        else:
            signature.append(2)
    return tuple(signature)


def _axis_signature_similarity(
    left: Sequence[int],
    right: Sequence[int],
) -> float:
    if not left or len(left) != len(right):
        return 0.0
    exact = 0.0
    conflict = 0.0
    missing = 0.0
    for a, b in zip(left, right):
        if a and b:
            if a == b:
                exact += 1.0
            else:
                conflict += 1.0
        elif bool(a) != bool(b):
            missing += 1.0
    denominator = exact + conflict + 0.20 * missing
    if denominator <= 0:
        return 0.0
    return exact / denominator


def _best_axis_alignment(
    reference: Sequence[int],
    candidate: Sequence[int],
) -> tuple[int, float]:
    if not reference or len(reference) != len(candidate):
        return 0, 0.0
    best_shift = 0
    best_similarity = -1.0
    for shift in range(len(reference)):
        similarity = _axis_signature_similarity(
            reference,
            _rotated(candidate, shift),
        )
        if similarity > best_similarity:
            best_similarity = similarity
            best_shift = shift
    return best_shift, max(0.0, best_similarity)


def _fine_similarity_at_shift(
    reference: Sequence[int],
    candidate: Sequence[int],
    shift: int,
) -> float:
    if not reference or len(reference) != len(candidate):
        return 0.0
    return _signature_similarity(
        reference,
        _rotated(candidate, shift),
    )


def _phase_confidence_from_model(
    model: EventPhaseDiscoveryResult,
) -> float:
    if not model.phases:
        return 0.0
    return sum(
        float(phase.confidence)
        for phase in model.phases
    ) / len(model.phases)


def _aligned_pooled_events(
    members: Sequence[
        tuple[int, SessionReconstruction, int, float]
    ],
    segment_events: Sequence[Sequence[TrajectoryEvent]],
    *,
    cycle_seconds: float,
) -> tuple[tuple[TrajectoryEvent, ...], int]:
    pooled: list[TrajectoryEvent] = []
    base_cycle = 1
    pooled_cycle_count = 0

    for session_id, session, shift, _similarity in members:
        if not 1 <= session_id <= len(segment_events):
            continue
        model = session.phase_model
        if model is None:
            continue
        local_cycle = float(model.cycle_seconds)
        if local_cycle <= 0:
            continue
        raw = [
            event
            for event in segment_events[session_id - 1]
            if (
                event.event_type
                in {EventType.RELEASE, EventType.CROSSING}
                and event.approach in _APPROACH_BITS
            )
        ]
        if not raw:
            continue

        origin_ms = int(model.origin_timestamp_ms)
        indexed: list[tuple[TrajectoryEvent, int, float]] = []
        cycle_indices: list[int] = []
        for event in raw:
            elapsed_cycles = (
                (event.timestamp_ms - origin_ms)
                / 1000.0
                / local_cycle
            )
            cycle_index = floor(elapsed_cycles)
            local_fraction = elapsed_cycles - cycle_index
            indexed.append(
                (event, cycle_index, local_fraction)
            )
            cycle_indices.append(cycle_index)

        min_cycle = min(cycle_indices)
        max_cycle = max(cycle_indices)
        span_cycles = max_cycle - min_cycle + 1
        pooled_cycle_count += span_cycles

        shift_fraction = shift / SIGNATURE_BINS
        for event, cycle_index, local_fraction in indexed:
            aligned = local_fraction - shift_fraction
            cycle_adjust = floor(aligned)
            aligned_fraction = aligned - cycle_adjust
            synthetic_cycle = (
                base_cycle
                + cycle_index
                - min_cycle
                + cycle_adjust
            )
            synthetic_timestamp_ms = int(
                round(
                    (
                        synthetic_cycle
                        + aligned_fraction
                    )
                    * cycle_seconds
                    * 1000.0
                )
            )
            pooled.append(
                TrajectoryEvent(
                    event_type=event.event_type,
                    timestamp_ms=synthetic_timestamp_ms,
                    approach=event.approach,
                    movement=event.movement,
                    confidence=event.confidence,
                    quality=event.quality,
                )
            )

        base_cycle += span_cycles + 2

    pooled.sort(
        key=lambda event: (
            event.timestamp_ms,
            event.event_type.value,
            event.approach,
            event.movement,
        )
    )
    return tuple(pooled), pooled_cycle_count


def _phase_model_payload(
    model: EventPhaseDiscoveryResult,
    *,
    confidence: float,
) -> dict[str, object]:
    payload = model.to_dict()
    payload.pop("profiles", None)
    payload["model_type"] = "cross_session_pooled_evidence"
    payload["confidence"] = round(confidence, 4)
    payload["stages"] = payload["phases"]
    total = (
        model.supporting_event_count
        + model.contradictory_event_count
    )
    payload["support_ratio"] = (
        round(model.supporting_event_count / total, 4)
        if total
        else None
    )
    return payload


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
    *,
    segment_events: Sequence[Sequence[TrajectoryEvent]] | None = None,
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
        raw_events = (
            segment_events[session_id - 1]
            if (
                segment_events is not None
                and 1 <= session_id <= len(segment_events)
            )
            else ()
        )
        axis_signature = _raw_axis_signature(
            session,
            raw_events,
        )
        cycle = float(session.phase_model.cycle_seconds)
        candidates: list[
            tuple[
                float,
                _FamilyWork,
                int,
                float,
                float,
            ]
        ] = []

        for family in families:
            reference_cycle = float(
                family.reference.phase_model.cycle_seconds
            )
            if (
                abs(cycle - reference_cycle)
                > CYCLE_TOLERANCE_SECONDS
            ):
                continue

            strong_pair = (
                session.model_quality != "INSUFFICIENT"
                and family.reference.model_quality
                != "INSUFFICIENT"
            )
            if (
                not strong_pair
                and axis_signature
                and family.reference_axis_signature
            ):
                shift, coarse_similarity = (
                    _best_axis_alignment(
                        family.reference_axis_signature,
                        axis_signature,
                    )
                )
                fine_similarity = _fine_similarity_at_shift(
                    family.reference_signature,
                    signature,
                    shift,
                )
                if (
                    coarse_similarity
                    < MIN_WEAK_COARSE_SIMILARITY
                    or fine_similarity
                    < MIN_WEAK_FINE_SIMILARITY
                ):
                    continue
                score = (
                    0.70 * coarse_similarity
                    + 0.30 * fine_similarity
                )
            elif not strong_pair:
                # Backward-compatible fallback for callers that do not retain
                # raw segment events. Production archive analysis supplies raw
                # evidence and therefore uses the coarse-axis branch above.
                shift, fine_similarity = _best_alignment(
                    family.reference_signature,
                    signature,
                )
                coarse_similarity = 0.0
                if fine_similarity < MIN_WEAK_FINE_SIMILARITY:
                    continue
                score = fine_similarity
            else:
                shift, fine_similarity = _best_alignment(
                    family.reference_signature,
                    signature,
                )
                coarse_similarity = (
                    _axis_signature_similarity(
                        family.reference_axis_signature,
                        _rotated(axis_signature, shift),
                    )
                    if (
                        axis_signature
                        and family.reference_axis_signature
                    )
                    else 0.0
                )
                if fine_similarity < MIN_FAMILY_SIMILARITY:
                    continue
                score = (
                    fine_similarity
                    + 0.05 * coarse_similarity
                )

            candidates.append(
                (
                    score,
                    family,
                    shift,
                    fine_similarity,
                    coarse_similarity,
                )
            )

        candidates.sort(
            key=lambda item: item[0],
            reverse=True,
        )
        chosen = candidates[0] if candidates else None
        if (
            chosen is not None
            and session.model_quality == "INSUFFICIENT"
            and len(candidates) > 1
            and (
                chosen[0] - candidates[1][0]
                < AMBIGUOUS_FAMILY_SCORE_MARGIN
            )
        ):
            chosen = None

        if chosen is None:
            families.append(
                _FamilyWork(
                    reference_id=session_id,
                    reference=session,
                    reference_signature=signature,
                    reference_axis_signature=axis_signature,
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

        (
            _score,
            best_family,
            best_shift,
            best_similarity,
            _coarse_similarity,
        ) = chosen
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
        consensus_quality = _family_quality(
            coverage=coverage,
            cycle_confidence=cycle_confidence,
            phase_confidence=phase_confidence,
        )

        pooled_events: tuple[TrajectoryEvent, ...] = ()
        pooled_cycle_count = 0
        pooled_result: EventPhaseDiscoveryResult | None = None
        pooled_coverage: float | None = None
        pooled_confidence: float | None = None
        pooled_quality: str | None = None
        pooled_model: dict[str, object] | None = None
        pooling_status = "not_available"

        if segment_events is None:
            pooling_status = "raw_events_unavailable"
        elif len(members) < 2:
            pooling_status = "not_enough_members"
        else:
            pooled_events, pooled_cycle_count = (
                _aligned_pooled_events(
                    members,
                    segment_events,
                    cycle_seconds=cycle_seconds,
                )
            )
            if not pooled_events:
                pooling_status = "no_raw_events"
            else:
                try:
                    pooled_result = EventPhaseDiscovery(
                        bin_seconds=2.0,
                    ).discover(
                        pooled_events,
                        cycle_seconds=cycle_seconds,
                    )
                except ValueError:
                    pooling_status = "phase_discovery_failed"
                else:
                    pooled_coverage = float(
                        pooled_result.cycle_coverage
                    )
                    pooled_phase_confidence = (
                        _phase_confidence_from_model(
                            pooled_result
                        )
                    )
                    pooled_confidence = min(
                        cycle_confidence,
                        pooled_phase_confidence,
                    )
                    pooled_quality = _family_quality(
                        coverage=pooled_coverage,
                        cycle_confidence=cycle_confidence,
                        phase_confidence=(
                            pooled_phase_confidence
                        ),
                    )
                    ambiguity = phase_model_ambiguity_reason(
                        pooled_result
                    )
                    if ambiguity is not None:
                        pooled_quality = "INSUFFICIENT"
                        pooling_status = "ambiguous_phase_model"
                    else:
                        pooling_status = "ok"
                    pooled_model = _phase_model_payload(
                        pooled_result,
                        confidence=pooled_confidence,
                    )

        quality = (
            pooled_quality
            if pooled_quality is not None
            else consensus_quality
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
                coarse_similarity=round(
                    (
                        _axis_signature_similarity(
                            family.reference_axis_signature,
                            _rotated(
                                _raw_axis_signature(
                                    session,
                                    segment_events[
                                        session_id - 1
                                    ],
                                ),
                                shift,
                            ),
                        )
                        if (
                            segment_events is not None
                            and family.reference_axis_signature
                            and 1 <= session_id <= len(segment_events)
                        )
                        else 0.0
                    ),
                    4,
                ),
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
                consensus_model_quality=consensus_quality,
                model_quality=quality,
                consensus_phase_model=consensus_model,
                pooled_event_count=len(pooled_events),
                pooled_cycle_count=pooled_cycle_count,
                pooled_coverage=(
                    round(pooled_coverage, 4)
                    if pooled_coverage is not None
                    else None
                ),
                pooled_confidence=(
                    round(pooled_confidence, 4)
                    if pooled_confidence is not None
                    else None
                ),
                pooled_model_quality=pooled_quality,
                pooled_phase_model=pooled_model,
                pooled_movement_candidate_count=(
                    len(
                        pooled_result.distinct_movement_candidates
                    )
                    if pooled_result is not None
                    else 0
                ),
                pooled_movement_stage_count=(
                    len(pooled_result.movement_stages)
                    if pooled_result is not None
                    else 0
                ),
                pooling_status=pooling_status,
            )
        )

    return tuple(summaries)
