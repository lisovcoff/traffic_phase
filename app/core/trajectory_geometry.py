from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping

EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class Detection:
    millis: int
    lat: float
    lng: float


@dataclass(frozen=True)
class TrajectoryGeometry:
    detections: tuple[Detection, ...]
    invalid_detection_count: int = 0

    @property
    def duration_s(self) -> float | None:
        if len(self.detections) < 2:
            return None
        return (self.detections[-1].millis - self.detections[0].millis) / 1000.0

    @property
    def total_distance_m(self) -> float:
        return sum(
            haversine_distance_m(first, second)
            for first, second in zip(self.detections, self.detections[1:])
        )


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _parse_detection(item: Any) -> Detection | None:
    if not isinstance(item, Mapping):
        return None

    millis = item.get("millis")
    lat = item.get("lat")
    lng = item.get("lng")

    if not _finite_number(millis) or float(millis) != int(float(millis)):
        return None
    if not _finite_number(lat) or not -90.0 <= float(lat) <= 90.0:
        return None
    if not _finite_number(lng) or not -180.0 <= float(lng) <= 180.0:
        return None

    return Detection(
        millis=int(millis),
        lat=float(lat),
        lng=float(lng),
    )


def build_trajectory_geometry(trajectory: Mapping[str, Any]) -> TrajectoryGeometry:
    raw_detections = trajectory.get("detections")
    if not isinstance(raw_detections, list):
        return TrajectoryGeometry(())

    valid: list[Detection] = []
    invalid = 0
    for item in raw_detections:
        detection = _parse_detection(item)
        if detection is None:
            invalid += 1
            continue
        valid.append(detection)

    valid.sort(key=lambda detection: detection.millis)
    return TrajectoryGeometry(tuple(valid), invalid_detection_count=invalid)


def normalize_detections(
    detections: Iterable[Any] | None,
) -> TrajectoryGeometry:
    if detections is None:
        return TrajectoryGeometry(())

    valid: list[Detection] = []
    invalid = 0
    for item in detections:
        detection = _parse_detection(item)
        if detection is None:
            invalid += 1
            continue
        valid.append(detection)

    valid.sort(key=lambda detection: detection.millis)
    return TrajectoryGeometry(tuple(valid), invalid_detection_count=invalid)


def haversine_distance_m(first: Detection, second: Detection) -> float:
    lat1 = math.radians(first.lat)
    lat2 = math.radians(second.lat)
    delta_lat = lat2 - lat1
    delta_lng = math.radians(second.lng - first.lng)

    a = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, a)))
