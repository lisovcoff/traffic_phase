from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping

from app.core.models import Detection

EARTH_RADIUS_M = 6_371_000.0


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
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


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

    zone = item.get("zone")
    if zone is not None:
        zone = str(zone)

    return Detection(
        millis=int(millis),
        lat=float(lat),
        lng=float(lng),
        zone=zone,
    )


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


def build_trajectory_geometry(
    trajectory: Mapping[str, Any],
) -> TrajectoryGeometry:
    return normalize_detections(trajectory.get("detections"))


def build_trajectory_model(trajectory: Mapping[str, Any]):
    from app.core.models import Trajectory

    geometry = build_trajectory_geometry(trajectory)
    if trajectory.get("millis") is None:
        raise ValueError("Trajectory millis is required")

    zone_in = trajectory.get("zone_in")
    zone_out = trajectory.get("zone_out")
    if not zone_in or not zone_out:
        raise ValueError("Trajectory zones are required")

    return Trajectory(
        vehicle_id=trajectory.get("id"),
        timestamp_ms=int(trajectory["millis"]),
        zone_in=str(zone_in),
        zone_out=str(zone_out),
        movement=f"{zone_in}->{zone_out}",
        speed=float(trajectory["speed"]) if trajectory.get("speed") is not None else None,
        wait_s=max(
            0.0,
            float(trajectory.get("stay_duration_millis") or 0) / 1000.0,
        ),
        move_s=max(
            0.0,
            float(trajectory.get("move_duration_millis") or 0) / 1000.0,
        ),
        distance=(
            float(trajectory["distance"])
            if trajectory.get("distance") is not None
            else None
        ),
        detections=geometry.detections,
    )


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
