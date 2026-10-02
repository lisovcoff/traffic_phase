from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

import numpy as np


APPROACHES = ("N", "S", "E", "W")

CANONICAL_APPROACH_POINTS: Mapping[str, tuple[float, float]] = {
    "N": (0.50, 0.10),
    "S": (0.50, 0.90),
    "E": (0.90, 0.50),
    "W": (0.10, 0.50),
}

CANONICAL_CENTER = np.array([0.50, 0.50], dtype=float)
CANONICAL_RADIUS = 0.40


def norm_approach(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("_", "").strip().upper()
    return text if text in APPROACHES else None


def _detection_points(track: Mapping[str, Any]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for detection in track.get("detections") or ():
        if not isinstance(detection, Mapping):
            continue
        if (
            detection.get("centroid_x") is None
            or detection.get("centroid_y") is None
            or detection.get("millis") is None
        ):
            continue
        try:
            x = float(detection["centroid_x"])
            y = float(detection["centroid_y"])
            float(detection["millis"])
        except (TypeError, ValueError):
            continue
        if np.isfinite(x) and np.isfinite(y):
            points.append((x, y))
    return points


def build_approach_anchors(
    tracks: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[float, float]]:
    grouped: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for track in tracks:
        approach = norm_approach(track.get("zone_in"))
        if approach is None:
            continue
        points = _detection_points(track)
        if not points:
            continue
        grouped[approach].append(points[0])

    anchors: dict[str, tuple[float, float]] = {}
    for approach in APPROACHES:
        points = grouped.get(approach)
        if not points:
            continue
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        anchors[approach] = (
            float(np.median(xs)),
            float(np.median(ys)),
        )
    return anchors


def _solve_homography(
    source: Sequence[tuple[float, float]],
    target: Sequence[tuple[float, float]],
) -> np.ndarray:
    if len(source) != 4 or len(target) != 4:
        raise ValueError("four point pairs are required")

    matrix = []
    vector = []
    for (x, y), (u, v) in zip(source, target):
        matrix.append([x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y])
        vector.append(u)
        matrix.append([0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y])
        vector.append(v)

    coefficients = np.linalg.solve(
        np.asarray(matrix, dtype=float),
        np.asarray(vector, dtype=float),
    )
    return np.array(
        [
            [coefficients[0], coefficients[1], coefficients[2]],
            [coefficients[3], coefficients[4], coefficients[5]],
            [coefficients[6], coefficients[7], 1.0],
        ],
        dtype=float,
    )


def _solve_affine(
    source: Sequence[tuple[float, float]],
    target: Sequence[tuple[float, float]],
) -> np.ndarray:
    matrix = []
    ux = []
    vy = []
    for (x, y), (u, v) in zip(source, target):
        matrix.append([x, y, 1.0])
        ux.append(u)
        vy.append(v)

    solution_u, *_ = np.linalg.lstsq(
        np.asarray(matrix, dtype=float),
        np.asarray(ux, dtype=float),
        rcond=None,
    )
    solution_v, *_ = np.linalg.lstsq(
        np.asarray(matrix, dtype=float),
        np.asarray(vy, dtype=float),
        rcond=None,
    )

    return np.array(
        [
            [solution_u[0], solution_u[1], solution_u[2]],
            [solution_v[0], solution_v[1], solution_v[2]],
            [0.0, 0.0, 1.0],
        ],
        dtype=float,
    )



def _project_linear(
    matrix: np.ndarray,
    x: float,
    y: float,
) -> np.ndarray | None:
    point = matrix @ np.array([float(x), float(y), 1.0], dtype=float)
    denominator = float(point[2])
    if abs(denominator) < 1e-12 or not np.isfinite(denominator):
        return None
    result = point[:2] / denominator
    if not np.all(np.isfinite(result)):
        return None
    return result


def _track_heading(
    track: Mapping[str, Any],
    matrix: np.ndarray,
) -> np.ndarray | None:
    points = _detection_points(track)
    if len(points) < 2:
        return None
    first = _project_linear(matrix, *points[0])
    last = _project_linear(matrix, *points[-1])
    if first is None or last is None:
        return None
    vector = last - first
    norm = float(np.linalg.norm(vector))
    if norm < 1e-9:
        return None
    return vector / norm


def _estimate_straight_heading(
    tracks: Sequence[Mapping[str, Any]],
    matrix: np.ndarray,
    source: str,
    target: str,
) -> tuple[np.ndarray | None, int]:
    vectors: list[np.ndarray] = []
    for track in tracks:
        if (
            norm_approach(track.get("zone_in")) != source
            or norm_approach(track.get("zone_out")) != target
        ):
            continue
        vector = _track_heading(track, matrix)
        if vector is None:
            continue
        # Orient reverse streams to the same canonical direction.
        if (source, target) in {("N", "S"), ("E", "W")}:
            vector = -vector
        vectors.append(vector)

    if not vectors:
        return None, 0

    heading = np.median(np.asarray(vectors, dtype=float), axis=0)
    norm = float(np.linalg.norm(heading))
    if norm < 1e-9:
        return None, 0
    return heading / norm, len(vectors)


def _track_initial_heading(
    track: Mapping[str, Any],
    matrix: np.ndarray,
) -> np.ndarray | None:
    points = _detection_points(track)
    if len(points) < 2:
        return None

    projected: list[np.ndarray] = []
    for point in points:
        value = _project_linear(matrix, *point)
        if value is not None:
            projected.append(value)
    if len(projected) < 2:
        return None

    # Estimate the incoming-road heading before the vehicle reaches the
    # intersection. This remains valid for a T-junction where a side road
    # has no reciprocal straight stream (e.g. E exists but W does not).
    prefix_size = max(
        2,
        min(
            len(projected),
            max(3, int(np.ceil(len(projected) * 0.25))),
        ),
    )
    prefix = np.asarray(projected[:prefix_size], dtype=float)
    centered = prefix - np.mean(prefix, axis=0)
    covariance = centered.T @ centered
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    heading = np.asarray(eigenvectors[:, int(np.argmax(eigenvalues))], dtype=float)

    direction = prefix[-1] - prefix[0]
    if float(np.dot(heading, direction)) < 0.0:
        heading = -heading
    norm = float(np.linalg.norm(heading))
    if norm < 1e-9:
        return None
    return heading / norm


def _estimate_approach_heading(
    tracks: Sequence[Mapping[str, Any]],
    matrix: np.ndarray,
    approach: str,
) -> tuple[np.ndarray | None, int]:
    vectors: list[np.ndarray] = []
    for track in tracks:
        if norm_approach(track.get("zone_in")) != approach:
            continue
        heading = _track_initial_heading(track, matrix)
        if heading is not None:
            vectors.append(heading)
    if not vectors:
        return None, 0
    heading = np.median(np.asarray(vectors, dtype=float), axis=0)
    norm = float(np.linalg.norm(heading))
    if norm < 1e-9:
        return None, 0
    return heading / norm, len(vectors)


def _estimate_heading_axes(
    tracks: Sequence[Mapping[str, Any]],
    matrix: np.ndarray,
) -> tuple[np.ndarray | None, np.ndarray | None, dict[str, Any]]:
    horizontal, horizontal_samples = _estimate_straight_heading(
        tracks, matrix, "W", "E"
    )
    reverse_horizontal, reverse_horizontal_samples = _estimate_straight_heading(
        tracks, matrix, "E", "W"
    )
    vertical, vertical_samples = _estimate_straight_heading(
        tracks, matrix, "S", "N"
    )
    reverse_vertical, reverse_vertical_samples = _estimate_straight_heading(
        tracks, matrix, "N", "S"
    )

    def merge(
        first: np.ndarray | None,
        second: np.ndarray | None,
    ) -> np.ndarray | None:
        if first is None:
            return second
        if second is None:
            return first
        combined = first + second
        norm = float(np.linalg.norm(combined))
        return combined / norm if norm >= 1e-9 else first

    horizontal = merge(horizontal, reverse_horizontal)
    vertical = merge(vertical, reverse_vertical)

    horizontal_fallback_samples = 0
    if horizontal is None:
        east_heading, east_samples = _estimate_approach_heading(tracks, matrix, "E")
        west_heading, west_samples = _estimate_approach_heading(tracks, matrix, "W")
        # Incoming E traffic points toward -X, so invert it to obtain the
        # canonical W->E axis direction. Incoming W traffic already points +X.
        if east_heading is not None:
            east_heading = -east_heading
        horizontal = merge(east_heading, west_heading)
        horizontal_fallback_samples = east_samples + west_samples

    vertical_fallback_samples = 0
    if vertical is None:
        north_heading, north_samples = _estimate_approach_heading(tracks, matrix, "N")
        south_heading, south_samples = _estimate_approach_heading(tracks, matrix, "S")
        # Incoming N traffic points +Y; invert it. Incoming S traffic points -Y.
        if north_heading is not None:
            north_heading = -north_heading
        vertical = merge(south_heading, north_heading)
        vertical_fallback_samples = north_samples + south_samples

    return (
        horizontal,
        vertical,
        {
            "available": horizontal is not None and vertical is not None,
            "samples": {
                "W_to_E": horizontal_samples,
                "E_to_W": reverse_horizontal_samples,
                "S_to_N": vertical_samples,
                "N_to_S": reverse_vertical_samples,
                "horizontal_approach_fallback": horizontal_fallback_samples,
                "vertical_approach_fallback": vertical_fallback_samples,
            },
        },
    )


def _build_heading_alignment(
    tracks: Sequence[Mapping[str, Any]],
    base_matrix: np.ndarray,
    anchors: Mapping[str, tuple[float, float]],
) -> tuple[np.ndarray, dict[str, Any]] | None:
    horizontal, vertical, metadata = _estimate_heading_axes(tracks, base_matrix)
    if horizontal is None or vertical is None:
        metadata["reason"] = "insufficient_straight_heading_evidence"
        return None

    source_basis = np.column_stack((horizontal, vertical))
    determinant = float(np.linalg.det(source_basis))
    if abs(determinant) < 1e-6:
        metadata["reason"] = "straight_headings_are_near_collinear"
        return None

    # Map observed W->E / S->N basis vectors to canonical +X / -Y.
    # The inverse basis removes non-orthogonality (shear correction).
    target_basis = np.array([[1.0, 0.0], [0.0, -1.0]], dtype=float)
    linear_unit = target_basis @ np.linalg.inv(source_basis)

    # One common scalar keeps X/Y scale isotropic after orthogonalization.
    transformed_radii: list[float] = []
    for point in anchors.values():
        projected = _project_linear(base_matrix, *point)
        if projected is None:
            continue
        transformed = linear_unit @ (projected - CANONICAL_CENTER)
        radius = float(np.linalg.norm(transformed))
        if radius > 1e-9 and np.isfinite(radius):
            transformed_radii.append(radius)
    if not transformed_radii:
        metadata["reason"] = "unable_to_estimate_canonical_scale"
        return None

    median_radius = float(np.median(transformed_radii))
    scale = CANONICAL_RADIUS / median_radius
    linear = scale * linear_unit
    translation = CANONICAL_CENTER - linear @ CANONICAL_CENTER
    correction = np.array([
        [linear[0, 0], linear[0, 1], translation[0]],
        [linear[1, 0], linear[1, 1], translation[1]],
        [0.0, 0.0, 1.0],
    ], dtype=float)

    final_matrix = correction @ base_matrix
    horizontal_angle_deg = float(np.degrees(np.arctan2(horizontal[1], horizontal[0])))
    vertical_angle_from_up_deg = float(np.degrees(np.arctan2(vertical[0], -vertical[1])))
    observed_angle_deg = float(np.degrees(np.arccos(
        np.clip(float(np.dot(horizontal, vertical)), -1.0, 1.0)
    )))

    metadata.update({
        "source_axes": {
            "W_to_E": [float(value) for value in horizontal],
            "S_to_N": [float(value) for value in vertical],
        },
        "heading_angles_deg": {
            "W_to_E_from_positive_X": horizontal_angle_deg,
            "S_to_N_from_negative_Y": vertical_angle_from_up_deg,
        },
        "observed_axis_angle_deg": observed_angle_deg,
        "observed_orthogonality_error_deg": abs(90.0 - observed_angle_deg),
        "isotropic_scale": float(scale),
        "correction_matrix": [
            [float(value) for value in row]
            for row in correction
        ],
    })
    return final_matrix, metadata

def build_spatial_projection(
    tracks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    anchors = build_approach_anchors(tracks)
    usable = [
        approach
        for approach in APPROACHES
        if approach in anchors
    ]

    if len(usable) == 4:
        source = [anchors[item] for item in APPROACHES]
        target = [CANONICAL_APPROACH_POINTS[item] for item in APPROACHES]
        try:
            base_matrix = _solve_homography(source, target)
            base_method = "four_point_homography"
        except np.linalg.LinAlgError:
            base_matrix = _solve_affine(source, target)
            base_method = "least_squares_affine_fallback"
    elif len(usable) >= 3:
        source = [anchors[item] for item in usable]
        target = [CANONICAL_APPROACH_POINTS[item] for item in usable]
        base_matrix = _solve_affine(source, target)
        base_method = "least_squares_affine_partial"
    else:
        base_matrix = np.eye(3, dtype=float)
        base_method = "identity_insufficient_approach_anchors"

    matrix = base_matrix
    method = base_method
    heading_alignment: dict[str, Any] = {
        "available": False,
        "source": "straight movement track headings",
        "target_axes": {
            "W_to_E": "+X",
            "S_to_N": "-Y",
        },
    }

    # Use straight-stream headings when available; for a 3-leg intersection,
    # fall back to the incoming heading of the single side-road approach.
    if len(usable) >= 3:
        aligned = _build_heading_alignment(tracks, base_matrix, anchors)
        if aligned is not None:
            matrix, heading_alignment = aligned
            method = f"heading_aligned_{base_method}"

    return {
        "method": method,
        "base_method": base_method,
        "anchors": {
            approach: [float(x), float(y)]
            for approach, (x, y) in anchors.items()
        },
        "matrix": [
            [float(value) for value in row]
            for row in matrix
        ],
        "base_matrix": [
            [float(value) for value in row]
            for row in base_matrix
        ],
        "heading_alignment": heading_alignment,
        "canonical_approaches": {
            approach: list(CANONICAL_APPROACH_POINTS[approach])
            for approach in APPROACHES
        },
    }


def apply_projection(
    projection: Mapping[str, Any],
    x: float,
    y: float,
) -> tuple[float, float]:
    matrix = np.asarray(projection["matrix"], dtype=float)
    point = matrix @ np.array([float(x), float(y), 1.0], dtype=float)
    denominator = float(point[2])
    if abs(denominator) < 1e-12:
        raise ValueError("projected homogeneous coordinate is zero")
    return (
        float(point[0] / denominator),
        float(point[1] / denominator),
    )


def compact_trajectories(
    tracks: Sequence[Mapping[str, Any]],
    *,
    analysis_base_timestamp_ms: float,
    projection: Mapping[str, Any],
) -> list[list[Any]]:
    result: list[list[Any]] = []
    for track in tracks:
        approach = norm_approach(track.get("zone_in"))
        target = norm_approach(track.get("zone_out"))
        if approach is None or target is None or approach == target:
            continue

        detections: list[list[float]] = []
        for detection in track.get("detections") or ():
            if not isinstance(detection, Mapping):
                continue
            if (
                detection.get("millis") is None
                or detection.get("centroid_x") is None
                or detection.get("centroid_y") is None
            ):
                continue
            try:
                millis = float(detection["millis"])
                x = float(detection["centroid_x"])
                y = float(detection["centroid_y"])
            except (TypeError, ValueError):
                continue
            if not (
                np.isfinite(millis)
                and np.isfinite(x)
                and np.isfinite(y)
            ):
                continue
            if millis < analysis_base_timestamp_ms:
                continue

            px, py = apply_projection(projection, x, y)
            if not (
                np.isfinite(px)
                and np.isfinite(py)
            ):
                continue

            detections.append([
                round((millis - analysis_base_timestamp_ms) / 1000.0, 3),
                round(px, 6),
                round(py, 6),
            ])

        if not detections:
            continue
        detections.sort(key=lambda item: item[0])

        identifier = track.get("id")
        if isinstance(identifier, (int, float)) and float(identifier).is_integer():
            identifier = int(identifier)
        elif identifier is None:
            identifier = ""

        result.append([
            identifier,
            approach,
            f"{approach}->{target}",
            detections,
        ])
    return result
