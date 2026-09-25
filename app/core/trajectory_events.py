from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Protocol, Sequence

from app.core.models import (
    Detection,
    EventType,
    MovementEvidenceQuality,
    Trajectory,
    TrajectoryEvent,
)
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


UNKNOWN_DESTINATION = "UNKNOWN"


def resolve_movement(
    approach: str,
    zone_out: str | None,
    movement: str | None,
) -> tuple[str, MovementEvidenceQuality, str | None]:
    """Canonicalize and validate a trajectory movement."""
    normalized_approach = str(approach).strip()
    if not normalized_approach:
        raise ValueError("movement approach must not be empty")

    normalized_zone_out = (
        str(zone_out).strip()
        if zone_out is not None
        else UNKNOWN_DESTINATION
    )
    destination_known = bool(
        normalized_zone_out
        and normalized_zone_out != UNKNOWN_DESTINATION
    )

    raw_movement = (
        str(movement).strip()
        if movement is not None
        else ""
    )

    if not raw_movement:
        if destination_known:
            return (
                f"{normalized_approach}->{normalized_zone_out}",
                MovementEvidenceQuality.VALID,
                None,
            )
        return (
            f"{normalized_approach}->{UNKNOWN_DESTINATION}",
            MovementEvidenceQuality.UNKNOWN,
            "destination_not_observed",
        )

    parts = raw_movement.split("->")
    if len(parts) != 2:
        raise ValueError(
            "movement must use '<approach>-><destination>' format"
        )

    movement_approach = parts[0].strip()
    movement_destination = parts[1].strip()
    if not movement_approach or not movement_destination:
        raise ValueError("movement approach and destination must not be empty")

    if movement_approach != normalized_approach:
        raise ValueError(
            "movement approach does not match zone_in: "
            f"{movement_approach!r} != {normalized_approach!r}"
        )

    if destination_known:
        if movement_destination != normalized_zone_out:
            raise ValueError(
                "movement destination does not match zone_out: "
                f"{movement_destination!r} != {normalized_zone_out!r}"
            )
        return (
            f"{normalized_approach}->{movement_destination}",
            MovementEvidenceQuality.VALID,
            None,
        )

    if movement_destination == UNKNOWN_DESTINATION:
        return (
            f"{normalized_approach}->{UNKNOWN_DESTINATION}",
            MovementEvidenceQuality.UNKNOWN,
            "destination_not_observed",
        )

    return (
        f"{normalized_approach}->{movement_destination}",
        MovementEvidenceQuality.WEAK,
        "destination_inferred_from_movement",
    )

