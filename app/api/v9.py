from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import shutil
import threading
import uuid
import zipfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.core.v9.v9_discovery import OnlinePhaseTracker, discover_path

router = APIRouter(prefix="/api/v1/v9", tags=["v9"])


class RealtimeEventPayload(BaseModel):
    timestamp_ms: int
    stream: str = Field(min_length=1, max_length=256)


class RealtimeRequest(BaseModel):
    # Backward-compatible: callers may still send the full model.
    model: dict[str, object] | None = None
    model_id: str | None = Field(default=None, min_length=1, max_length=128)
    stream_id: str = Field(default="default", min_length=1, max_length=128)
    event: RealtimeEventPayload
    lookback_s: float = Field(default=60.0, gt=0.0)


class _V9RealtimeSession:
    def __init__(
        self,
        tracker: OnlinePhaseTracker,
        *,
        model_id: str | None,
        model_fingerprint: str,
        lookback_s: float,
        model: dict[str, object],
    ) -> None:
        self.tracker = tracker
        self.model_id = model_id
        self.model_fingerprint = model_fingerprint
        self.model = model
        self.lookback_s = float(lookback_s)


class V9RuntimeRegistry:
    """Bounded process-local storage for analyzed V9 models and realtime sessions."""

    def __init__(
        self,
        *,
        max_models: int = 32,
        max_streams: int = 128,
    ) -> None:
        if max_models <= 0:
            raise ValueError("max_models must be positive")
        if max_streams <= 0:
            raise ValueError("max_streams must be positive")
        self.max_models = int(max_models)
        self.max_streams = int(max_streams)
        self._models: OrderedDict[str, dict[str, object]] = OrderedDict()
        self._sessions: OrderedDict[str, _V9RealtimeSession] = OrderedDict()
        self._lock = threading.RLock()

    @staticmethod
    def _fingerprint(model: dict[str, object]) -> str:
        encoded = json.dumps(
            model,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    @property
    def model_count(self) -> int:
        with self._lock:
            return len(self._models)

    @property
    def stream_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def register_model(self, model: dict[str, object]) -> str:
        if not isinstance(model, dict):
            raise TypeError("model must be an object")
        model_id = f"v9_{uuid.uuid4().hex}"
        with self._lock:
            while len(self._models) >= self.max_models:
                self._models.popitem(last=False)
            self._models[model_id] = deepcopy(model)
            self._models.move_to_end(model_id)
        return model_id

    def get_model(self, model_id: str) -> dict[str, object]:
        with self._lock:
            try:
                model = self._models[model_id]
            except KeyError as exc:
                raise KeyError(f"unknown V9 model_id: {model_id}") from exc
            self._models.move_to_end(model_id)
            return model

    def get_or_create_session(
        self,
        stream_id: str,
        *,
        model_id: str | None,
        model: dict[str, object] | None,
        lookback_s: float,
    ) -> tuple[OnlinePhaseTracker, str | None]:
        with self._lock:
            existing = self._sessions.get(stream_id)
            if existing is not None:
                if (
                    model_id is not None
                    and existing.model_id != model_id
                ):
                    raise ValueError(
                        "stream already exists with a different model_id"
                    )
                if (
                    model_id is None
                    and model is not None
                    and self._fingerprint(model)
                    != existing.model_fingerprint
                ):
                    raise ValueError(
                        "stream already exists with a different model"
                    )
                if float(lookback_s) != existing.lookback_s:
                    raise ValueError(
                        "stream already exists with a different lookback_s"
                    )
                self._sessions.move_to_end(stream_id)
                return existing.tracker, existing.model_id, existing.model

            if model_id is not None:
                resolved_model = self.get_model(model_id)
            elif model is not None:
                resolved_model = model
            else:
                raise ValueError(
                    "model_id or model is required for a new realtime stream"
                )

            tracker = OnlinePhaseTracker(
                resolved_model,
                lookback_s=lookback_s,
            )
            session = _V9RealtimeSession(
                tracker,
                model_id=model_id,
                model_fingerprint=self._fingerprint(resolved_model),
                lookback_s=lookback_s,
                model=resolved_model,
            )
            while len(self._sessions) >= self.max_streams:
                self._sessions.popitem(last=False)
            self._sessions[stream_id] = session
            return tracker, model_id, resolved_model

    def reset_stream(self, stream_id: str) -> None:
        with self._lock:
            self._sessions.pop(stream_id, None)

    def clear(self) -> None:
        with self._lock:
            self._models.clear()
            self._sessions.clear()


runtime_registry = V9RuntimeRegistry()


def _attach_physical_snapshot(
    snapshot: dict[str, object],
    model: dict[str, object],
) -> None:
    physical = model.get("physical_signal_plan")
    if not isinstance(physical, dict) or not physical.get("enabled"):
        return

    mapping = physical.get("mapping", {})
    anonymous_phase = snapshot.get("phase")
    physical_phase = (
        mapping.get(anonymous_phase)
        if isinstance(mapping, dict) and anonymous_phase is not None
        else None
    )
    if physical_phase is None:
        return

    snapshot["physical_phase"] = physical_phase
    for spec in physical.get("phases", ()):
        if isinstance(spec, dict) and spec.get("name") == physical_phase:
            snapshot["physical_green_movements"] = list(
                spec.get("green_movements", ())
            )
            snapshot["physical_additional_movements"] = list(
                spec.get("additional_movements", ())
            )
            break


@router.get("/info")
def v9_info() -> dict[str, object]:
    return {
        "algorithm": "direction-agnostic-v9",
        "contract": [
            "anonymous movement streams",
            "automatic period inference",
            "automatic phase-count inference",
            "cyclic HSMM phase segmentation",
            "periodic baseline",
            "temporary phase deviation detection",
            "causal realtime tracking",
            "model_id based offline-to-realtime handoff",
            "stateful realtime streams",
        ],
        "manual_labels_used_for_discovery": False,
        "runtime": {
            "model_registry": "bounded process-local",
            "realtime_sessions": "bounded process-local",
        },
    }


@router.post("/analyze")
async def v9_analyze(
    file: UploadFile = File(...),
    dt: float = Form(default=1.0, gt=0.0),
) -> dict[str, object]:
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="Filename is required",
        )
    filename = file.filename
    lowered = filename.lower()
    if not lowered.endswith((".json", ".zip")):
        raise HTTPException(
            status_code=400,
            detail="Only JSON and ZIP inputs are supported",
        )

    try:
        with TemporaryDirectory(prefix="traffic_phase_v9_") as tmp:
            root = Path(tmp)
            target = root / Path(filename).name
            await file.seek(0)
            with target.open("wb") as sink:
                shutil.copyfileobj(
                    file.file,
                    sink,
                    length=1024 * 1024,
                )

            if lowered.endswith(".zip"):
                source = root / "archive"
                source.mkdir()
                with zipfile.ZipFile(target) as archive:
                    for info in archive.infolist():
                        if (
                            info.is_dir()
                            or not info.filename.lower().endswith(".json")
                        ):
                            continue
                        member = Path(info.filename)
                        if (
                            member.is_absolute()
                            or ".." in member.parts
                        ):
                            raise ValueError(
                                f"unsafe ZIP member path: {info.filename}"
                            )
                        destination = source / member
                        destination.parent.mkdir(
                            parents=True,
                            exist_ok=True,
                        )
                        with (
                            archive.open(info) as src,
                            destination.open("wb") as dst,
                        ):
                            shutil.copyfileobj(
                                src,
                                dst,
                                length=1024 * 1024,
                            )
            else:
                source = target

            result = discover_path(
                source,
                dt=dt,
            )
            model_id = runtime_registry.register_model(result)
            result["api"] = {
                "endpoint": "/api/v1/v9/analyze",
                "manual_labels_used": False,
                "model_id": model_id,
                "realtime": {
                    "stream_id_required": True,
                    "next_endpoint": "/api/v1/v9/realtime",
                    "send_model_id_instead_of_model": True,
                },
            }
            return result

    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid ZIP archive",
        ) from exc
    except (ValueError, TypeError, OSError) as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc


@router.post("/realtime")
def v9_realtime(payload: RealtimeRequest) -> dict[str, object]:
    try:
        tracker, effective_model_id, resolved_model = runtime_registry.get_or_create_session(
            payload.stream_id,
            model_id=payload.model_id,
            model=payload.model,
            lookback_s=payload.lookback_s,
        )

        tracker.observe(
            payload.event.timestamp_ms,
            payload.event.stream,
        )
        snapshot = tracker.infer(payload.event.timestamp_ms)

        model_for_snapshot = resolved_model
        if model_for_snapshot is not None:
            _attach_physical_snapshot(
                snapshot,
                model_for_snapshot,
            )

        return {
            "status": "ok",
            "algorithm": "direction-agnostic-v9",
            "stream_id": payload.stream_id,
            "model_id": effective_model_id,
            "snapshot": snapshot,
        }
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc


@router.delete("/realtime/streams/{stream_id}")
def reset_v9_realtime_stream(stream_id: str) -> dict[str, object]:
    runtime_registry.reset_stream(stream_id)
    return {
        "stream_id": stream_id,
        "reset": True,
    }


__all__ = [
    "RealtimeRequest",
    "V9RuntimeRegistry",
    "reset_v9_realtime_stream",
    "router",
    "runtime_registry",
    "v9_analyze",
    "v9_info",
    "v9_realtime",
]
