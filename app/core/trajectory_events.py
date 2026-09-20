from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from app.core.models import EventType, Trajectory, TrajectoryEvent
from app.core.trajectory_geometry import TrajectoryGeometry, haversine_distance_m


@dataclass(frozen=True)
class EventExtractionConfig:
    stop_speed_mps: float = 0.8
    stop_min_duration_s: float = 3.0
    release_speed_mps: float = 2.0
    release_min_duration_s: float = 1.0
    max_detection_gap_s: float = 2.0
    min_detections: int = 2
    smoothing_window: int = 3


class StopLineProvider(Protocol):
    """Optional configured geometry hook for future explicit stop-line crossing."""

    def crossing_timestamp_ms(
        self, detections: Sequence
    ) -> int | None: ...


@dataclass(frozen=True)
class IntersectionGeometry:
    stop_line_provider: StopLineProvider | None = None


def _segment_speeds(detections):
    speeds = []
    for first, second in zip(detections, detections[1:]):
        dt_s = (second.millis - first.millis) / 1000.0
        if dt_s <= 0:
            continue
        speeds.append(
            (second.millis, haversine_distance_m(first, second) / dt_s, dt_s)
        )
    return speeds


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _smooth_speeds(speeds, window: int):
    if window <= 1 or len(speeds) < 2:
        return speeds

    half = window // 2
    values = [item[1] for item in speeds]
    return [
        (
            item[0],
            _median(
                values[
                    max(0, index - half): min(len(values), index + half + 1)
                ]
            ),
            item[2],
        )
        for index, item in enumerate(speeds)
    ]


def _first_sustained(speeds, predicate, duration_s: float) -> int | None:
    start_ms = None
    last_ms = None

    for timestamp_ms, speed_mps, dt_s in speeds:
        if predicate(speed_mps):
            if start_ms is None:
                start_ms = int(timestamp_ms - dt_s * 1000.0)
            last_ms = timestamp_ms
            if (last_ms - start_ms) / 1000.0 >= duration_s:
                return start_ms
        else:
            start_ms = None
            last_ms = None

    return None


def _trajectory_quality(
    geometry: TrajectoryGeometry,
    config: EventExtractionConfig,
) -> tuple[float, str]:
    detections = geometry.detections
    if len(detections) < config.min_detections:
        return 0.25, "LOW"

    gaps = [
        (second.millis - first.millis) / 1000.0
        for first, second in zip(detections, detections[1:])
        if second.millis > first.millis
    ]
    if not gaps:
        return 0.25, "LOW"

    gap_ratio = sum(gap > config.max_detection_gap_s for gap in gaps) / len(gaps)
    invalid_ratio = geometry.invalid_detection_count / max(
        1, len(detections) + geometry.invalid_detection_count
    )
    confidence = max(0.0, 1.0 - 0.7 * gap_ratio - 0.3 * invalid_ratio)

    quality = (
        "HIGH"
        if confidence >= 0.85
        else "MEDIUM"
        if confidence >= 0.60
        else "LOW"
    )
    return confidence, quality


def _event_confidence(base: float, strength: float) -> float:
    return round(max(0.0, min(1.0, base * strength)), 4)


def _zone_crossing_timestamp(
    detections,
    *,
    zone_in: str,
    zone_out: str,
) -> tuple[int | None, bool]:
    """Return an observed entry into the intersection from detection zones.

    The transition is usable only after the incoming zone has actually been
    observed.  A following unzoned detection represents the intersection
    interior in the supplied data; a direct transition to the configured
    outgoing zone is also accepted.  The boolean reports whether any named
    detection-zone information exists, so an incomplete zoned trajectory is
    not silently replaced with the end-of-track fallback.
    """
    seen_incoming = False
    has_named_zone = False

    for detection in detections:
        zone = getattr(detection, "zone", None)
        if zone is not None:
            has_named_zone = True

        if zone == zone_in:
            seen_incoming = True
            continue

        if seen_incoming and (zone is None or zone == zone_out):
            return int(detection.millis), True

    return None, has_named_zone


def extract_trajectory_events(
    trajectory: Trajectory,
    geometry: TrajectoryGeometry,
    *,
    intersection: IntersectionGeometry | None = None,
    config: EventExtractionConfig = EventExtractionConfig(),
) -> list[TrajectoryEvent]:
    detections = geometry.detections
    if not detections:
        return []

    base_confidence, quality = _trajectory_quality(geometry, config)
    approach = trajectory.zone_in
    movement = trajectory.movement

    events = [
        TrajectoryEvent(
            event_type=EventType.APPROACH,
            timestamp_ms=detections[0].millis,
            approach=approach,
            movement=movement,
            confidence=_event_confidence(base_confidence, 1.0),
            quality=quality,
        )
    ]

    speeds = _smooth_speeds(
        _segment_speeds(detections),
        config.smoothing_window,
    )

    stop_timestamp = _first_sustained(
        speeds,
        lambda speed: speed <= config.stop_speed_mps,
        config.stop_min_duration_s,
    )

    if stop_timestamp is not None:
        events.append(
            TrajectoryEvent(
                event_type=EventType.STOP,
                timestamp_ms=stop_timestamp,
                approach=approach,
                movement=movement,
                confidence=_event_confidence(base_confidence, 0.9),
                quality=quality,
            )
        )

        release_candidates = [
            item
            for item in speeds
            if item[0] >= stop_timestamp + config.stop_min_duration_s * 1000
        ]
        release_timestamp = _first_sustained(
            release_candidates,
            lambda speed: speed >= config.release_speed_mps,
            config.release_min_duration_s,
        )

        if release_timestamp is not None:
            events.append(
                TrajectoryEvent(
                    event_type=EventType.RELEASE,
                    timestamp_ms=release_timestamp,
                    approach=approach,
                    movement=movement,
                    confidence=_event_confidence(base_confidence, 0.9),
                    quality=quality,
                )
            )

    crossing_timestamp = None
    crossing_strength = 0.0
    stop_line_provider = (
        intersection.stop_line_provider
        if intersection is not None
        else None
    )

    if stop_line_provider is not None:
        crossing_timestamp = stop_line_provider.crossing_timestamp_ms(detections)
        crossing_strength = 1.0 if len(detections) >= 5 else 0.6
    else:
        crossing_timestamp, zone_data_present = _zone_crossing_timestamp(
            detections,
            zone_in=trajectory.zone_in,
            zone_out=trajectory.zone_out,
        )
        if crossing_timestamp is not None:
            crossing_strength = 1.0 if len(detections) >= 5 else 0.6
        elif not zone_data_present:
            # With no detection-zone information, the track end is only a
            # weak proxy for intersection entry.  Keep it for compatibility,
            # but ensure it cannot look as reliable as an observed crossing.
            crossing_timestamp = detections[-1].millis
            crossing_strength = 0.35 if len(detections) >= 5 else 0.2

    if crossing_timestamp is not None and crossing_timestamp >= detections[0].millis:
        events.append(
            TrajectoryEvent(
                event_type=EventType.CROSSING,
                timestamp_ms=int(crossing_timestamp),
                approach=approach,
                movement=movement,
                confidence=_event_confidence(
                    base_confidence,
                    crossing_strength,
                ),
                quality=quality,
            )
        )

    return events
