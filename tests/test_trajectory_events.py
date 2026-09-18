from __future__ import annotations

from app.core.models import EventType, Trajectory
from app.core.trajectory_events import extract_trajectory_events
from app.core.trajectory_geometry import build_trajectory_geometry


def _trajectory(detections):
    geometry = build_trajectory_geometry({"detections": detections})
    return Trajectory(
        vehicle_id=1,
        timestamp_ms=geometry.detections[-1].millis if geometry.detections else 0,
        zone_in="N",
        zone_out="_S",
        movement="N->_S",
        speed=None,
        wait_s=0.0,
        move_s=0.0,
        distance=None,
        detections=geometry.detections,
    )


def _point(millis, lat, lng=61.0):
    return {"millis": millis, "lat": lat, "lng": lng}


def _event_types(events):
    return [event.event_type for event in events]


def test_extracts_approach_stop_release_and_crossing():
    detections = [
        _point(0, 55.00000), _point(1000, 55.00002),
        _point(2000, 55.00004), _point(3000, 55.00006),
        _point(4000, 55.00008), _point(5000, 55.00008),
        _point(6000, 55.00008), _point(7000, 55.00008),
        _point(8000, 55.00008), _point(9000, 55.00008),
        _point(10000, 55.00011), _point(11000, 55.00014),
        _point(12000, 55.00017), _point(13000, 55.00020),
    ]
    geometry = build_trajectory_geometry({"detections": detections})
    events = extract_trajectory_events(_trajectory(detections), geometry)
    assert _event_types(events) == [
        EventType.APPROACH, EventType.STOP, EventType.RELEASE, EventType.CROSSING
    ]
    assert events[0].timestamp_ms == 0
    assert 3500 <= events[1].timestamp_ms <= 4500
    assert 8500 <= events[2].timestamp_ms <= 10000
    assert events[-1].timestamp_ms == 13000


def test_trajectory_without_stop_has_no_release():
    detections = [_point(i * 1000, 55.0 + i * 0.00003) for i in range(10)]
    geometry = build_trajectory_geometry({"detections": detections})
    events = extract_trajectory_events(_trajectory(detections), geometry)
    assert EventType.APPROACH in _event_types(events)
    assert EventType.CROSSING in _event_types(events)
    assert EventType.STOP not in _event_types(events)
    assert EventType.RELEASE not in _event_types(events)


def test_missing_detections_return_no_events():
    trajectory = Trajectory(1, 1000, "N", "_S", "N->_S", None, 0.0, 0.0, None, ())
    assert extract_trajectory_events(trajectory, build_trajectory_geometry({})) == []


def test_irregular_timestamps_lower_quality():
    detections = [
        _point(0, 55.0), _point(500, 55.00003),
        _point(4000, 55.00006), _point(4500, 55.00009),
    ]
    geometry = build_trajectory_geometry({"detections": detections})
    events = extract_trajectory_events(_trajectory(detections), geometry)
    assert events and events[0].confidence < 1.0


def test_repeated_points_do_not_break_extraction():
    detections = [
        _point(0, 55.0), _point(1000, 55.0), _point(2000, 55.0),
        _point(3000, 55.0), _point(4000, 55.00003), _point(5000, 55.00006),
    ]
    geometry = build_trajectory_geometry({"detections": detections})
    events = extract_trajectory_events(_trajectory(detections), geometry)
    assert events and events[-1].event_type == EventType.CROSSING


def test_coordinate_noise_does_not_raise():
    detections = [
        _point(0, 55.0), _point(1000, 55.00003), _point(2000, 55.00001),
        _point(3000, 55.00004), _point(4000, 55.00002), _point(5000, 55.00005),
    ]
    geometry = build_trajectory_geometry({"detections": detections})
    events = extract_trajectory_events(_trajectory(detections), geometry)
    assert events and events[0].approach == "N" and events[0].movement == "N->_S"


def test_invalid_detections_lower_confidence_without_crash():
    detections = [
        _point(0, 55.0),
        {"millis": 1000, "lat": 91.0, "lng": 61.0},
        {"millis": 2000, "lat": None, "lng": 61.0},
        _point(3000, 55.00003),
    ]
    geometry = build_trajectory_geometry({"detections": detections})
    events = extract_trajectory_events(_trajectory(detections), geometry)
    assert geometry.invalid_detection_count == 2
    assert events and all(event.confidence < 1.0 for event in events)


def test_crossing_uses_last_detection_without_stop_line_geometry():
    detections = [_point(1000, 55.0), _point(2000, 55.00003), _point(3000, 55.00006)]
    geometry = build_trajectory_geometry({"detections": detections})
    events = extract_trajectory_events(_trajectory(detections), geometry)
    crossing = next(event for event in events if event.event_type == EventType.CROSSING)
    assert crossing.timestamp_ms == 3000
