from __future__ import annotations

import json
import uuid
import zipfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from app.api.realtime import PhasePayload, _build_phase_model
from app.core.realtime_simulation import (
    DEFAULT_SIMULATION_SPEED,
    RealtimeArchiveSimulation,
    RealtimeSimulationRegistry,
    load_realtime_simulation_source,
)


router = APIRouter(
    prefix="/api/v1/realtime/simulations",
    tags=["realtime-simulation"],
)
simulation_registry = RealtimeSimulationRegistry()


def _simulation_or_404(
    simulation_id: str,
) -> RealtimeArchiveSimulation:
    try:
        return simulation_registry.get(simulation_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="realtime simulation not found",
        ) from exc


@router.post("/start")
async def start_realtime_simulation(
    file: UploadFile = File(...),
    phase_model: str = Form(...),
    speed: float = Form(DEFAULT_SIMULATION_SPEED),
    simulation_id: str | None = Form(default=None),
) -> dict[str, object]:
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="Filename is required",
        )
    try:
        phase_payload = PhasePayload.model_validate_json(
            phase_model
        )
        model = _build_phase_model(phase_payload)
        await file.seek(0)
        source = load_realtime_simulation_source(
            file.file,
            filename=file.filename,
        )
        simulation = RealtimeArchiveSimulation(
            source,
            model,
            speed=speed,
        )
        identifier = simulation_id or uuid.uuid4().hex
        if not identifier.strip():
            raise ValueError("simulation_id must not be empty")
        simulation_registry.create(
            identifier,
            simulation,
        )
        return {
            "simulation_id": identifier,
            **simulation.snapshot(),
        }
    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid or corrupted ZIP archive",
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid phase_model payload",
        ) from exc
    except (
        ValueError,
        TypeError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc


@router.get("/{simulation_id}/status")
async def realtime_simulation_status(
    simulation_id: str,
) -> dict[str, object]:
    simulation = _simulation_or_404(simulation_id)
    return {
        "simulation_id": simulation_id,
        **simulation.snapshot(),
    }


@router.post("/{simulation_id}/step")
async def step_realtime_simulation(
    simulation_id: str,
    elapsed_seconds: float = 1.0,
    speed: float | None = None,
) -> dict[str, object]:
    simulation = _simulation_or_404(simulation_id)
    try:
        snapshot = simulation.step(
            elapsed_seconds,
            speed=speed,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    return {
        "simulation_id": simulation_id,
        **snapshot,
    }


@router.post("/{simulation_id}/reset")
async def reset_realtime_simulation(
    simulation_id: str,
) -> dict[str, object]:
    simulation = _simulation_or_404(simulation_id)
    return {
        "simulation_id": simulation_id,
        **simulation.reset(),
    }


@router.delete("/{simulation_id}")
async def delete_realtime_simulation(
    simulation_id: str,
) -> dict[str, object]:
    removed = simulation_registry.remove(
        simulation_id
    )
    if not removed:
        raise HTTPException(
            status_code=404,
            detail="realtime simulation not found",
        )
    return {
        "simulation_id": simulation_id,
        "deleted": True,
    }


__all__ = [
    "router",
    "simulation_registry",
]
