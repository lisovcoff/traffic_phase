from __future__ import annotations

from io import BytesIO
import json

from app.core.archive_analysis import analyze_trajectory_stream
from app.core.realtime_simulation import (
    RealtimeArchiveSimulation,
    load_realtime_simulation_source,
)


def _record(
    vehicle_id: int,
    timestamp_ms: int,
    approach: str,
    zone_out: str,
) -> dict[str, object]:
    return {
        "id": vehicle_id,
        "millis": timestamp_ms + 1000,
        "zone_in": approach,
        "zone_out": zone_out,
        "category_name": "car",
        "detections": [
            {
                "millis": timestamp_ms - 1000,
                "lat": 55.0,
                "lng": 61.0,
                "zone": approach,
            },
            {
                "millis": timestamp_ms,
                "lat": 55.00003,
                "lng": 61.0,
                "zone": None,
            },
            {
                "millis": timestamp_ms + 1000,
                "lat": 55.00006,
                "lng": 61.0,
                "zone": zone_out,
            },
        ],
    }


def _payload() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    vehicle_id = 0
    origin_ms = 1_000_000
    movements = (
        (10, "N", "_S"),
        (25, "S", "_N"),
        (70, "E", "_W"),
        (85, "W", "_E"),
    )
    for cycle in range(10):
        base_ms = origin_ms + cycle * 120_000
        for offset_s, approach, zone_out in movements:
            vehicle_id += 1
            records.append(
                _record(
                    vehicle_id,
                    base_ms + offset_s * 1000,
                    approach,
                    zone_out,
                )
            )
    return records


def run_smoke() -> dict[str, object]:
    encoded = json.dumps(_payload()).encode("utf-8")

    analysis = analyze_trajectory_stream(
        BytesIO(encoded),
        filename="synthetic-smoke.json",
    )
    if len(analysis.sessions) != 1:
        raise RuntimeError(
            f"expected one batch session, got {len(analysis.sessions)}"
        )
    session = analysis.sessions[0]
    if session.status != "ok" or session.phase_model is None:
        raise RuntimeError(
            "batch reconstruction did not produce a phase model: "
            f"{session.error_reason}"
        )

    source = load_realtime_simulation_source(
        BytesIO(encoded),
        filename="synthetic-smoke.json",
    )
    simulation = RealtimeArchiveSimulation(
        source,
        session.phase_model,
        speed=20.0,
    )
    initial = simulation.snapshot()
    if initial["synchronization_status"] != "WARMUP":
        raise RuntimeError(
            "realtime simulation must start in WARMUP"
        )
    if set(initial["signal_states"].values()) != {"UNKNOWN"}:
        raise RuntimeError(
            "WARMUP states must be UNKNOWN"
        )

    snapshot = simulation.step(10.0)
    if snapshot["synchronization_status"] != "SYNCHRONIZED":
        snapshot = simulation.step(10.0)
    if snapshot["synchronization_status"] != "SYNCHRONIZED":
        raise RuntimeError(
            "realtime simulation did not synchronize on synthetic evidence"
        )
    if snapshot["phase_id"] is None:
        raise RuntimeError(
            "synchronized realtime snapshot has no phase"
        )

    return {
        "batch_status": session.status,
        "cycle_seconds": session.cycle.estimate.cycle_seconds,
        "phase_count": len(session.phase_model.phases),
        "realtime_status": snapshot["synchronization_status"],
        "phase_id": snapshot["phase_id"],
        "phase_offset_s": snapshot["phase_offset_s"],
        "emitted_trajectory_count": snapshot[
            "evidence_summary"
        ]["emitted_trajectory_count"],
    }


def main() -> None:
    print(json.dumps(run_smoke(), indent=2))


if __name__ == "__main__":
    main()
