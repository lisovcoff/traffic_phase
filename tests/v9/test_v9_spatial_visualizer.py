from __future__ import annotations

import base64
import gzip
import json

from app.core.v9.spatial import build_spatial_projection, compact_trajectories
from scripts.v9_spatial_visualizer import (
    _physical_visual_model,
    infer_physical_signal_topology,
    render_html,
)


def _track(identifier, approach, target, x0, y0):
    return {
        "id": identifier,
        "zone_in": approach,
        "zone_out": target,
        "detections": [
            {"millis": 1000, "centroid_x": x0, "centroid_y": y0},
            {"millis": 2000, "centroid_x": x0 + 0.01, "centroid_y": y0 + 0.01},
        ],
    }


def _result():
    return {
        "algorithm": "direction-agnostic traffic phase discovery V9",
        "trajectory_count": 4,
        "event_count": 4,
        "movement_stream_count": 4,
        "analysis_base_timestamp_ms": 1000.0,
        "recording_duration_s": 100.0,
        "schedule": {
            "period_s": 100.0,
            "phase_count": 2,
            "phase_names": ["PHASE_A", "PHASE_B"],
            "baseline_segments": [
                [0.0, 50.0, 0],
                [50.0, 100.0, 1],
            ],
            "stream_activity_by_phase": [
                {"stream": "N->S", "event_probability_by_phase": {"PHASE_A": 0.9, "PHASE_B": 0.01}},
                {"stream": "S->N", "event_probability_by_phase": {"PHASE_A": 0.9, "PHASE_B": 0.01}},
                {"stream": "E->W", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.9}},
                {"stream": "W->E", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.9}},
            ],
        },
        "anomaly_detection": {"temporary_phase_deviations": []},
    }


def _unpack_payload(html: str) -> list[list[object]]:
    marker = 'const PACKED_DATA = "'
    start = html.index(marker) + len(marker)
    end = html.index('";', start)
    packed = html[start:end]
    raw = gzip.decompress(base64.b64decode(packed))
    return json.loads(raw.decode("utf-8"))


def test_spatial_visualizer_contains_fixed_cardinal_layout_and_json_data():
    tracks = [
        _track(1, "N", "S", 0.60, 0.95),
        _track(2, "S", "N", 0.85, 0.10),
        _track(3, "E", "W", 0.43, 0.20),
        _track(4, "W", "E", 0.97, 0.45),
    ]
    projection = build_spatial_projection(tracks)
    compact = compact_trajectories(
        tracks,
        analysis_base_timestamp_ms=1000,
        projection=projection,
    )
    html = render_html(_result(), projection, compact)

    assert "N — сверху" in html
    assert "S — снизу" in html
    assert "E — справа" in html
    assert "W — слева" in html
    assert 'const APPROACHES = ["N","S","E","W"]' in html
    assert "function drawLight" in html
    assert "function activeVehicles" in html
    assert "const PACKED_DATA = " in html
    payload = _unpack_payload(html)
    assert payload[0][1] == "N"
    assert payload[0][2] == "N->S"
    assert len(payload[0][3]) == 2
    assert "centroid_x" not in html
    assert "DecompressionStream" in html


def test_spatial_visualizer_omits_absent_t_intersection_approach():
    result = _result()
    tracks = [
        _track(1, "N", "S", 0.50, 0.95),
        _track(2, "S", "N", 0.50, 0.05),
        _track(3, "E", "S", 0.95, 0.50),
    ]
    projection = build_spatial_projection(tracks)
    html = render_html(result, projection, [])

    assert set(projection["anchors"]) == {"N", "S", "E"}
    assert "const ACTIVE_APPROACHES =" in html
    assert "Object.prototype.hasOwnProperty.call(PROJECTION.anchors, approach)" in html


def _lenina_physical_result():
    return {
        "algorithm": "direction-agnostic traffic phase discovery V9",
        "trajectory_count": 100,
        "event_count": 100,
        "movement_stream_count": 7,
        "analysis_base_timestamp_ms": 1000.0,
        "recording_duration_s": 100.0,
        "schedule": {
            "period_s": 99.84281321021679,
            "phase_count": 3,
            "phase_names": ["PHASE_A", "PHASE_B", "PHASE_C"],
            "baseline_segments": [
                [0.0, 21.0, 0],
                [21.0, 52.0, 1],
                [52.0, 99.84281321021679, 2],
            ],
            "baseline_duration_targets_s": {
                "PHASE_A": 21.0,
                "PHASE_B": 31.0,
                "PHASE_C": 47.0,
            },
            "stream_activity_by_phase": [
                {"stream": "E->W", "event_probability_by_phase": {"PHASE_A": 0.18, "PHASE_B": 0.01, "PHASE_C": 0.01}},
                {"stream": "W->E", "event_probability_by_phase": {"PHASE_A": 0.18, "PHASE_B": 0.01, "PHASE_C": 0.01}},
                {"stream": "W->N", "event_probability_by_phase": {"PHASE_A": 0.15, "PHASE_B": 0.01, "PHASE_C": 0.01}},
                {"stream": "N->S", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.45, "PHASE_C": 0.24}},
                {"stream": "N->E", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.11, "PHASE_C": 0.01}},
                {"stream": "E->N", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.09, "PHASE_C": 0.01}},
                {"stream": "S->N", "event_probability_by_phase": {"PHASE_A": 0.01, "PHASE_B": 0.01, "PHASE_C": 0.53}},
            ],
        },
        "anomaly_detection": {"temporary_phase_deviations": []},
    }


