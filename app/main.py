from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile

from .analyzer import analyze

app = FastAPI(
    title="Traffic Phase Estimator",
    version="0.2.0",
    description="Estimate recurring traffic-light phase structure from vehicle trajectories.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/phase/analyze")
async def phase_analyze(file: UploadFile = File(...)) -> dict:
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON trajectory files are supported")

    payload = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp.write(payload)
        temp_path = Path(tmp.name)

    try:
        return analyze(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "traffic-phase", "version": "0.2.0"}
