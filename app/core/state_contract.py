"""Identifiability contract, independent of movement names and traffic thresholds."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
                      verified_lamp_observation=False):
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
    return StateEstimate("UNKNOWN" if reason else state, "physical_section", source,
                         tuple(assumptions), support, reason, provenance, mode)


def logical_phase_at(result, timestamp_s, *, mode="reconstructed"):
    """Seconds relative to schedule anchor. No extrapolation across missing segments."""
    schedule = result.get("schedule", {})
    key = "raw_hsmm_segments" if mode == "reconstructed" else "baseline_segments"
    segments = schedule.get(key, [])
    t = float(timestamp_s)
    reason = "NO_TEMPORAL_COVERAGE"
    phase = "UNKNOWN"
    support = {"timestamp_s": t if math.isfinite(t) else None, "segment_source": key,
               "temporally_covered": False, "vehicle_demand_is_not_lamp_observation": True,
               "local_vehicle_observation_support": "UNKNOWN",
               "coverage_semantics": "model_history_NOT_local_observation_or_lamp_observability"}
    if math.isfinite(t) and t >= 0:
        if mode in {"configured", "simulated"}:
            period = schedule.get("period_s", 0)
            if period > 0:
                t %= period
        for start, end, index in segments:
            if start <= t < end:
                names = schedule.get("phase_names", [])
                if isinstance(index, int) and 0 <= index < len(names):
                    phase, reason = names[index], None
                    support.update(temporally_covered=True, segment_interval_s=[start, end])
                else:
                    reason = "INVALID_PHASE_INDEX"
                break
    return StateEstimate(phase, "logical_phase", schedule.get("model", "anonymous_phase_model"),
                         ("latent_phase_estimate_NOT_lamp_state",), support, reason,
                         {"schedule_anchor_ms": result.get("schedule_base_timestamp_ms")}, mode)


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