def test_physical_head_mapping_infers_only_supported_reciprocal_turn_sections():
    result = _result()
    result["schedule"]["stream_activity_by_phase"] += [
        {"stream": "N->E", "event_probability_by_phase": {"PHASE_A": 0.109, "PHASE_B": 0.016}},
        {"stream": "E->N", "event_probability_by_phase": {"PHASE_A": 0.095, "PHASE_B": 0.010}},
        {"stream": "W->S", "event_probability_by_phase": {"PHASE_A": 0.010, "PHASE_B": 0.076}},
        {"stream": "S->W", "event_probability_by_phase": {"PHASE_A": 0.010, "PHASE_B": 0.010}},
    ]

    topology = infer_physical_signal_topology(result)

    assert topology == {
        "N": {"main": "N->S", "arrows": ["N->E"]},
        "S": {"main": "S->N", "arrows": []},
        "E": {"main": "E->W", "arrows": ["E->N"]},
        "W": {"main": "W->E", "arrows": []},
    }

    html = render_html(
        result,
        build_spatial_projection([
            _track(1, "N", "S", 0.60, 0.95),
            _track(2, "S", "N", 0.85, 0.10),
            _track(3, "E", "W", 0.43, 0.20),
            _track(4, "W", "E", 0.97, 0.45),
        ]),
        [],
    )
    assert "const PHYSICAL_TOPOLOGY =" in html
    assert "dominant_ratio" in html
    assert "function drawArrowSection" in html


def test_visual_model_renders_turn_from_green_movements_even_without_additional_field():
    result = _result()
    result["physical_signal_plan"] = {
        "enabled": True,
        "cycle_seconds": 100.0,
        "auto_inferred": True,
        "mapping": {"PHASE_A": "NS_TURN", "PHASE_B": "EW_THROUGH"},
        "confidence": 0.9,
        "stages": [
            {
                "stage_id": 1,
                "name": "NS_TURN",
                "phase_start": 0.0,
                "phase_end": 50.0,
                "active_movements": ["N->S", "N->E", "E->N"],
                # Deliberately omit additional_movements: visualization must
                # still expose N->E and E->N as physical arrow sections.
            },
            {
                "stage_id": 2,
                "name": "EW_THROUGH",
                "phase_start": 50.0,
                "phase_end": 100.0,
                "active_movements": ["E->W", "W->E"],
            },
        ],
    }

    physical = _physical_visual_model(result, result["physical_signal_plan"])

    assert physical["topology"]["N"]["arrows"] == ["N->E"]
    assert physical["topology"]["E"]["arrows"] == ["E->N"]
    html = render_html(result, {}, [], physical_plan=result["physical_signal_plan"])
    assert '"E->N"' in html


def test_visualizer_does_not_turn_residual_activity_into_green():
    result = _result()
    html = render_html(
        result,
        build_spatial_projection([
            _track(1, "N", "S", 0.60, 0.95),
            _track(2, "S", "N", 0.85, 0.10),
            _track(3, "E", "W", 0.43, 0.20),
            _track(4, "W", "E", 0.97, 0.45),
        ]),
        [],
    )
    assert "dominantRatio>=0.70" in html

def test_spatial_visualizer_uses_v10_physical_plan_for_signal_states():
    result = _lenina_physical_result()
    physical_plan = {
        "enabled": True,
        "cycle_seconds": 99.84281321021679,
        "stages": [
            {
                "stage_id": 1,
                "name": "C",
                "phase_start": 0.0,
                "phase_end": 21.0,
                "active_movements": ["E->W", "W->E", "W->N"],
                "additional_movements": ["W->N"],
            },
            {
                "stage_id": 2,
                "name": "A",
                "phase_start": 21.0,
                "phase_end": 52.0,
                "active_movements": ["N->S", "N->E", "E->N"],
                "additional_movements": ["N->E", "E->N"],
            },
            {
                "stage_id": 3,
                "name": "B",
                "phase_start": 52.0,
                "phase_end": 99.84281321021679,
                "active_movements": ["N->S", "S->N"],
                "additional_movements": [],
            },
        ],
    }
    html = render_html(
        result,
        {},
        [],
        physical_plan=physical_plan,
    )

    assert 'const PHYSICAL = {"enabled":true' in html
    assert '"PHASE_A":"C"' in html
    assert '"PHASE_B":"A"' in html
    assert '"PHASE_C":"B"' in html
    physical = _physical_visual_model(result, physical_plan)
    assert physical["phases"][0]["additional_movements"] == ["W->N"]
    assert physical["topology"]["W"]["arrows"] == ["W->N"]
    assert 'const PHYSICAL = {"enabled":true' in html
    assert '"mapping":' in html
    assert 'const rows=PHYSICAL.enabled' in html
    assert 'String(row[2])' in html
