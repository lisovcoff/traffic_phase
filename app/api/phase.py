from __future__ import annotations

import json
import zipfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.archive_analysis import analyze_trajectory_stream
from app.core.intersection_config import (
    DEFAULT_INTERSECTION_CONFIG,
    IntersectionConfig,
)
from app.core.reconstruction import DEFAULT_SESSION_GAP_SECONDS

router = APIRouter(prefix="/api/v1/phase", tags=["phase"])


@router.post("/analyze")
async def phase_analyze(
    file: UploadFile = File(...),
    session_gap_seconds: float = DEFAULT_SESSION_GAP_SECONDS,
    intersection_config: str | None = Form(default=None),
) -> dict[str, object]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")
    if not file.filename.lower().endswith((".json", ".zip")):
        raise HTTPException(
            status_code=400,
            detail="Only JSON and ZIP trajectory files are supported",
        )
    if session_gap_seconds <= 0:
        raise HTTPException(
            status_code=400,
            detail="session_gap_seconds must be positive",
        )

    try:
        await file.seek(0)
        config = (
            IntersectionConfig.from_dict(
                json.loads(intersection_config)
            )
            if intersection_config
            else DEFAULT_INTERSECTION_CONFIG
        )
        analysis = analyze_trajectory_stream(
            file.file,
            filename=file.filename,
            session_gap_seconds=session_gap_seconds,
            intersection_config=config,
        )
        return analysis.to_dict()
    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid or corrupted ZIP archive",
        ) from exc
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
