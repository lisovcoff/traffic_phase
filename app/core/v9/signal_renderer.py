from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence


DEFAULT_ACTIVITY_THRESHOLD = 0.05
DEFAULT_YELLOW_DURATION_SECONDS = 3.0
DEFAULT_RED_YELLOW_DURATION_SECONDS = 2.0


def _phase_name(phase_id: int) -> str:
    return f"PHASE_{chr(ord('A') + int(phase_id))}"


def _phase_id_from_name(name: str) -> int:
    prefix = "PHASE_"
    if not str(name).startswith(prefix):
        raise ValueError(f"invalid phase name: {name!r}")
    suffix = str(name)[len(prefix) :].strip()
    if len(suffix) != 1 or not suffix.isalpha():
        raise ValueError(f"invalid phase name: {name!r}")
    return ord(suffix.upper()) - ord("A")


def _as_float(value: Any) -> float:
    return float(value)


def _find_segment(
    segments: Sequence[Sequence[Any]],
    timestamp_s: float,
) -> tuple[float, float, int] | None:
    for raw in segments:
        if len(raw) < 3:
            continue
        start, end, phase_id = (
            _as_float(raw[0]),
            _as_float(raw[1]),
            int(raw[2]),
        )
        if start <= timestamp_s < end:
            return start, end, phase_id
    if segments:
        first = segments[0]
        if len(first) >= 3 and timestamp_s < _as_float(first[0]):
            return (
                _as_float(first[0]),
                _as_float(first[1]),
                int(first[2]),
            )
        last = segments[-1]
        if len(last) >= 3:
            return (
                _as_float(last[0]),
                _as_float(last[1]),
                int(last[2]),
            )
    return None


def _adjacent_phase(
    segments: Sequence[Sequence[Any]],
    index: int,
    direction: int,
) -> int | None:
    if not segments:
        return None
    target = index + direction
    if 0 <= target < len(segments):
        return int(segments[target][2])
    return int(segments[target % len(segments)][2])


def build_signal_model(
    result: Mapping[str, Any],
    *,
    activity_threshold: float = DEFAULT_ACTIVITY_THRESHOLD,
) -> dict[str, Any]:
    schedule = result.get("schedule")
    if not isinstance(schedule, Mapping):
        raise ValueError("V9 result has no schedule")
    period = _as_float(schedule.get("period_s", 0.0))
    if period <= 0:
        raise ValueError("V9 period must be positive")

    phase_count = int(schedule.get("phase_count", 0))
    if phase_count <= 0:
        raise ValueError("V9 phase_count must be positive")

    activity: dict[str, dict[int, float]] = defaultdict(dict)
    streams = schedule.get("stream_activity_by_phase", ())
    for item in streams:
        if not isinstance(item, Mapping):
            continue
        movement = str(item.get("stream", "")).strip()
        probabilities = item.get("event_probability_by_phase", {})
        if not movement or not isinstance(probabilities, Mapping):
            continue
        for name, value in probabilities.items():
            try:
                phase_id = _phase_id_from_name(str(name))
            except ValueError:
                continue
            activity[movement][phase_id] = _as_float(value)

    movement_names = sorted(activity)
    approaches: dict[str, list[str]] = defaultdict(list)
    for movement in movement_names:
        approach = movement.split("->", 1)[0].strip()
        if approach:
            approaches[approach].append(movement)

    for movement_list in approaches.values():
        movement_list.sort()

    return {
        "period_s": period,
        "phase_count": phase_count,
        "phase_names": [
            str(name)
            for name in schedule.get(
                "phase_names",
                [_phase_name(index) for index in range(phase_count)],
            )
        ],
        "segments": [
            [float(row[0]), float(row[1]), int(row[2])]
            for row in schedule.get("baseline_segments", ())
            if isinstance(row, Sequence) and len(row) >= 3
        ],
        "activity": {
            movement: {
                int(phase_id): float(probability)
                for phase_id, probability in probabilities.items()
            }
            for movement, probabilities in activity.items()
        },
        "approaches": {
            approach: list(movements)
            for approach, movements in sorted(approaches.items())
        },
        "activity_threshold": float(activity_threshold),
    }


