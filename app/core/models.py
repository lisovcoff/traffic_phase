from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class Detection:
    millis: int
    lat: float
    lng: float
    zone: str | None = None


@dataclass(frozen=True)
class Trajectory:
    vehicle_id: Any
    timestamp_ms: int
    zone_in: str
    zone_out: str
    movement: str
    speed: float | None
    wait_s: float
    move_s: float
    distance: float | None
    detections: tuple[Detection, ...] = ()

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


class EventType(str, Enum):
    APPROACH = "APPROACH"
    STOP = "STOP"
    RELEASE = "RELEASE"
    CROSSING = "CROSSING"


class MovementEvidenceQuality(str, Enum):
    VALID = "valid"
    WEAK = "weak"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TrajectoryEvent:
    event_type: EventType
    timestamp_ms: int
    approach: str
    movement: str
    confidence: float
    quality: str
    movement_quality: MovementEvidenceQuality = MovementEvidenceQuality.UNKNOWN
    movement_reason: str | None = None


@dataclass(frozen=True)
class TrafficWindow:
    start_s: float
    duration_s: float
    movement: str
    flow: int
    mean_speed: float | None
    mean_wait: float | None
    stopped_count: int
    release_weight: float
