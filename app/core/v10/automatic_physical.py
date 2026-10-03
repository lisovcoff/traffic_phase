from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

APPROACHES = frozenset({"N", "S", "E", "W"})
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}
DEFAULT_ACTIVITY_THRESHOLD = 0.08
DEFAULT_SELECTIVITY_RATIO = 1.15
DEFAULT_STARTUP_LOST_S = 0.0


def _canonical_movement(value: Any) -> str | None:
    parts = str(value).strip().upper().replace("_", "").split("->")
    if len(parts) != 2 or parts[0] == parts[1]:
        return None
    if parts[0] not in APPROACHES or parts[1] not in APPROACHES:
        return None
    return f"{parts[0]}->{parts[1]}"


def _phase_names(schedule: Mapping[str, Any]) -> list[str]:
    raw = schedule.get("phase_names", ())
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        count = int(schedule.get("phase_count", 0))
        raw = [f"PHASE_{chr(ord('A') + i)}" for i in range(count)]
    names = [str(item).strip() for item in raw]
    if not names or len(set(names)) != len(names):
        raise ValueError("V9 phase names must be unique and non-empty")
    return names


def _activity_by_phase(result: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    schedule = result.get("schedule")
    if not isinstance(schedule, Mapping):
        raise ValueError("V9 result has no schedule")
    names = _phase_names(schedule)
    out = {name: {} for name in names}
    rows = schedule.get("stream_activity_by_phase", ())
    if not isinstance(rows, Sequence):
        return out
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        movement = _canonical_movement(row.get("stream", ""))
        values = row.get("event_probability_by_phase", {})
        if movement is None or not isinstance(values, Mapping):
            continue
        for name in names:
            try:
                value = float(values.get(name, 0.0))
            except (TypeError, ValueError):
                continue
            if value > 0.0:
                out[name][movement] = value
    return out


def _phase_durations(result: Mapping[str, Any]) -> dict[str, float]:
    raw = result["schedule"].get("baseline_duration_targets_s", {})
    if not isinstance(raw, Mapping):
        return {}
    out = {}
    for key, value in raw.items():
        try:
            duration = float(value)
        except (TypeError, ValueError):
            continue
        if duration > 0.0:
            out[str(key)] = duration
    return out


def _is_straight(movement: str) -> bool:
    source, target = movement.split("->", 1)
    return target == OPPOSITE[source]


def _semantic_name(green: frozenset[str]) -> str:
    # Prefer an observed straight movement to identify the phase family.
    # Protected turns such as N->E/E->N can belong to the same physical
    # N/S signal family as N->S; the turn's destination approach must not
    # reclassify the whole phase as "MIXED".
    straight = {
        item
        for item in green
        if _is_straight(item)
    }
    if straight & {"N->S", "S->N"}:
        base = "NS"
    elif straight & {"E->W", "W->E"}:
        base = "EW"
    else:
        sources = {
            item.split("->", 1)[0]
            for item in green
        }
        if sources and sources <= {"N", "S"}:
            base = "NS"
        elif sources and sources <= {"E", "W"}:
            base = "EW"
        else:
            base = "MIXED"

    has_turn = any(not _is_straight(item) for item in green)
    return f"{base}_{'TURN' if has_turn else 'THROUGH'}"


def _baseline_order(
    result: Mapping[str, Any],
    names: Sequence[str],
    period: float,
) -> list[str]:
    order: list[str] = []
    rows = result["schedule"].get("baseline_segments", ())
    if not isinstance(rows, Sequence):
        return order
    for row in rows:
        if not isinstance(row, Sequence) or len(row) < 3:
            continue
        start, end, index = float(row[0]), float(row[1]), int(row[2])
        if start >= period - 1e-9:
            break
        if 0 <= index < len(names) and end > start:
            phase = names[index]
            if not order or order[-1] != phase:
                order.append(phase)
    if len(order) > 1 and order[0] == order[-1]:
        order = order[:-1]
    return order


def _head_states(green: frozenset[str]) -> dict[str, dict[str, Any]]:
    """Build authoritative physical signal states for every approach.

    The renderer consumes these states directly. A missing traffic stream must
    therefore remain RED instead of changing the state of its reciprocal head.
    """
    states: dict[str, dict[str, Any]] = {}
    opposite = {"N": "S", "S": "N", "E": "W", "W": "E"}
    for approach in ("N", "S", "E", "W"):
        main = f"{approach}->{opposite[approach]}"
        arrows = sorted(
            movement
            for movement in green
            if movement.startswith(f"{approach}->")
            and movement != main
        )
        states[approach] = {
            "main": "GREEN" if main in green else "RED",
            "arrows": {
                movement: "GREEN"
                for movement in arrows
            },
        }
    return states


def infer_physical_signal_plan(
    result: Mapping[str, Any],
    *,
    activity_threshold: float = DEFAULT_ACTIVITY_THRESHOLD,
    selectivity_ratio: float = DEFAULT_SELECTIVITY_RATIO,
    startup_lost_s: float = DEFAULT_STARTUP_LOST_S,
) -> dict[str, Any]:
    """Infer physical movement groups from V9 phase signatures.

    Only observed canonical N/S/E/W movements are promoted to physical
    movements. Straight movements are main sections; turns are additional
    sections. Unobserved movements are never invented.
    """
    if not 0.0 <= float(activity_threshold) <= 1.0:
        raise ValueError("activity_threshold must be in [0, 1]")
    if float(selectivity_ratio) < 1.0:
        raise ValueError("selectivity_ratio must be >= 1")
    if float(startup_lost_s) < 0.0:
        raise ValueError("startup_lost_s must be >= 0")

    schedule = result.get("schedule")
    if not isinstance(schedule, Mapping):
        raise ValueError("V9 result has no schedule")
    period = float(schedule.get("period_s", 0.0))
    if period <= 0.0:
        raise ValueError("V9 period must be positive")

    names = _phase_names(schedule)
    activity = _activity_by_phase(result)
    durations = _phase_durations(result)
    movements = sorted(set().union(*(values.keys() for values in activity.values())))
    if not movements:
        raise ValueError("no canonical N/S/E/W movement evidence")

    WEAK_PHASE_EVIDENCE_THRESHOLD = 0.03
    WEAK_PHASE_SELECTIVITY_RATIO = max(1.25, float(selectivity_ratio))

    green_by_phase: dict[str, frozenset[str]] = {}
    confidence_by_phase: dict[str, float] = {}

    for phase in names:
        green: set[str] = set()
        evidence: list[float] = []
        for movement in movements:
            values = [activity[item].get(movement, 0.0) for item in names]
            probability = float(activity[phase].get(movement, 0.0))
            weakest = min(values)
            peak = max(values)
            if (
                probability >= float(activity_threshold)
                and probability >= float(selectivity_ratio) * max(weakest, 0.001)
            ):
                green.add(movement)
                evidence.append(
                    max(
                        0.0,
                        min(
                            1.0,
                            (probability - weakest) / max(peak - weakest, 0.001),
                        ),
                    )
                )
        if not green:
            candidates: list[tuple[float, float, str]] = []
            for movement in movements:
                values = [
                    float(activity[item].get(movement, 0.0))
                    for item in names
                ]
                probability = float(activity[phase].get(movement, 0.0))
                other_peak = max(
                    (
                        value
                        for item, value in zip(names, values)
                        if item != phase
                    ),
                    default=0.0,
                )
                if (
                    probability >= WEAK_PHASE_EVIDENCE_THRESHOLD
                    and probability >= WEAK_PHASE_SELECTIVITY_RATIO
                    * max(other_peak, 0.001)
                ):
                    candidates.append(
                        (
                            probability,
                            probability / max(other_peak, 0.001),
                            movement,
                        )
                    )
            if candidates:
                best_probability = max(item[0] for item in candidates)
                for probability, _ratio, movement in candidates:
                    if probability >= 0.75 * best_probability:
                        green.add(movement)
                        evidence.append(
                            min(
                                1.0,
                                probability
                                / max(best_probability, 0.001),
                            )
                        )

        if not green:
            raise ValueError(
                f"phase {phase!r} has no supported physical green movements"
            )

        green_set = frozenset(sorted(green))
        green_by_phase[phase] = green_set
        confidence_by_phase[phase] = (
            sum(evidence) / len(evidence) if evidence else 0.0
        )

    # Turns are assigned independently from phase-selective evidence.
    # A physical arrow requires a clear phase peak. No opposing-through,
    # reciprocal-pulling, or geometry-specific heuristic is used here.
    TURN_CANDIDATE_EVIDENCE_THRESHOLD = 0.03
    TURN_CANDIDATE_SELECTIVITY_RATIO = max(1.25, float(selectivity_ratio))
    TURN_CANDIDATE_MIN_MARGIN = 0.02

    # Keep straight assignments from the primary evidence pass, but assign
    # every non-straight movement to at most one statistically dominant phase.
    for phase in names:
        green_by_phase[phase] = frozenset(
            movement
            for movement in green_by_phase[phase]
            if _is_straight(movement)
        )

    suppressed_turn_movements_by_phase: dict[str, list[str]] = {
        phase: [] for phase in names
    }
    turn_candidates_by_phase: dict[str, set[str]] = {
        phase: set() for phase in names
    }

    for movement in movements:
        if _is_straight(movement):
            continue
        values = {
            phase: float(activity[phase].get(movement, 0.0))
            for phase in names
        }
        ranked = sorted(values.items(), key=lambda item: item[1], reverse=True)
        best_phase, best_probability = ranked[0]
        second_probability = ranked[1][1] if len(ranked) > 1 else 0.0
        if (
            best_probability >= TURN_CANDIDATE_EVIDENCE_THRESHOLD
            and best_probability >= TURN_CANDIDATE_SELECTIVITY_RATIO * max(second_probability, 0.001)
            and best_probability - second_probability >= TURN_CANDIDATE_MIN_MARGIN
        ):
            turn_candidates_by_phase[best_phase].add(movement)
        else:
            for phase, probability in values.items():
                if probability >= TURN_CANDIDATE_EVIDENCE_THRESHOLD:
                    suppressed_turn_movements_by_phase[phase].append(movement)

    # A protected-turn candidate is accepted only when the phase has enough
    # same-phase straight traffic to support the extra physical arrow. This
    # prevents traffic leakage from dominating a short V9 split and producing
    # a phantom third physical phase. Turn-only phases remain valid when they
    # contain a reciprocal pair of turn movements.
    for phase in names:
        candidates = turn_candidates_by_phase[phase]
        if not candidates:
            continue

        straight_evidence = sum(
            float(activity[phase].get(movement, 0.0))
            for movement in movements
            if _is_straight(movement)
        )
        turn_evidence = sum(
            float(activity[phase].get(movement, 0.0))
            for movement in candidates
        )

        reciprocal_pair = any(
            f"{target}->{source}" in candidates
            for movement in candidates
            for source, target in [movement.split("->", 1)]
        )

        if straight_evidence > 0.0 and turn_evidence <= straight_evidence:
            green = set(green_by_phase[phase])
            green.update(candidates)
            green_by_phase[phase] = frozenset(sorted(green))
            continue

        if straight_evidence <= 0.0 and reciprocal_pair:
            green = set(green_by_phase[phase])
            green.update(candidates)
            green_by_phase[phase] = frozenset(sorted(green))
            continue

        for movement in sorted(candidates):
            suppressed_turn_movements_by_phase[phase].append(movement)

    # Preserve the physical NS/EW main sections when V9 statistically splits
    # the two reciprocal straight streams between phases.
    straight_by_axis = {
        "NS": ("N->S", "S->N"),
        "EW": ("E->W", "W->E"),
    }
    for axis, straight_movements in straight_by_axis.items():
        observed = {
            movement
            for movement in straight_movements
            if max(
                activity[phase].get(movement, 0.0)
                for phase in names
            ) >= 0.03
        }
        if not observed:
            continue
        for phase in names:
            green = set(green_by_phase[phase])
            if _semantic_name(frozenset(green)) != f"{axis}_THROUGH":
                continue
            green.update(straight_movements)
            green_by_phase[phase] = frozenset(sorted(green))

    # Resolve physical names only after all weak-evidence rescue has completed.
    # This keeps a phase with N/S straight + protected turns named NS_TURN
    # rather than retaining a stale NS_THROUGH name from the initial pass.
    mapping: dict[str, str] = {}
    used: defaultdict[str, int] = defaultdict(int)
    signature_names: dict[tuple[str, ...], str] = {}
    for phase in names:
        signature = tuple(sorted(green_by_phase[phase]))
        if signature in signature_names:
            mapping[phase] = signature_names[signature]
            continue
        base = _semantic_name(green_by_phase[phase])
        used[base] += 1
        physical_name = (
            base if used[base] == 1 else f"{base}_{used[base]}"
        )
        signature_names[signature] = physical_name
        mapping[phase] = physical_name

    phases = []
    emitted_names: set[str] = set()

    for phase in names:
        green = green_by_phase[phase]
        additional = frozenset(
            item for item in green if not _is_straight(item)
        )
        physical_name = mapping[phase]
        if physical_name in emitted_names:
            continue
        emitted_names.add(physical_name)
        phases.append(
            {
                "name": physical_name,
                "green_movements": sorted(green),
                "additional_movements": sorted(additional),
                "duration_s": round(
                    float(
                        durations.get(
                            phase,
                            period / max(1, len(names)),
                        )
                    ),
                    6,
                ),
                "source_phase": phase,
                "heads": _head_states(green),
            }
        )

    by_name = {item["name"]: item for item in phases}
    stages = []
    rows = result["schedule"].get("baseline_segments", ())
    if isinstance(rows, Sequence):
        for row in rows:
            if not isinstance(row, Sequence) or len(row) < 3:
                continue
            start, end, index = float(row[0]), float(row[1]), int(row[2])
            if start >= period - 1e-9:
                break
            if end <= start or index < 0 or index >= len(names):
                continue
            end = min(end, period)
            phase = names[index]
            spec = by_name[mapping[phase]]
            stages.append(
                {
                    "stage_id": len(stages) + 1,
                    "name": spec["name"],
                    "phase_start": round(start, 6),
                    "phase_end": round(end, 6),
                    "active_movements": list(spec["green_movements"]),
                    "additional_movements": list(spec["additional_movements"]),
                    "source_phase": phase,
                    "heads": _head_states(spec["green_movements"]),
                }
            )

    merged_stages: list[dict[str, Any]] = []
    for stage in stages:
        if (
            merged_stages
            and merged_stages[-1]["name"] == stage["name"]
            and merged_stages[-1]["heads"] == stage["heads"]
            and merged_stages[-1]["active_movements"]
            == stage["active_movements"]
        ):
            merged_stages[-1]["phase_end"] = stage["phase_end"]
        else:
            merged_stages.append(stage)
    stages = merged_stages
    for index, stage in enumerate(stages, start=1):
        stage["stage_id"] = index

    topology = {
        approach: {
            "main": f"{approach}->{OPPOSITE[approach]}",
            "arrows": [],
        }
        for approach in ("N", "S", "E", "W")
    }
    for spec in phases:
        for movement in spec["additional_movements"]:
            source = movement.split("->", 1)[0]
            topology[source]["arrows"].append(movement)
    for approach in topology:
        topology[approach]["arrows"] = sorted(
            set(topology[approach]["arrows"])
        )

    confidence = (
        sum(confidence_by_phase.values()) / len(confidence_by_phase)
        if confidence_by_phase
        else 0.0
    )
    recording_start_value = result.get("recording_start_timestamp_ms")
    analysis_base_value = result.get("analysis_base_timestamp_ms")
    event_base_value = result.get("event_base_timestamp_ms")
    if recording_start_value is None and analysis_base_value is None:
        recording_start_value = 0.0
        analysis_base_value = 0.0
    elif recording_start_value is None:
        recording_start_value = analysis_base_value
    elif analysis_base_value is None:
        analysis_base_value = recording_start_value
    try:
        model_anchor_s = (
            float(analysis_base_value) - float(recording_start_value)
        ) / 1000.0
    except (TypeError, ValueError):
        model_anchor_s = 0.0

    try:
        physical_anchor_s = (
            model_anchor_s - float(startup_lost_s)
        )
    except (TypeError, ValueError):
        physical_anchor_s = model_anchor_s

    regime = result.get("regime_detection")
    slice_start_s = 0.0
    if isinstance(regime, Mapping):
        try:
            slice_start_s = float(
                regime.get("selected_window_start_s", 0.0)
            )
        except (TypeError, ValueError):
            slice_start_s = 0.0

    try:
        event_base_offset_s = (
            float(event_base_value) - float(recording_start_value)
        ) / 1000.0
    except (TypeError, ValueError):
        event_base_offset_s = None

    return {
        "enabled": True,
        "auto_inferred": True,
        "model": "v10_automatic_physical_signal_plan",
        "cycle_seconds": period,
        "mapping": mapping,
        "time_offset_s": round(float(physical_anchor_s), 6),
        "recording_start_timestamp_ms": float(recording_start_value),
        "analysis_base_timestamp_ms": float(analysis_base_value),
        "timing": {
            "phase_anchor_model_s": round(float(model_anchor_s), 6),
            "phase_anchor_physical_s": round(float(physical_anchor_s), 6),
            "startup_lost_s": round(float(startup_lost_s), 6),
            "slice_start_s": round(float(slice_start_s), 6),
            "event_base_offset_s": (
                round(float(event_base_offset_s), 6)
                if event_base_offset_s is not None
                else None
            ),
        },
        "confidence": round(float(confidence), 4),
        "phases": phases,
        "stages": stages,
        "topology": topology,
        "inference": {
            "activity_threshold": float(activity_threshold),
            "selectivity_ratio": float(selectivity_ratio),
            "phase_confidence": {
                key: round(float(value), 4)
                for key, value in confidence_by_phase.items()
            },
            "turn_candidate_evidence_threshold": TURN_CANDIDATE_EVIDENCE_THRESHOLD,
            "turn_candidate_selectivity_ratio": TURN_CANDIDATE_SELECTIVITY_RATIO,
            "startup_lost_s": float(startup_lost_s),
            "suppressed_turn_movements_by_phase": {
                key: value
                for key, value in suppressed_turn_movements_by_phase.items()
            },
            "physical_phase_count": len(phases),
            "source": "V9 stream_activity_by_phase",
            "unobserved_movements_are_not_invented": True,
        },
    }


__all__ = [
    "DEFAULT_ACTIVITY_THRESHOLD",
    "DEFAULT_SELECTIVITY_RATIO",
    "DEFAULT_STARTUP_LOST_S",
    "infer_physical_signal_plan",
]
