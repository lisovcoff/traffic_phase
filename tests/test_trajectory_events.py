from __future__ import annotations

import pytest

from app.core.models import EventType, MovementEvidenceQuality, Trajectory
from app.core.trajectory_events import IntersectionGeometry, extract_trajectory_events
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


_MISSING = object()


def _point(millis, lat, lng=61.0, zone=_MISSING):
    point = {"millis": millis, "lat": lat, "lng": lng}
    if zone is not _MISSING:
        point["zone"] = zone
    return point


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
    assert all(event.movement == "N->_S" for event in events)
    assert all(
        event.movement_quality is MovementEvidenceQuality.VALID
        for event in events
    )


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


def test_crossing_uses_zone_exit_as_intersection_entry():
    detections = [
        _point(1000, 55.0, zone="N"),
        _point(2000, 55.00003, zone="N"),
        _point(3000, 55.00006, zone=None),
        _point(4000, 55.00009, zone=None),
        _point(5000, 55.00012, zone="_S"),
    ]
    geometry = build_trajectory_geometry({"detections": detections})
    events = extract_trajectory_events(_trajectory(detections), geometry)

    crossing = next(event for event in events if event.event_type == EventType.CROSSING)

    assert crossing.timestamp_ms == 3000
    assert crossing.confidence == 1.0


def test_crossing_falls_back_to_track_end_with_lower_confidence_without_zones():
    detections = [
        _point(1000, 55.0),
        _point(2000, 55.00003),
        _point(3000, 55.00006),
        _point(4000, 55.00009),
        _point(5000, 55.00012),
    ]
    geometry = build_trajectory_geometry({"detections": detections})
    events = extract_trajectory_events(_trajectory(detections), geometry)

    crossing = next(event for event in events if event.event_type == EventType.CROSSING)

    assert crossing.timestamp_ms == 5000
    assert crossing.confidence == 0.35


def test_incomplete_zoned_trajectory_does_not_invent_crossing():
    detections = [
        _point(1000, 55.00006, zone=None),
        _point(2000, 55.00009, zone=None),
        _point(3000, 55.00012, zone="_S"),
    ]
    geometry = build_trajectory_geometry({"detections": detections})
    events = extract_trajectory_events(_trajectory(detections), geometry)

    assert EventType.CROSSING not in _event_types(events)


def test_stop_line_provider_has_priority_over_detection_zones():
    class Provider:
        def crossing_timestamp_ms(self, detections):
            return 4500

    detections = [
        _point(1000, 55.0, zone="N"),
        _point(2000, 55.00003, zone="N"),
        _point(3000, 55.00006, zone=None),
        _point(4000, 55.00009, zone=None),
        _point(5000, 55.00012, zone="_S"),
    ]
    geometry = build_trajectory_geometry({"detections": detections})
    events = extract_trajectory_events(
        _trajectory(detections),
        geometry,
        intersection=IntersectionGeometry(stop_line_provider=Provider()),
    )

    crossing = next(event for event in events if event.event_type == EventType.CROSSING)

    assert crossing.timestamp_ms == 4500


def test_causal_extractor_confirms_stop_and_release_without_future_points():
    from app.core.trajectory_events import CausalTrajectoryEventExtractor

    extractor = CausalTrajectoryEventExtractor(
        approach="N",
        movement="N->_S",
        zone_out="_S",
    )
    points = [
        _point(0, 55.0, zone="N"),
        _point(1000, 55.0, zone="N"),
        _point(2000, 55.0, zone="N"),
        _point(3000, 55.0, zone="N"),
        _point(4000, 55.0, zone="N"),
        _point(5000, 55.00003, zone="N"),
        _point(6000, 55.00006, zone=None),
    ]
    geometry = build_trajectory_geometry({"detections": points})

    early = extractor.ingest_snapshot(geometry.detections[:4])
    assert EventType.APPROACH in _event_types(early)
    assert EventType.STOP in _event_types(early)
    assert EventType.RELEASE not in _event_types(early)

    before_release_confirmation = extractor.ingest_snapshot(
        geometry.detections[:6]
    )
    assert EventType.RELEASE not in _event_types(
        before_release_confirmation
    )

    confirmed = extractor.ingest_snapshot(geometry.detections)
    assert EventType.RELEASE in _event_types(confirmed)
    assert EventType.CROSSING in _event_types(confirmed)


