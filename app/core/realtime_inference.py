from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from threading import RLock
from typing import Iterable, Sequence

from app.core.models import TrajectoryEvent
from app.core.anomaly_profile import TrafficBaselineProfile
from app.core.anomaly_inference import AnomalyAwareSignalInference
from app.core.signal_state_estimator import SignalStateEstimator
from app.core.trajectory_events import extract_trajectory_events
from app.core.trajectory_geometry import build_trajectory_geometry, build_trajectory_model


@dataclass(frozen=True)
class RealtimeInferenceSnapshot:
    timestamp_ms: int
    timestamp_s: float
    phase_id: int | None
    phase: dict[str, object] | None
    signal_states: dict[str, str]
    confidence: float
    phase_confidence: float
    traffic_evidence_confidence: float
    cycle_position_s: float
    evidence_summary: dict[str, dict[str, object]]
    buffer_event_count: int
    anomaly: dict[str, object] | None = None
    duplicate: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DuplicateEventError(ValueError):
    pass


class RealtimeSignalInferenceEngine:
    """Stateful inference over a bounded rolling event buffer."""

    def __init__(
        self,
        phase_model: object,
        *,
        recent_window_s: float = 12.0,
        event_origin_ms: int = 0,
        min_phase_confidence: float = 0.20,
        min_traffic_confidence: float = 0.12,
        yellow_duration_seconds: float = 2.0,
        conflict_persistence_seconds: float = 3.0,
        baseline: TrafficBaselineProfile | None = None,
    ) -> None:
        if recent_window_s <= 0:
            raise ValueError("recent_window_s must be positive")
        self.phase_model = phase_model
        self.recent_window_s = float(recent_window_s)
        self.event_origin_ms = int(event_origin_ms)
        self._anomaly_inference = AnomalyAwareSignalInference(phase_model, baseline)
        self._estimator = SignalStateEstimator(
            phase_model,
            recent_window_s=recent_window_s,
            min_phase_confidence=min_phase_confidence,
            min_traffic_confidence=min_traffic_confidence,
            yellow_duration_seconds=yellow_duration_seconds,
            conflict_persistence_seconds=conflict_persistence_seconds,
            event_origin_ms=self.event_origin_ms,
        )
        self._events: dict[str, TrajectoryEvent] = {}
        self._seen: dict[str, tuple[str, int]] = {}
        self._current_timestamp_ms: int | None = None
        self._lock = RLock()

    @property
    def current_timestamp_ms(self) -> int | None:
        return self._current_timestamp_ms

    @property
    def buffer_event_count(self) -> int:
        return len(self._events)

    def ingest_event(
        self,
        event: TrajectoryEvent,
        *,
        event_id: str | None = None,
    ) -> RealtimeInferenceSnapshot:
        with self._lock:
            key = event_id or self._event_fingerprint(event)
            fingerprint = self._event_fingerprint(event)

            previous = self._seen.get(key)
            if previous is not None:
                if previous[0] != fingerprint:
                    raise DuplicateEventError(
                        f"idempotency key {key!r} was already used for another event"
                    )
                return self._snapshot(duplicate=True)

            self._seen[key] = (fingerprint, event.timestamp_ms)
            if self._current_timestamp_ms is None:
                self._current_timestamp_ms = event.timestamp_ms
            else:
                self._current_timestamp_ms = max(
                    self._current_timestamp_ms,
                    event.timestamp_ms,
                )

            cutoff_ms = self._current_timestamp_ms - int(
                self.recent_window_s * 1000.0
            )
            if event.timestamp_ms >= cutoff_ms:
                self._events[key] = event

            self._trim(cutoff_ms)
            return self._snapshot(duplicate=False)

    def ingest_events(
        self,
        events: Iterable[TrajectoryEvent],
        *,
        event_ids: Sequence[str | None] | None = None,
    ) -> RealtimeInferenceSnapshot:
        items = list(events)
        if event_ids is not None and len(event_ids) != len(items):
            raise ValueError("event_ids must match events length")
        snapshot = None
        for index, event in enumerate(items):
            snapshot = self.ingest_event(
                event,
                event_id=event_ids[index] if event_ids is not None else None,
            )
        if snapshot is None:
            raise ValueError("at least one event is required")
        return snapshot

    def ingest_trajectory(
        self,
        trajectory: dict[str, object],
        *,
        trajectory_id: str | None = None,
    ) -> RealtimeInferenceSnapshot:
        model = build_trajectory_model(trajectory)
        geometry = build_trajectory_geometry(trajectory)
        events = extract_trajectory_events(model, geometry)
        if not events:
            raise ValueError("trajectory produced no usable events")

        prefix = trajectory_id or str(model.vehicle_id)
        event_ids = [
            (
                f"{prefix}:{event.event_type.value}:{event.timestamp_ms}:"
                f"{event.approach}:{event.movement}"
            )
            for event in events
        ]
        return self.ingest_events(events, event_ids=event_ids)

    def snapshot(self) -> RealtimeInferenceSnapshot:
        with self._lock:
            return self._snapshot(duplicate=False)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._seen.clear()
            self._current_timestamp_ms = None

    def _snapshot(self, *, duplicate: bool) -> RealtimeInferenceSnapshot:
        if self._current_timestamp_ms is None:
            raise ValueError("no realtime event has been ingested")

        timestamp_s = (
            self._current_timestamp_ms - self.event_origin_ms
        ) / 1000.0
        buffered_events = tuple(self._events.values())
        result = self._estimator.estimate(max(0.0, timestamp_s), buffered_events)
        aware = self._anomaly_inference.estimate(
            result,
            buffered_events,
            current_time_s=max(0.0, timestamp_s),
            recent_window_s=self.recent_window_s,
            origin_ms=self.event_origin_ms,
        )
        result = aware.signal

        phase = next(
            (
                item.to_dict()
                for item in getattr(self.phase_model, "phases", ())
                if item.phase_id == result.phase_id
            ),
            None,
        )
        signal_states = {
            item.approach: item.state.value
            for item in result.approaches
        }
        evidence_summary = {
            item.approach: {
                "state": item.state.value,
                "evidence_weight": item.evidence_weight,
                "supporting_event_count": item.supporting_event_count,
                "contradictory_event_count": item.contradictory_event_count,
                "traffic_evidence_confidence": item.traffic_evidence_confidence,
                "confidence": item.confidence,
            }
            for item in result.approaches
        }
        confidence = round(
            max(
                0.0,
                min(
                    1.0,
                    0.70 * result.phase_confidence
                    + 0.30 * result.traffic_evidence_confidence,
                ),
            ),
            4,
        )
        return RealtimeInferenceSnapshot(
            timestamp_ms=self._current_timestamp_ms,
            timestamp_s=round(timestamp_s, 3),
            phase_id=result.phase_id,
            phase=phase,
            signal_states=signal_states,
            confidence=confidence,
            phase_confidence=result.phase_confidence,
            traffic_evidence_confidence=result.traffic_evidence_confidence,
            cycle_position_s=result.cycle_phase_s,
            evidence_summary=evidence_summary,
            buffer_event_count=len(self._events),
            anomaly=aware.indicators.to_dict(),
            duplicate=duplicate,
        )

    def _trim(self, cutoff_ms: int) -> None:
        stale_keys = [
            key
            for key, event in self._events.items()
            if event.timestamp_ms < cutoff_ms
        ]
        for key in stale_keys:
            self._events.pop(key, None)

        stale_seen = [
            key
            for key, (_fingerprint, timestamp_ms) in self._seen.items()
            if timestamp_ms < cutoff_ms
        ]
        for key in stale_seen:
            self._seen.pop(key, None)

    @staticmethod
    def _event_fingerprint(event: TrajectoryEvent) -> str:
        payload = {
            "event_type": event.event_type.value,
            "timestamp_ms": int(event.timestamp_ms),
            "approach": event.approach,
            "movement": event.movement,
            "confidence": round(float(event.confidence), 6),
            "quality": event.quality,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
