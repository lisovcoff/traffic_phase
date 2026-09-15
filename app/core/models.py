from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


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

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


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
