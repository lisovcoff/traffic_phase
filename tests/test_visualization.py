from __future__ import annotations

import asyncio
from io import BytesIO
import json

from app.api.routes import phase_analyze
from app.api.visualization import visualization_page
from starlette.datastructures import UploadFile


def _record(vehicle_id: int, timestamp_ms: int, approach: str, zone_out: str):
    return {
        "id": vehicle_id,
        "millis": timestamp_ms + 1000,
        "zone_in": approach,
        "zone_out": zone_out,
        "category_name": "car",
        "detections": [
            {"millis": timestamp_ms - 1000, "lat": 55.0, "lng": 61.0, "zone": approach},
            {"millis": timestamp_ms, "lat": 55.00003, "lng": 61.0, "zone": None},
            {"millis": timestamp_ms + 1000, "lat": 55.00006, "lng": 61.0, "zone": zone_out},
        ],
    }


def _payload(cycles: int = 10):
    movements = (
        (10, "N", "_S"),
        (25, "S", "_N"),
        (70, "E", "_W"),
        (85, "W", "_E"),
    )
    records = []
    vehicle_id = 0
    for cycle in range(cycles):
        base = cycle * 120_000
        for offset_s, approach, zone_out in movements:
            vehicle_id += 1
            records.append(
                _record(
                    vehicle_id,
                    base + offset_s * 1000,
                    approach,
                    zone_out,
                )
            )
    return records


def _upload(payload):
    return UploadFile(
        file=BytesIO(json.dumps(payload).encode("utf-8")),
        filename="player.json",
    )


def test_batch_player_contract_exposes_research_snapshot():
    response = asyncio.run(phase_analyze(_upload(_payload())))
    session = response["sessions"][0]
    player = session["player"]

    assert player["version"] == "1"
    assert player["mode"] == "BATCH_RECONSTRUCTION"
    assert player["adaptive_mode"] == "BATCH_RECONSTRUCTION"
    assert player["timeline"]
    assert player["cycle_seconds"] == session["phase_model"]["cycle_seconds"]
    assert player["phase_boundaries"]
    active_movement_points = [
        point for point in player["timeline"]
        if point.get("movement_states")
    ]
    if active_movement_points:
        assert player["movement_intervals"]
    assert player["phase_extension_intervals"] == []

    point = player["timeline"][0]
    assert set(point) >= {
        "timestamp_ms",
        "cycle_position_s",
        "phase_id",
        "movement_states",
        "states",
        "confidence",
        "evidence",
        "unknown_reason",
        "adaptive_mode",
        "signal_renderer",
        "signal_source",
    }
    assert point["adaptive_mode"] == "BATCH_RECONSTRUCTION"
    assert set(point["signal_renderer"]) >= {
        "renderer_version",
        "intersection_id",
        "approaches",
        "layout",
        "heads",
    }

    assert set(player["navigation"]) >= {
        "phase_starts",
        "previous_phase",
        "next_phase",
        "unknown",
        "extensions",
        "anomalies",
        "transitions",
    }


def test_visualization_page_contains_backend_only_batch_player():
    html = visualization_page()
    required = (
        "batchPrevPhase",
        "batchNextPhase",
        "batchNextUnknown",
        "batchNextExtension",
        "batchNextAnomaly",
        "batchSpeed",
        "batchExactTimestamp",
        "batchCyclePosition",
        "batchMovementStates",
        "batchEvidence",
        "batchUnknownReason",
        "batchPlayerAdaptive",
        "movementTimeline",
        "stateTimeline",
        "function playerTimeline(",
        "function jumpBatch(",
        "function renderBatchPoint(",
        "function playBatch(",
    )
    assert all(token in html for token in required)
    assert "SignalStateEstimator" not in html
    assert "EventPhaseDiscovery" not in html

def test_visualization_contains_realtime_operator_dashboard_contract():
    html = visualization_page()
    required = (
        "CURRENT TIME",
        "SYNC STATUS",
        "CURRENT PHASE",
        "CONFIDENCE",
        "OBSERVABILITY",
        "UNKNOWN REASON",
        "TEMPLATE COMPATIBILITY",
        "ADAPTIVE MODE",
        "PHASE EXTENSION",
        "EXTENSION DURATION",
        "realtimeTemplateStates",
        "realtimeEffectiveMovements",
        "realtimeOperatorAlert",
        "INSUFFICIENT DATA",
        "LIVE OVERRIDE",
        "RECOVERY",
        "renderRealtimeSnapshot(snapshot)",
        "renderSignalRenderer(snapshot.signal_renderer||null,'signalRenderer')",
    )
    assert all(token in html for token in required)
