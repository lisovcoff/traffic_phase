from __future__ import annotations

import json

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.preprocessing import load_trajectory_payload
from app.core.reconstruction import reconstruct_trajectories

router = APIRouter(prefix="/api/v1/phase", tags=["phase"])


@router.post("/analyze")
async def phase_analyze(file: UploadFile = File(...)) -> dict[str, object]:
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON trajectory files are supported")

    try:
        payload = json.loads(await file.read())
        trajectories = load_trajectory_payload(payload)
        reconstruction = reconstruct_trajectories(trajectories)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    timestamps = [event.timestamp_ms for event in reconstruction.events]
    duration_s = (
        max(0.0, (max(timestamps) - reconstruction.origin_timestamp_ms) / 1000.0)
        if timestamps
        else 0.0
    )

    return {
        "mode": "event_based_inference",
        "ground_truth": "UNAVAILABLE",
        "source": {
            "filename": file.filename,
            "cars_used": len(reconstruction.trajectories),
            "events_used": len(reconstruction.events),
            "start_timestamp_ms": reconstruction.origin_timestamp_ms,
            "duration_s": round(duration_s, 3),
        },
        "cycle": reconstruction.cycle.to_dict(),
        "phase_model": reconstruction.phase_model.to_dict(),
        "limitations": [
            "The traffic-light state is inferred indirectly from trajectory events.",
            "No controller/signal ground truth is present in the trajectory data.",
            "Yellow and RED_YELLOW are configurable transition windows around inferred phase boundaries.",
        ],
    }
