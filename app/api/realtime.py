from __future__ import annotations

from threading import RLock

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.event_phase_discovery import (
    EventPhase,
    EventPhaseDiscoveryResult,
    MovementSignalStage,
)
from app.core.anomaly_profile import TrafficBaselineProfile
from app.core.models import EventType, TrajectoryEvent
from app.core.realtime_inference import (
    DuplicateEventError,
    RealtimeSignalInferenceEngine,
)
from app.core.realtime_phase_sync import RealtimePhaseTemplate


class PhasePayload(BaseModel):
    cycle_seconds: float = Field(gt=0)
    bin_seconds: float = Field(gt=0)
    origin_timestamp_ms: int = Field(default=0)
    phases: list[dict[str, object]]
    cycle_coverage: float = Field(default=1.0, ge=0, le=1)
    overlap: float = Field(default=0.0, ge=0, le=1)
    supporting_event_count: int = Field(default=0, ge=0)
    contradictory_event_count: int = Field(default=0, ge=0)
    movement_stages: list[dict[str, object]] = Field(default_factory=list)


class BaselineProfilePayload(BaseModel):
    payload: dict[str, object]


class RealtimeEventPayload(BaseModel):
    event_type: EventType
    timestamp_ms: int
    approach: str
    movement: str
    confidence: float = Field(default=1.0, ge=0, le=1)
    quality: str = "HIGH"


class RealtimeInferenceRequest(BaseModel):
    stream_id: str = Field(min_length=1, max_length=128)
    event: RealtimeEventPayload
    event_id: str | None = Field(default=None, min_length=1, max_length=256)
    phase_model: PhasePayload | None = None
    event_origin_ms: int | None = None
    recent_window_s: float = Field(default=12.0, gt=0)
    yellow_duration_seconds: float = Field(default=2.0, ge=0)
    baseline_profile: BaselineProfilePayload | None = None


class RealtimeTrajectoryPayload(BaseModel):
    stream_id: str = Field(min_length=1, max_length=128)
    trajectory: dict[str, object]
    trajectory_id: str | None = Field(default=None, min_length=1, max_length=256)
    phase_model: PhasePayload | None = None
    event_origin_ms: int | None = None
    recent_window_s: float = Field(default=12.0, gt=0)
    yellow_duration_seconds: float = Field(default=2.0, ge=0)
    baseline_profile: BaselineProfilePayload | None = None


def _build_phase_model(payload: PhasePayload) -> EventPhaseDiscoveryResult:
    phases = tuple(
        EventPhase(
            phase_id=int(item["phase_id"]),
            phase_start=float(item["phase_start"]),
            phase_end=float(item["phase_end"]),
            active_approaches=tuple(item.get("active_approaches", ())),
            confidence=float(item.get("confidence", 0.0)),
            supporting_event_count=int(item.get("supporting_event_count", 0)),
            contradictory_event_count=int(item.get("contradictory_event_count", 0)),
            members=tuple(item.get("members", ())),
        )
        for item in payload.phases
    )
    movement_stages = tuple(
        MovementSignalStage(
            movement_stage_id=int(item["movement_stage_id"]),
            approach=str(item["approach"]),
            movement=str(item["movement"]),
            phase_start=float(item["phase_start"]),
            phase_end=float(item["phase_end"]),
            confidence=float(item.get("confidence", 0.0)),
            repeatability=float(item.get("repeatability", 0.0)),
            stability=float(item.get("stability", 0.0)),
            supporting_event_count=int(
                item.get("supporting_event_count", 0)
            ),
            observed_cycle_count=int(
                item.get("observed_cycle_count", 0)
            ),
        )
        for item in payload.movement_stages
    )
    return EventPhaseDiscoveryResult(
        cycle_seconds=payload.cycle_seconds,
        bin_seconds=payload.bin_seconds,
        phases=phases,
        profiles=(),
        cycle_coverage=payload.cycle_coverage,
        overlap=payload.overlap,
        supporting_event_count=payload.supporting_event_count,
        contradictory_event_count=payload.contradictory_event_count,
        # Historical reference origin is not part of the realtime template.
        origin_timestamp_ms=0,
        movement_stages=movement_stages,
    )


