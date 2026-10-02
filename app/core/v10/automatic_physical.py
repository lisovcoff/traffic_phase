from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

APPROACHES = frozenset({"N", "S", "E", "W"})
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}
DEFAULT_ACTIVITY_THRESHOLD = 0.08
DEFAULT_SELECTIVITY_RATIO = 1.15


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

    PROTECTED_TURN_MAIN_RATIO = 2.0
    PROTECTED_TURN_PAIR_SUPPORT = 0.20

    def protected_turn_group(
        phase: str,
        candidates: Sequence[str],
    ) -> bool:
        candidate_set = set(candidates)

        strong_turns = [
            movement
            for movement in candidate_set
            if activity[phase].get(movement, 0.0)
            >= PROTECTED_TURN_PAIR_SUPPORT
        ]
        if len(strong_turns) >= 2:
            sources = {
                movement.split("->", 1)[0]
                for movement in strong_turns
            }
            if sources <= {"N", "S"} or sources <= {"E", "W"}:
                return True

        for movement in candidate_set:
            source, target = movement.split("->", 1)
            reverse = f"{target}->{source}"
            if (
                reverse in candidate_set
                and activity[phase].get(movement, 0.0)
                >= PROTECTED_TURN_PAIR_SUPPORT
                and activity[phase].get(reverse, 0.0)
                >= PROTECTED_TURN_PAIR_SUPPORT
            ):
                return True

        for source in {
            item.split("->", 1)[0]
            for item in candidate_set
        }:
            straight = f"{source}->{OPPOSITE[source]}"
            turn_probabilities = [
                activity[phase].get(item, 0.0)
                for item in candidate_set
                if item.startswith(f"{source}->")
            ]
            if not turn_probabilities:
                continue
            strongest_turn = max(turn_probabilities)
            main_probability = activity[phase].get(straight, 0.0)
            if (
                strongest_turn >= float(activity_threshold) * 0.5
                and main_probability
                >= PROTECTED_TURN_MAIN_RATIO * strongest_turn
            ):
                return True

        return False

    suppressed_turn_movements_by_phase: dict[str, list[str]] = {}
    for phase in names:
        green = set(green_by_phase[phase])
        turns = [
            movement
            for movement in green
            if not _is_straight(movement)
        ]
        protected: set[str] = set()
        if turns and protected_turn_group(phase, turns):
            protected.update(turns)

        by_source: defaultdict[str, list[str]] = defaultdict(list)
        for movement in turns:
            by_source[movement.split("->", 1)[0]].append(movement)

        for source_candidates in by_source.values():
            if protected_turn_group(phase, source_candidates):
                protected.update(source_candidates)

        for movement in turns:
            source, target = movement.split("->", 1)
            reverse = f"{target}->{source}"
            if reverse in turns and protected_turn_group(
                phase,
                (movement, reverse),
            ):
                protected.update((movement, reverse))

        suppressed = sorted(set(turns) - protected)
        if suppressed:
            green.difference_update(suppressed)
        suppressed_turn_movements_by_phase[phase] = suppressed

        if not green:
            straight_candidates = []
            for movement in movements:
                if not _is_straight(movement):
                    continue
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
                    probability >= 0.03
                    and probability
                    >= max(1.25, float(selectivity_ratio))
                    * max(other_peak, 0.001)
                ):
                    straight_candidates.append(
                        (probability, movement)
                    )
            if straight_candidates:
                best_probability = max(
                    probability
                    for probability, _movement in straight_candidates
                )
                green.update(
                    movement
                    for probability, movement in straight_candidates
                    if probability >= 0.75 * best_probability
                )

        green_by_phase[phase] = frozenset(sorted(green))

    # A weak reciprocal turn is only restored when it also satisfies the same
    # protected-turn criterion. Permissive traffic cannot create a physical
    # arrow by itself.
    for phase in names:
        green = set(green_by_phase[phase])
        for movement in movements:
            if _is_straight(movement):
                continue
            source, target = movement.split("->", 1)
            reverse = f"{target}->{source}"
            if reverse not in movements:
                continue
            candidate_movements = (movement, reverse)
            pair_ok = True
            for candidate in candidate_movements:
                values = {
                    item: float(activity[item].get(candidate, 0.0))
                    for item in names
                }
                probability = values[phase]
                other_peak = max(
                    (
                        value
                        for item, value in values.items()
                        if item != phase
                    ),
                    default=0.0,
                )
                if (
                    probability < 0.03
                    or max(values.values(), default=0.0) != probability
                    or probability
                    < max(1.25, float(selectivity_ratio))
                    * max(other_peak, 0.001)
                ):
                    pair_ok = False
                    break
            if pair_ok and protected_turn_group(
                phase,
                candidate_movements,
            ):
                green.update(candidate_movements)
        green_by_phase[phase] = frozenset(sorted(green))

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
    if recording_start_value is None and analysis_base_value is None:
        recording_start_value = 0.0
        analysis_base_value = 0.0
    elif recording_start_value is None:
        recording_start_value = analysis_base_value
    elif analysis_base_value is None:
        analysis_base_value = recording_start_value
    try:
        time_offset_s = (
            float(analysis_base_value) - float(recording_start_value)
        ) / 1000.0
    except (TypeError, ValueError):
        time_offset_s = 0.0
    return {
        "enabled": True,
        "auto_inferred": True,
        "model": "v10_automatic_physical_signal_plan",
        "cycle_seconds": period,
        "mapping": mapping,
        "time_offset_s": round(float(time_offset_s), 6),
        "recording_start_timestamp_ms": float(recording_start_value),
        "analysis_base_timestamp_ms": float(analysis_base_value),
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
            "protected_turn_main_ratio": PROTECTED_TURN_MAIN_RATIO,
            "protected_turn_pair_support": PROTECTED_TURN_PAIR_SUPPORT,
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
    "infer_physical_signal_plan",
]
