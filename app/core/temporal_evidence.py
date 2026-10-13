"""Vehicle timing evidence, never a probability or observation of a lamp state."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any


@dataclass(frozen=True, slots=True)
class TemporalEvent:
    timestamp_ms: float
    event_type: str
    movement: str
    source_track_id: Any
    evidence_method: str
    confidence: float
    evidence_quality: str
    temporal_uncertainty_ms: float | None
    provenance: dict[str, Any]

    def __post_init__(self):
        if not math.isfinite(self.timestamp_ms) or self.timestamp_ms < 0:
            raise ValueError("invalid event timestamp")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("invalid heuristic evidence confidence")
        if self.temporal_uncertainty_ms is not None and (
            not math.isfinite(self.temporal_uncertainty_ms) or self.temporal_uncertainty_ms < 0
        ):
            raise ValueError("invalid temporal uncertainty")
        if self.event_type not in {"ENTRY", "STOP", "RELEASE", "CROSSING", "CROSSING_PROXY"}:
            raise ValueError("unknown vehicle evidence type")
        if self.evidence_quality not in {"HIGH", "MEDIUM", "LOW"}:
            raise ValueError("unknown evidence quality")
        if self.event_type == "CROSSING" and not self.provenance.get("verified_stop_line"):
            raise ValueError("actual CROSSING requires verified stop-line provenance")

    def to_dict(self):
        return asdict(self)


def adapt_trajectory_event(event, *, source_track_id, evidence_method, provenance,
                           temporal_uncertainty_ms=None):
    """Bridge existing trajectory_events outputs without reimplementing motion logic.

    Legacy CROSSING may be a zone or track-end proxy. Its enum alone never
    authorizes claiming an actual stop-line crossing.
    """
    kind = getattr(event.event_type, "value", event.event_type)
    if kind == "APPROACH":
        kind = "ENTRY"
    if kind == "CROSSING" and not provenance.get("verified_stop_line"):
        kind = "CROSSING_PROXY"
    return TemporalEvent(float(event.timestamp_ms), kind, event.movement, source_track_id,
                         evidence_method, float(event.confidence), event.quality,
                         temporal_uncertainty_ms, dict(provenance))


class EventStreamBundle(tuple):
    """Keep the existing 10-slot packed-stream API plus aligned evidence sidecar."""
    def __new__(cls, values, *, temporal_events=(), permission_streams=None, diagnostics=None):
        obj = super().__new__(cls, values)
        obj.temporal_events = tuple(temporal_events)
        obj.permission_streams = permission_streams or {}
        obj.diagnostics = diagnostics or {}
        return obj