class CausalTrajectoryEventExtractor:
    """Incrementally confirm trajectory events without reading future detections.

    Repeated partial snapshots are supported: duplicate detections are ignored
    and each event type is emitted at most once. Speed smoothing is trailing,
    so STOP/RELEASE confirmation uses only segments already observed.
    """

    def __init__(
        self,
        *,
        approach: str,
        movement: str | None,
        zone_out: str | None,
        config: EventExtractionConfig = EventExtractionConfig(),
    ) -> None:
        (
            canonical_movement,
            movement_quality,
            movement_reason,
        ) = resolve_movement(
            approach,
            zone_out,
            movement,
        )
        self.approach = str(approach).strip()
        self.movement = canonical_movement
        self.movement_quality = movement_quality
        self.movement_reason = movement_reason
        self.zone_out = (
            str(zone_out).strip()
            if zone_out is not None
            else UNKNOWN_DESTINATION
        )
        self.config = config
        self._detections: list[Detection] = []
        self._seen_detections: set[tuple[int, float, float, str | None]] = set()
        self._raw_speeds: list[tuple[int, float, float]] = []
        self._emitted: set[EventType] = set()
        self._stop_run_start_ms: int | None = None
        self._release_run_start_ms: int | None = None
        self._stop_timestamp_ms: int | None = None
        self._seen_incoming = False
        self._has_named_zone = False

    @property
    def observed_detection_count(self) -> int:
        return len(self._detections)

    @property
    def latest_detection_ms(self) -> int | None:
        if not self._detections:
            return None
        return self._detections[-1].millis

    def ingest_snapshot(
        self,
        detections: Sequence[Detection],
        *,
        final: bool = False,
    ) -> list[TrajectoryEvent]:
        events: list[TrajectoryEvent] = []
        for detection in sorted(detections, key=lambda item: item.millis):
            events.extend(self.ingest_detection(detection))
        if final:
            events.extend(self.finalize())
        return events

    def ingest_detection(
        self,
        detection: Detection,
    ) -> list[TrajectoryEvent]:
        key = (
            int(detection.millis),
            float(detection.lat),
            float(detection.lng),
            detection.zone,
        )
        if key in self._seen_detections:
            return []

        self._seen_detections.add(key)
        insert_at = bisect_right(
            [item.millis for item in self._detections],
            detection.millis,
        )
        if insert_at < len(self._detections):
            self._detections.insert(insert_at, detection)
            return self._rebuild_after_late_arrival()

        previous = self._detections[-1] if self._detections else None
        self._detections.append(detection)
        return self._process_detection(
            detection,
            previous,
        )

    def _process_detection(
        self,
        detection: Detection,
        previous: Detection | None,
    ) -> list[TrajectoryEvent]:
        events: list[TrajectoryEvent] = []

        if EventType.APPROACH not in self._emitted:
            events.append(
                self._emit(
                    EventType.APPROACH,
                    self._detections[0].millis,
                    strength=1.0,
                )
            )

        if previous is not None:
            dt_s = (detection.millis - previous.millis) / 1000.0
            if dt_s > 0:
                speed_mps = haversine_distance_m(
                    previous,
                    detection,
                ) / dt_s
                self._raw_speeds.append(
                    (detection.millis, speed_mps, dt_s)
                )
                smoothed_speed = _median(
                    [
                        item[1]
                        for item in self._raw_speeds[
                            -max(1, self.config.smoothing_window):
                        ]
                    ]
                )
                events.extend(
                    self._update_motion_state(
                        timestamp_ms=detection.millis,
                        segment_start_ms=previous.millis,
                        speed_mps=smoothed_speed,
                    )
                )

        events.extend(self._update_crossing(detection))
        return events

    def _rebuild_after_late_arrival(self) -> list[TrajectoryEvent]:
        previously_emitted = set(self._emitted)
        self._detections.sort(
            key=lambda item: (
                item.millis,
                item.lat,
                item.lng,
                item.zone or "",
            )
        )
        self._emitted.clear()
        self._raw_speeds.clear()
        self._stop_run_start_ms = None
        self._release_run_start_ms = None
        self._stop_timestamp_ms = None
        self._seen_incoming = False
        self._has_named_zone = False

        rebuilt: list[TrajectoryEvent] = []
        previous = None
        for detection in self._detections:
            rebuilt.extend(
                self._process_detection(
                    detection,
                    previous,
                )
            )
            previous = detection

        return [
            event
            for event in rebuilt
            if event.event_type not in previously_emitted
        ]

    def finalize(self) -> list[TrajectoryEvent]:
        if (
            EventType.CROSSING in self._emitted
            or not self._detections
            or self._has_named_zone
        ):
            return []
        strength = 0.35 if len(self._detections) >= 5 else 0.2
        return [
            self._emit(
                EventType.CROSSING,
                self._detections[-1].millis,
                strength=strength,
            )
        ]

    def _update_motion_state(
        self,
        *,
        timestamp_ms: int,
        segment_start_ms: int,
        speed_mps: float,
    ) -> list[TrajectoryEvent]:
        events: list[TrajectoryEvent] = []

        if EventType.STOP not in self._emitted:
            if speed_mps <= self.config.stop_speed_mps:
                if self._stop_run_start_ms is None:
                    self._stop_run_start_ms = segment_start_ms
                if (
                    timestamp_ms - self._stop_run_start_ms
                    >= int(self.config.stop_min_duration_s * 1000.0)
                ):
                    self._stop_timestamp_ms = self._stop_run_start_ms
                    events.append(
                        self._emit(
                            EventType.STOP,
                            self._stop_timestamp_ms,
                            strength=0.9,
                        )
                    )
            else:
                self._stop_run_start_ms = None
            return events

        if (
            EventType.RELEASE in self._emitted
            or self._stop_timestamp_ms is None
        ):
            return events

        release_not_before_ms = (
            self._stop_timestamp_ms
            + int(self.config.stop_min_duration_s * 1000.0)
        )
        if timestamp_ms < release_not_before_ms:
            return events

        if speed_mps >= self.config.release_speed_mps:
            candidate_start_ms = max(
                segment_start_ms,
                release_not_before_ms,
            )
            if self._release_run_start_ms is None:
                self._release_run_start_ms = candidate_start_ms
            if (
                timestamp_ms - self._release_run_start_ms
                >= int(self.config.release_min_duration_s * 1000.0)
            ):
                events.append(
                    self._emit(
                        EventType.RELEASE,
                        self._release_run_start_ms,
                        strength=0.9,
                    )
                )
        else:
            self._release_run_start_ms = None
        return events

    def _update_crossing(
        self,
        detection: Detection,
    ) -> list[TrajectoryEvent]:
        if EventType.CROSSING in self._emitted:
            return []

        zone = detection.zone
        if zone is not None:
            self._has_named_zone = True
        if zone == self.approach:
            self._seen_incoming = True
            return []
        if not self._seen_incoming:
            return []
        if zone is None or zone == self.zone_out:
            strength = 1.0 if len(self._detections) >= 5 else 0.6
            return [
                self._emit(
                    EventType.CROSSING,
                    detection.millis,
                    strength=strength,
                )
            ]
        return []

    def _emit(
        self,
        event_type: EventType,
        timestamp_ms: int,
        *,
        strength: float,
    ) -> TrajectoryEvent:
        confidence, quality = _trajectory_quality(
            TrajectoryGeometry(tuple(self._detections)),
            self.config,
        )
        self._emitted.add(event_type)
        return TrajectoryEvent(
            event_type=event_type,
            timestamp_ms=int(timestamp_ms),
            approach=self.approach,
            movement=self.movement,
            confidence=_event_confidence(confidence, strength),
            quality=quality,
            movement_quality=self.movement_quality,
            movement_reason=self.movement_reason,
        )


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
    movement, movement_quality, movement_reason = resolve_movement(
        trajectory.zone_in,
        trajectory.zone_out,
        trajectory.movement,
    )

    events = [
        TrajectoryEvent(
            event_type=EventType.APPROACH,
            timestamp_ms=detections[0].millis,
            approach=approach,
            movement=movement,
            confidence=_event_confidence(base_confidence, 1.0),
            quality=quality,
            movement_quality=movement_quality,
            movement_reason=movement_reason,
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
                movement_quality=movement_quality,
                movement_reason=movement_reason,
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
                    movement_quality=movement_quality,
                    movement_reason=movement_reason,
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
                movement_quality=movement_quality,
                movement_reason=movement_reason,
            )
        )

    return events