def test_causal_extractor_repeated_snapshots_do_not_reemit_events():
    from app.core.trajectory_events import CausalTrajectoryEventExtractor

    extractor = CausalTrajectoryEventExtractor(
        approach="N",
        movement="N->_S",
        zone_out="_S",
    )
    geometry = build_trajectory_geometry(
        {
            "detections": [
                _point(0, 55.0, zone="N"),
                _point(1000, 55.00003, zone="N"),
                _point(2000, 55.00006, zone=None),
            ]
        }
    )

    first = extractor.ingest_snapshot(geometry.detections)
    repeated = extractor.ingest_snapshot(geometry.detections)

    assert EventType.APPROACH in _event_types(first)
    assert EventType.CROSSING in _event_types(first)
    assert repeated == []


def test_causal_extractor_does_not_use_future_crossing_detection():
    from app.core.trajectory_events import CausalTrajectoryEventExtractor

    extractor = CausalTrajectoryEventExtractor(
        approach="N",
        movement="N->_S",
        zone_out="_S",
    )
    geometry = build_trajectory_geometry(
        {
            "detections": [
                _point(0, 55.0, zone="N"),
                _point(1000, 55.00001, zone="N"),
                _point(10_000, 55.00010, zone=None),
            ]
        }
    )

    early = extractor.ingest_snapshot(geometry.detections[:2])
    assert EventType.CROSSING not in _event_types(early)

    later = extractor.ingest_snapshot(geometry.detections)
    assert EventType.CROSSING in _event_types(later)


def test_common_movements_are_canonical_and_valid():
    from app.core.trajectory_events import resolve_movement

    cases = [
        ("N", "_S"),
        ("N", "_E"),
        ("N", "_W"),
        ("S", "_N"),
        ("S", "_E"),
        ("E", "_W"),
        ("E", "_N"),
        ("W", "_E"),
        ("W", "_S"),
    ]
    for approach, destination in cases:
        movement, quality, reason = resolve_movement(
            approach,
            destination,
            f"{approach}->{destination}",
        )
        assert movement == f"{approach}->{destination}"
        assert quality is MovementEvidenceQuality.VALID
        assert reason is None


def test_unknown_destination_is_explicit_and_does_not_fake_a_route():
    from app.core.trajectory_events import resolve_movement

    movement, quality, reason = resolve_movement(
        "N",
        None,
        None,
    )
    assert movement == "N->UNKNOWN"
    assert quality is MovementEvidenceQuality.UNKNOWN
    assert reason == "destination_not_observed"


def test_known_movement_without_zone_out_is_weak_not_valid():
    from app.core.trajectory_events import resolve_movement

    movement, quality, reason = resolve_movement(
        "N",
        None,
        "N->_E",
    )
    assert movement == "N->_E"
    assert quality is MovementEvidenceQuality.WEAK
    assert reason == "destination_inferred_from_movement"


def test_malformed_movement_is_rejected():
    from app.core.trajectory_events import resolve_movement

    with pytest.raises(ValueError, match="does not match zone_in"):
        resolve_movement("N", "_S", "E->_S")

    with pytest.raises(ValueError, match="does not match zone_out"):
        resolve_movement("N", "_S", "N->_E")


def test_causal_extractor_marks_unknown_destination_without_inventing_one():
    from app.core.trajectory_events import (
        CausalTrajectoryEventExtractor,
        UNKNOWN_DESTINATION,
    )

    extractor = CausalTrajectoryEventExtractor(
        approach="N",
        movement=None,
        zone_out=UNKNOWN_DESTINATION,
    )
    geometry = build_trajectory_geometry(
        {
            "detections": [
                _point(0, 55.0, zone="N"),
                _point(1000, 55.00003, zone="N"),
                _point(2000, 55.00006, zone=None),
            ]
        }
    )
    events = extractor.ingest_snapshot(geometry.detections)
    crossing = next(
        event for event in events
        if event.event_type == EventType.CROSSING
    )
    assert crossing.movement == "N->UNKNOWN"
    assert crossing.movement_quality is MovementEvidenceQuality.UNKNOWN


def test_causal_extractor_rejects_inconsistent_movement():
    from app.core.trajectory_events import CausalTrajectoryEventExtractor

    with pytest.raises(ValueError, match="does not match zone_out"):
        CausalTrajectoryEventExtractor(
            approach="N",
            movement="N->_E",
            zone_out="_S",
        )
