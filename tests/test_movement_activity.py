from app.core.models import Detection, EventType, Trajectory, TrajectoryEvent
from scripts.build_movement_activity import build_movement_activity


def test_build_movement_activity_keeps_movement_evidence_separate_from_signal_state():
    trajectory = Trajectory(
        vehicle_id=1,
        timestamp_ms=1000,
        zone_in="N",
        zone_out="E",
        movement="N->E",
        speed=20.0,
        wait_s=0.0,
        move_s=2.0,
        distance=10.0,
        detections=(
            Detection(1000, 55.0, 61.0, "N"),
            Detection(1800, 55.0, 61.0, "N"),
            Detection(2400, 55.0, 61.0, "E"),
        ),
    )
    event = TrajectoryEvent(
        event_type=EventType.RELEASE,
        timestamp_ms=2200,
        approach="N",
        movement="N->E",
        confidence=0.9,
        quality="valid",
    )

    result = build_movement_activity([trajectory], [event])

    assert result["movements"] == ["N->E"]
    rows = result["rows"]
    assert rows[0]["movement"] == "N->E"
    assert rows[0]["active_tracks"] == 1
    assert rows[1]["release_count"] == 1
    assert "GREEN" not in result["meaning"]
