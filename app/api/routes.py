from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.analyzer import analyze

router = APIRouter(prefix="/api/v1/phase", tags=["phase"])


@router.post("/analyze")
async def phase_analyze(file: UploadFile = File(...)) -> dict:
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(
            status_code=400,
            detail="Only JSON trajectory files are supported",
        )

    payload = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp.write(payload)
        temp_path = Path(tmp.name)

    try:
        return analyze(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)
