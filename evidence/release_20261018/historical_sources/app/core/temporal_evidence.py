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
        result = asdict(self)
        interval = self.provenance.get("observation_interval_ms")
        result["temporal_uncertainty_ms_scope"] = "vehicle_event_unvalidated_heuristic_only"
        result["calibrated_lamp_probability"] = None
        result["uncertainty"] = {
            "vehicle_event": {
                "sampling_interval_ms": interval,
                "sampling_interval_width_ms": interval[1] - interval[0] if interval else None,
                "heuristic_localization_radius_ms": self.temporal_uncertainty_ms,
                "calibrated": False,
                "statistical_error_bound": False,
            },
            "event_to_signal_switch": {
                "status": "UNKNOWN",
                "uncertainty_ms": None,
                "reason": "vehicle_evidence_does_not_identify_signal_switch_time",
            },
        }
        return result


class EvidenceUnavailable(ValueError):
    """Machine-readable abstention, retaining ValueError compatibility.

    No phase schedule or K is constructed; consumers may persist to_dict().
    This is not a fabricated detector result for an empty recording.
    """
    def __init__(self, message, *, reason_code):
        super().__init__(message)
        self.reason_code = reason_code

    def to_dict(self):
        return {"status": "unavailable", "state": "UNKNOWN", "reason_code": self.reason_code,
                "reason": str(self), "phase_count": None, "schedule": None,
                "estimated_state": "UNKNOWN", "level": "logical_phase",
                "source": "temporal_evidence", "assumptions": [], "observation_support": {},
                "abstention_reason": self.reason_code, "calibrated_lamp_probability": None}


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
