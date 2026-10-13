"""Identifiability contract, independent of movement names and traffic thresholds."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from bisect import bisect_right
from numbers import Integral, Real
import math
from typing import Any, Mapping


@dataclass(frozen=True)
class StateEstimate:
    estimated_state: str
    level: str
    source: str
    assumptions: tuple[str, ...] = ()
    observation_support: Mapping[str, Any] = field(default_factory=dict)
    abstention_reason: str | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)
    mode: str = "reconstructed"
    calibrated_lamp_probability: None = None

    def __post_init__(self):
        if self.level not in {"activity", "logical_phase", "physical_section"}:
            raise ValueError("invalid result level")
        if self.mode not in {"reconstructed", "configured", "simulated"}:
            raise ValueError("invalid result mode")
        if self.estimated_state == "UNKNOWN" and not self.abstention_reason:
            raise ValueError("UNKNOWN requires an abstention reason")
        if self.calibrated_lamp_probability is not None:
            raise ValueError("this contract does not measure calibrated lamp probability")

    def to_dict(self):
        return asdict(self)


def physical_estimate(state, *, mode="reconstructed", source="vehicle_phase_model",
                      assumptions=(), observation_support=None, provenance=None,
                      mapping_verified=False, hardware_verified=False,
                      verified_lamp_observation=False, logical_support=None):
    support, provenance = observation_support or {}, provenance or {}
    reason = None
    if mode == "reconstructed":
        if not mapping_verified:
            reason = "UNVERIFIED_SECTION_MAPPING"
        elif not hardware_verified:
            reason = "UNVERIFIED_HARDWARE"
        elif not (verified_lamp_observation and support and provenance and source
                  and source not in {"vehicle_phase_model", "vehicle_state_proposal"}
                  and support.get("kind") != "vehicle_model_proposal"):
            reason = "PHYSICAL_STATE_NOT_IDENTIFIABLE_FROM_VEHICLE_EVIDENCE"
    elif mode in {"configured", "simulated"}:
        assumptions = tuple(assumptions) + ("explicit_plan_states_and_transitions_are_assumed",)
    else:
        raise ValueError("invalid result mode")
    if state not in {"RED", "GREEN", "YELLOW", "RED_YELLOW", "OFF", "UNKNOWN"}:
        reason = "INVALID_HARDWARE_STATE"
    if state == "UNKNOWN" and not reason:
        reason = "NO_SECTION_STATE"
    if logical_support is not None and logical_support.abstention_reason:
        reason = logical_support.abstention_reason
    return StateEstimate("UNKNOWN" if reason else state, "physical_section", source,
                         tuple(assumptions), support, reason, provenance, mode)


@dataclass(frozen=True)
class LogicalPhaseQuery:
    """Immutable validated snapshot; construction O(n), query O(log n)."""
    phase_names: tuple[str, ...]
    segments: tuple[tuple[float, float, int], ...]
    starts: tuple[float, ...]
    source: str
    segment_source: str
    anchor_ms: float | None
    period_s: float | None
    mode: str
    validation_error: str | None = None

    def at(self, timestamp_s):
        t = float(timestamp_s)
        support = {"timestamp_s": t if math.isfinite(t) else None,
            "segment_source": self.segment_source, "temporally_covered": False,
            "vehicle_demand_is_not_lamp_observation": True,
            "local_vehicle_observation_support": "UNKNOWN",
            "coverage_semantics": "model_history_NOT_local_observation_or_lamp_observability"}
        reason = "INVALID_PHASE_HISTORY" if self.validation_error else "NO_TEMPORAL_COVERAGE"
        phase = "UNKNOWN"
        if self.validation_error:
            support["history_validation_error"] = self.validation_error
        elif math.isfinite(t) and t >= 0:
            if self.mode in {"configured", "simulated"}:
                t %= self.period_s
            index = bisect_right(self.starts, t) - 1
            if index >= 0:
                start, end, phase_id = self.segments[index]
                if start <= t < end:
                    phase, reason = self.phase_names[phase_id], None
                    support.update(temporally_covered=True, segment_interval_s=[start,end],
                                   segment_index=index, phase_id=phase_id, query_position_s=t)
        return StateEstimate(phase, "logical_phase", self.source,
            ("latent_phase_estimate_NOT_lamp_state",), support, reason,
            {"schedule_anchor_ms": self.anchor_ms}, self.mode)


def prepare_logical_query(result, *, mode="reconstructed"):
    """Validate once, fail closed for the entire malformed history. No sorting/repair."""
    if mode not in {"reconstructed", "configured", "simulated"}:
        raise ValueError("invalid result mode")
    schedule = result.get("schedule", {})
    key = "raw_hsmm_segments" if mode == "reconstructed" else "baseline_segments"
    raw_names, raw = schedule.get("phase_names", []), schedule.get(key, [])
    names, segments, error = (), [], None
    if (not isinstance(raw_names,(list,tuple)) or any(not isinstance(n,str) or not n.strip() for n in raw_names)
            or len(set(raw_names)) != len(raw_names)):
        error = "INVALID_PHASE_NAMES"
    else:
        names = tuple(raw_names)
    if not isinstance(raw,(list,tuple)):
        error = error or "INVALID_SEGMENT_CONTAINER"
    else:
        for row in raw:
            if error:
                break
            if not isinstance(row,(list,tuple)) or len(row)!=3:
                error = "INVALID_SEGMENT_SHAPE"; break
            start,end,index = row
            if any(isinstance(v,bool) or not isinstance(v,Real) or not math.isfinite(v) for v in (start,end)):
                error = "NONFINITE_OR_NONNUMERIC_BOUNDARY"; break
            if start < 0 or end <= start:
                error = "NONPOSITIVE_OR_NEGATIVE_INTERVAL"; break
            if isinstance(index,bool) or not isinstance(index,Integral) or not 0 <= index < len(names):
                error = "INVALID_PHASE_INDEX"; break
            if segments and start < segments[-1][0]:
                error = "UNSORTED_SEGMENTS"; break
            if segments and start < segments[-1][1]:
                error = "OVERLAPPING_SEGMENTS"; break
            segments.append((float(start),float(end),int(index)))
    period = schedule.get("period_s")
    if mode != "reconstructed" and (isinstance(period,bool) or not isinstance(period,Real)
                                    or not math.isfinite(period) or period <= 0):
        error = error or "INVALID_CONFIGURED_PERIOD"
    if error:
        segments = []
    return LogicalPhaseQuery(names,tuple(segments),tuple(s[0] for s in segments),
        schedule.get("model", "anonymous_phase_model"),key,result.get("schedule_base_timestamp_ms"),
        period,mode,error)


def logical_phase_at(result, timestamp_s, *, mode=None):
    """Accept a result for one-off queries or a prepared snapshot for bulk queries."""
    if isinstance(result,LogicalPhaseQuery):
        if mode is not None and mode != result.mode:
            raise ValueError("query mode differs from prepared history")
        return result.at(timestamp_s)
    return prepare_logical_query(result,mode=mode or "reconstructed").at(timestamp_s)


def attach_state_contract(result):
    """Add a sidecar; never change scores, K, period or segments."""
    schedule = result.get("schedule", {})
    rows = schedule.get("stream_activity_by_phase", [])
    result["state_contract"] = {
        "version": 1,
        "logical_phase": {"level": "logical_phase", "source": schedule.get("model"),
            "estimated_state": "QUERY_AT_TIMESTAMP", "assumptions": ["anonymous_latent_phase_NOT_lamp"],
            "observation_support": {"coverage_segments_s": schedule.get("raw_hsmm_segments", [])},
            "abstention_reason": None, "calibrated_lamp_probability": None},
        "activity": [{"movement": row["stream"], "scores": row.get("event_probability_by_phase", {}),
            "estimate": StateEstimate("MODELLED_EVENT_ACTIVITY", "activity", "bernoulli_event_occupancy",
                ("event_occupancy_score_NOT_lamp_probability",),
                {"support_kind": "fitted_vehicle_event_occupancy; local_demand_unknown"}).to_dict()} for row in rows],
        "physical_section": physical_estimate("UNKNOWN").to_dict(),
    }
    if "physical_signal_plan" in result:
        result["physical_signal_plan"]["state_semantics"] = {
            "status": "UNVERIFIED_MAPPING_HYPOTHESIS", "hardware_verified": False,
            "calibrated_lamp_probability": None, "reconstruction": "UNKNOWN",
            "reason": "turn_activity_does_not_identify_hardware_arrow"}
    return result