def signal_state_at(
    result: Mapping[str, Any],
    timestamp_s: float,
    *,
    yellow_duration_seconds: float = DEFAULT_YELLOW_DURATION_SECONDS,
    red_yellow_duration_seconds: float = DEFAULT_RED_YELLOW_DURATION_SECONDS,
    activity_threshold: float = DEFAULT_ACTIVITY_THRESHOLD,
) -> dict[str, Any]:
    if timestamp_s < 0:
        raise ValueError("timestamp_s must be non-negative")
    if yellow_duration_seconds < 0 or red_yellow_duration_seconds < 0:
        raise ValueError("transition durations must be non-negative")

    model = build_signal_model(
        result,
        activity_threshold=activity_threshold,
    )
    segments = model["segments"]
    if not segments:
        raise ValueError("V9 result has no baseline segments")

    recording_segment = _find_segment(segments, timestamp_s)
    if recording_segment is None:
        raise ValueError("timestamp is outside the available baseline")

    start, end, phase_id = recording_segment
    segment_index = next(
        index
        for index, row in enumerate(segments)
        if (
            abs(float(row[0]) - start) < 1e-9
            and abs(float(row[1]) - end) < 1e-9
            and int(row[2]) == phase_id
        )
    )
    previous_phase = _adjacent_phase(segments, segment_index, -1)
    next_phase = _adjacent_phase(segments, segment_index, +1)
    distance_from_start = max(0.0, timestamp_s - start)
    distance_to_end = max(0.0, end - timestamp_s)

    streams: list[dict[str, Any]] = []
    for movement in model["activity"]:
        probabilities = model["activity"][movement]
        probability = float(probabilities.get(phase_id, 0.0))
        current_green = probability >= activity_threshold
        previous_green = (
            float(probabilities.get(previous_phase, 0.0)) >= activity_threshold
            if previous_phase is not None
            else False
        )
        next_green = (
            float(probabilities.get(next_phase, 0.0)) >= activity_threshold
            if next_phase is not None
            else False
        )

        state = "GREEN" if current_green else "RED"
        source = "INFERRED_MODEL"
        transition = None

        if (
            current_green
            and not next_green
            and 0.0 < distance_to_end <= yellow_duration_seconds
        ):
            state = "YELLOW"
            source = "MODELLED_TRANSITION"
            transition = {
                "from_state": "GREEN",
                "to_state": "RED",
                "duration_seconds": float(yellow_duration_seconds),
            }
        elif (
            current_green
            and not previous_green
            and 0.0 <= distance_from_start < red_yellow_duration_seconds
            and red_yellow_duration_seconds > 0
        ):
            state = "RED_YELLOW"
            source = "MODELLED_TRANSITION"
            transition = {
                "from_state": "RED",
                "to_state": "GREEN",
                "duration_seconds": float(red_yellow_duration_seconds),
            }

        approach = movement.split("->", 1)[0].strip()
        streams.append(
            {
                "movement": movement,
                "approach": approach,
                "state": state,
                "probability": round(probability, 4),
                "confidence": round(min(1.0, probability), 4),
                "source": source,
                "transition": transition,
            }
        )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in streams:
        grouped[item["approach"]].append(item)

    return {
        "timestamp_s": round(float(timestamp_s), 3),
        "cycle_position_s": round(float(timestamp_s % model["period_s"]), 3),
        "phase_id": phase_id,
        "phase_name": _phase_name(phase_id),
        "transition": any(item["transition"] is not None for item in streams),
        "approaches": {
            approach: sorted(items, key=lambda item: item["movement"])
            for approach, items in sorted(grouped.items())
        },
        "streams": streams,
        "semantics": {
            "green_red": "inferred from V9 per-stream phase activity",
            "yellow": "modelled transition before an active stream turns red",
            "red_yellow": "modelled transition before an inactive stream turns green",
        },
    }


__all__ = [
    "DEFAULT_ACTIVITY_THRESHOLD",
    "DEFAULT_RED_YELLOW_DURATION_SECONDS",
    "DEFAULT_YELLOW_DURATION_SECONDS",
    "build_signal_model",
    "signal_state_at",
]
