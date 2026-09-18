from __future__ import annotations

from app.core.anomaly_profile import TrafficBaselineProfile
from app.core.models import EventType, TrajectoryEvent


def baseline():
    events = []
    for t in range(0, 120, 2):
        for approach in ("N", "S", "E", "W"):
            events.append(
                TrajectoryEvent(
                    EventType.APPROACH,
                    t * 1000,
                    approach,
                    f"{approach}->x",
                    1.0,
                    "HIGH",
                )
            )
            events.append(
                TrajectoryEvent(
                    EventType.RELEASE,
                    (t + 0.2) * 1000,
                    approach,
                    f"{approach}->x",
                    1.0,
                    "HIGH",
                )
            )
    return TrafficBaselineProfile.from_events(events, window_seconds=12.0)


def test_reference_baseline_profiles_can_be_aggregated():
    first = baseline()
    second = TrafficBaselineProfile.from_dict(first.to_dict() | {"source": "second"})
    aggregate = TrafficBaselineProfile.aggregate([first, second])
    assert aggregate.source == "reference_pool"
    assert aggregate.total_flow_median == first.total_flow_median
    assert aggregate.baseline_windows == first.baseline_windows * 2
