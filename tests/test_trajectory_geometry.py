from app.core.trajectory_geometry import (
    build_trajectory_geometry,
    haversine_distance_m,
    normalize_detections,
)


def test_normalizes_and_sorts_detections():
    result = normalize_detections(
        [
            {"millis": 3000, "lat": 55.0, "lng": 61.0},
            {"millis": 1000, "lat": 55.001, "lng": 61.001},
            {"millis": 2000, "lat": 55.002, "lng": 61.002},
        ]
    )

    assert [item.millis for item in result.detections] == [1000, 2000, 3000]
    assert result.invalid_detection_count == 0


def test_empty_detections_return_empty_geometry():
    result = normalize_detections([])

    assert result.detections == ()
    assert result.duration_s is None
    assert result.total_distance_m == 0.0


def test_missing_detections_field_is_supported():
    result = build_trajectory_geometry({"id": 1})

    assert result.detections == ()
    assert result.invalid_detection_count == 0


def test_detection_without_millis_is_rejected():
    result = normalize_detections([{"lat": 55.0, "lng": 61.0}])

    assert result.detections == ()
    assert result.invalid_detection_count == 1


def test_detection_without_coordinates_is_rejected():
    result = normalize_detections(
        [
            {"millis": 1000, "lat": 55.0},
            {"millis": 2000, "lng": 61.0},
        ]
    )

    assert result.detections == ()
    assert result.invalid_detection_count == 2


def test_invalid_coordinates_are_rejected():
    result = normalize_detections(
        [
            {"millis": 1000, "lat": 91.0, "lng": 61.0},
            {"millis": 2000, "lat": 55.0, "lng": 181.0},
            {"millis": 3000, "lat": float("nan"), "lng": 61.0},
        ]
    )

    assert result.detections == ()
    assert result.invalid_detection_count == 3


def test_duration_is_calculated_from_detection_timestamps():
    result = normalize_detections(
        [
            {"millis": 2500, "lat": 55.0, "lng": 61.0},
            {"millis": 1000, "lat": 55.0, "lng": 61.0},
            {"millis": 5000, "lat": 55.0, "lng": 61.0},
        ]
    )

    assert result.duration_s == 4.0


def test_haversine_distance_uses_meters():
    first = normalize_detections(
        [{"millis": 1000, "lat": 55.0, "lng": 61.0}]
    ).detections[0]
    second = normalize_detections(
        [{"millis": 1000, "lat": 55.001, "lng": 61.0}]
    ).detections[0]

    distance = haversine_distance_m(first, second)

    assert 110.0 < distance < 112.0


def test_total_trajectory_distance_sums_segments():
    result = normalize_detections(
        [
            {"millis": 1000, "lat": 55.0, "lng": 61.0},
            {"millis": 2000, "lat": 55.001, "lng": 61.0},
            {"millis": 3000, "lat": 55.002, "lng": 61.0},
        ]
    )

    assert 220.0 < result.total_distance_m < 224.0


def test_mixed_valid_and_invalid_detections_are_preserved_separately():
    result = normalize_detections(
        [
            {"millis": 2000, "lat": 55.0, "lng": 61.0},
            {"millis": 1000, "lat": 55.001, "lng": 61.001},
            {"millis": 3000, "lat": 91.0, "lng": 61.0},
        ]
    )

    assert len(result.detections) == 2
    assert result.invalid_detection_count == 1