class RealtimeEngineRegistry:
    def __init__(self) -> None:
        self._engines: dict[str, RealtimeSignalInferenceEngine] = {}
        self._lock = RLock()

    def get_or_create(
        self,
        stream_id: str,
        *,
        phase_model: EventPhaseDiscoveryResult | None,
        event_origin_ms: int | None,
        recent_window_s: float,
        yellow_duration_seconds: float,
        baseline: TrafficBaselineProfile | None,
    ) -> RealtimeSignalInferenceEngine:
        with self._lock:
            engine = self._engines.get(stream_id)
            if engine is not None:
                if (
                    phase_model is not None
                    and RealtimePhaseTemplate.from_phase_model(
                        phase_model
                    ).to_dict()
                    != engine.phase_template.to_dict()
                ):
                    raise ValueError(
                        "stream already exists with a different phase model"
                    )
                if (
                    baseline is not None
                    and engine.baseline_profile is not None
                    and baseline.to_dict() != engine.baseline_profile.to_dict()
                ):
                    raise ValueError(
                        "stream already exists with a different baseline profile"
                    )
                if baseline is not None and engine.baseline_profile is None:
                    raise ValueError(
                        "stream already exists without a baseline profile"
                    )
                if (
                    event_origin_ms is not None
                    and int(event_origin_ms) != engine.event_origin_ms
                ):
                    raise ValueError(
                        "stream already exists with a different event origin"
                    )
                return engine

            if phase_model is None:
                raise ValueError(
                    "phase_model is required when creating a realtime stream"
                )

            engine = RealtimeSignalInferenceEngine(
                phase_model,
                recent_window_s=recent_window_s,
                event_origin_ms=event_origin_ms,
                yellow_duration_seconds=yellow_duration_seconds,
                baseline=baseline,
            )
            self._engines[stream_id] = engine
            return engine

    def reset(self, stream_id: str) -> None:
        with self._lock:
            self._engines.pop(stream_id, None)


registry = RealtimeEngineRegistry()
router = APIRouter(prefix="/api/v1/realtime", tags=["realtime"])


@router.post("/infer")
async def infer_realtime(
    payload: RealtimeInferenceRequest,
) -> dict[str, object]:
    try:
        phase_model = (
            _build_phase_model(payload.phase_model)
            if payload.phase_model is not None
            else None
        )
        engine = registry.get_or_create(
            payload.stream_id,
            phase_model=phase_model,
            event_origin_ms=payload.event_origin_ms,
            recent_window_s=payload.recent_window_s,
            yellow_duration_seconds=payload.yellow_duration_seconds,
            baseline=TrafficBaselineProfile.from_dict(payload.baseline_profile.payload) if payload.baseline_profile else None,
        )
        event = TrajectoryEvent(
            event_type=payload.event.event_type,
            timestamp_ms=payload.event.timestamp_ms,
            approach=payload.event.approach,
            movement=payload.event.movement,
            confidence=payload.event.confidence,
            quality=payload.event.quality,
        )
        return engine.ingest_event(
            event,
            event_id=payload.event_id,
        ).to_dict()
    except DuplicateEventError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/trajectory")
async def infer_realtime_trajectory(
    payload: RealtimeTrajectoryPayload,
) -> dict[str, object]:
    try:
        phase_model = (
            _build_phase_model(payload.phase_model)
            if payload.phase_model is not None
            else None
        )
        engine = registry.get_or_create(
            payload.stream_id,
            phase_model=phase_model,
            event_origin_ms=payload.event_origin_ms,
            recent_window_s=payload.recent_window_s,
            yellow_duration_seconds=payload.yellow_duration_seconds,
            baseline=(
                TrafficBaselineProfile.from_dict(payload.baseline_profile.payload)
                if payload.baseline_profile
                else None
            ),
        )
        return engine.ingest_trajectory(
            payload.trajectory,
            trajectory_id=payload.trajectory_id,
        ).to_dict()
    except DuplicateEventError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/streams/{stream_id}")
async def reset_realtime_stream(stream_id: str) -> dict[str, object]:
    registry.reset(stream_id)
    return {"stream_id": stream_id, "reset": True}


__all__ = ["RealtimeEngineRegistry", "registry", "router"]
