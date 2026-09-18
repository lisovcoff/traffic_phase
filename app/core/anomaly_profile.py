from __future__ import annotations

from dataclasses import asdict, dataclass
import statistics
from typing import Iterable

from app.core.models import EventType, TrajectoryEvent

APPROACHES = ("N", "S", "E", "W")
GROUPS = {"NS": ("N", "S"), "EW": ("E", "W")}


def _median(values: list[float], default: float = 0.0) -> float:
    return float(statistics.median(values)) if values else default


def _mad(values: list[float], center: float, default: float = 1.0) -> float:
    if not values:
        return default
    value = float(statistics.median(abs(item - center) for item in values))
    return value if value > 1e-9 else default


@dataclass(frozen=True)
class TrafficBaselineProfile:
    window_seconds: float
    approach_flow_median: dict[str, float]
    approach_flow_mad: dict[str, float]
    approach_stop_rate_median: dict[str, float]
    approach_stop_rate_mad: dict[str, float]
    group_flow_median: dict[str, float]
    group_flow_mad: dict[str, float]
    group_release_median: dict[str, float]
    group_release_mad: dict[str, float]
    group_share_median: dict[str, float]
    group_share_mad: dict[str, float]
    total_flow_median: float
    total_flow_mad: float
    baseline_windows: int
    source: str = "reference"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_events(
        cls,
        events: Iterable[TrajectoryEvent],
        *,
        window_seconds: float = 12.0,
        source: str = "reference",
    ) -> "TrafficBaselineProfile":
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        selected = [event for event in events if event.approach in APPROACHES]
        if not selected:
            raise ValueError("no usable events for baseline profile")

        start_ms = min(event.timestamp_ms for event in selected)
        end_ms = max(event.timestamp_ms for event in selected)
        window_count = max(
            1,
            int((end_ms - start_ms) / 1000.0 / window_seconds) + 1,
        )
        flow = {a: [0.0] * window_count for a in APPROACHES}
        stops = {a: [0.0] * window_count for a in APPROACHES}
        releases = {a: [0.0] * window_count for a in APPROACHES}

        for event in selected:
            index = min(
                window_count - 1,
                max(
                    0,
                    int((event.timestamp_ms - start_ms) / 1000.0 / window_seconds),
                ),
            )
            if event.event_type == EventType.APPROACH:
                flow[event.approach][index] += 1.0
            elif event.event_type == EventType.STOP:
                stops[event.approach][index] += 1.0
            elif event.event_type in {EventType.RELEASE, EventType.CROSSING}:
                releases[event.approach][index] += (
                    1.0 if event.event_type == EventType.RELEASE else 0.5
                )

        approach_flow_median = {}
        approach_flow_mad = {}
        approach_stop_rate_median = {}
        approach_stop_rate_mad = {}
        for approach in APPROACHES:
            values = flow[approach]
            center = _median(values)
            stop_rates = [
                stops[approach][i] / values[i] if values[i] else 0.0
                for i in range(window_count)
            ]
            stop_center = _median(stop_rates)
            approach_flow_median[approach] = round(center, 6)
            approach_flow_mad[approach] = round(_mad(values, center), 6)
            approach_stop_rate_median[approach] = round(stop_center, 6)
            approach_stop_rate_mad[approach] = round(_mad(stop_rates, stop_center), 6)

        group_flow_median = {}
        group_flow_mad = {}
        group_release_median = {}
        group_release_mad = {}
        group_share_median = {}
        group_share_mad = {}
        for group, approaches in GROUPS.items():
            group_flows = [
                sum(flow[a][i] for a in approaches)
                for i in range(window_count)
            ]
            group_releases = [
                sum(releases[a][i] for a in approaches)
                for i in range(window_count)
            ]
            shares = []
            for i in range(window_count):
                total = sum(flow[a][i] for a in APPROACHES)
                shares.append(
                    sum(flow[a][i] for a in approaches) / total
                    if total else 0.0
                )
            flow_center = _median(group_flows)
            release_center = _median(group_releases)
            share_center = _median(shares)
            group_flow_median[group] = round(flow_center, 6)
            group_flow_mad[group] = round(_mad(group_flows, flow_center), 6)
            group_release_median[group] = round(release_center, 6)
            group_release_mad[group] = round(_mad(group_releases, release_center), 6)
            group_share_median[group] = round(share_center, 6)
            group_share_mad[group] = round(_mad(shares, share_center), 6)

        total_flows = [
            sum(flow[a][i] for a in APPROACHES)
            for i in range(window_count)
        ]
        total_center = _median(total_flows)
        return cls(
            window_seconds=float(window_seconds),
            approach_flow_median=approach_flow_median,
            approach_flow_mad=approach_flow_mad,
            approach_stop_rate_median=approach_stop_rate_median,
            approach_stop_rate_mad=approach_stop_rate_mad,
            group_flow_median=group_flow_median,
            group_flow_mad=group_flow_mad,
            group_release_median=group_release_median,
            group_release_mad=group_release_mad,
            group_share_median=group_share_median,
            group_share_mad=group_share_mad,
            total_flow_median=round(total_center, 6),
            total_flow_mad=round(_mad(total_flows, total_center), 6),
            baseline_windows=window_count,
            source=source,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "TrafficBaselineProfile":
        return cls(
            window_seconds=float(payload["window_seconds"]),
            approach_flow_median={k: float(v) for k, v in payload["approach_flow_median"].items()},
            approach_flow_mad={k: float(v) for k, v in payload["approach_flow_mad"].items()},
            approach_stop_rate_median={k: float(v) for k, v in payload["approach_stop_rate_median"].items()},
            approach_stop_rate_mad={k: float(v) for k, v in payload["approach_stop_rate_mad"].items()},
            group_flow_median={k: float(v) for k, v in payload["group_flow_median"].items()},
            group_flow_mad={k: float(v) for k, v in payload["group_flow_mad"].items()},
            group_release_median={k: float(v) for k, v in payload["group_release_median"].items()},
            group_release_mad={k: float(v) for k, v in payload["group_release_mad"].items()},
            group_share_median={k: float(v) for k, v in payload["group_share_median"].items()},
            group_share_mad={k: float(v) for k, v in payload["group_share_mad"].items()},
            total_flow_median=float(payload["total_flow_median"]),
            total_flow_mad=float(payload["total_flow_mad"]),
            baseline_windows=int(payload["baseline_windows"]),
            source=str(payload.get("source", "reference")),
        )


def robust_deviation(value: float, center: float, mad: float, *, scale: float = 3.0) -> float:
    return max(0.0, min(1.0, abs(value - center) / max(mad, 1e-6) / scale))
