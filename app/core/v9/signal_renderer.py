from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from app.core.state_contract import StateEstimate, logical_phase_at, physical_estimate, prepare_logical_query

DEFAULT_ACTIVITY_THRESHOLD = 0.05
DEFAULT_YELLOW_DURATION_SECONDS = 3.0
DEFAULT_RED_YELLOW_DURATION_SECONDS = 2.0


class SignalQueryModel(dict):
    """JSON-compatible model with a reusable validated history snapshot."""
    def __init__(self, values, query):
        super().__init__(values)
        self.logical_query = query


def build_signal_model(result: Mapping[str, Any], *, activity_threshold=DEFAULT_ACTIVITY_THRESHOLD,
                       mode="reconstructed") -> SignalQueryModel:
    schedule = result.get("schedule")
    if not isinstance(schedule, Mapping):
        raise ValueError("V9 result has no schedule")
    query = prepare_logical_query(result, mode=mode)
    names = query.phase_names
    name_ids = {name:index for index,name in enumerate(names)}
    activity = defaultdict(dict)
    for item in schedule.get("stream_activity_by_phase", ()):
        if not isinstance(item,Mapping):
            continue
        movement = str(item.get("stream", "")).strip()
        probabilities = item.get("event_probability_by_phase", {})
        if not movement or not isinstance(probabilities,Mapping):
            continue
        activity[movement]  # Preserve stream identity even when its phase scores are unavailable.
        for name,value in probabilities.items():
            if name in name_ids:
                activity[movement][name_ids[name]] = float(value)
    approaches = defaultdict(list)
    for movement in sorted(activity):
        approaches[movement.split("->",1)[0].strip()].append(movement)
    return SignalQueryModel({
        "mode":mode, "period_s":schedule.get("period_s"),
        "phase_count":schedule.get("phase_count"), "phase_names":list(names),
        "segments":[list(row) for row in query.segments],
        "activity":dict(activity), "approaches":dict(approaches),
        "activity_threshold":float(activity_threshold),
        "activity_semantics":"vehicle_event_occupancy_NOT_lamp_probability",
        "history_validation_error":query.validation_error,
        "physical_section":physical_estimate("UNKNOWN",mode=mode).to_dict(),
    },query)


def signal_state_at(result: Mapping[str, Any], timestamp_s: float, *,
                    yellow_duration_seconds=DEFAULT_YELLOW_DURATION_SECONDS,
                    red_yellow_duration_seconds=DEFAULT_RED_YELLOW_DURATION_SECONDS,
                    activity_threshold=DEFAULT_ACTIVITY_THRESHOLD, mode=None) -> dict[str, Any]:
    """Default physical abstention; pass build_signal_model output for bulk queries."""
    if yellow_duration_seconds < 0 or red_yellow_duration_seconds < 0:
        raise ValueError("transition durations must be non-negative")
    if isinstance(result,SignalQueryModel):
        model=result
        if mode is not None and mode != model.logical_query.mode:
            raise ValueError("query mode differs from prepared model")
    else:
        model=build_signal_model(result,activity_threshold=activity_threshold,mode=mode or "reconstructed")
    mode=model.logical_query.mode
    logical=logical_phase_at(model.logical_query,timestamp_s)
    phase_id=logical.observation_support.get("phase_id")
    index=logical.observation_support.get("segment_index")
    segments=model.logical_query.segments
    position=logical.observation_support.get("query_position_s")
    previous_phase=next_phase=None
    distance_from_start=distance_to_end=0.
    if index is not None:
        start,end,_=segments[index]
        distance_from_start=position-start; distance_to_end=end-position
        if index>0 and segments[index-1][1]==start:
            previous_phase=segments[index-1][2]
        if index+1<len(segments) and segments[index+1][0]==end:
            next_phase=segments[index+1][2]
        # Circular neighbors belong only to explicitly assumed periodic mode.
        if mode != "reconstructed":
            if index==0 and start==0:
                previous_phase=segments[-1][2]
            if end==model.logical_query.period_s and segments[0][0]==0:
                next_phase=segments[0][2]
    streams=[]
    for movement,probabilities in model["activity"].items():
        score=probabilities.get(phase_id) if phase_id is not None else None
        activity=StateEstimate("MODELLED_EVENT_ACTIVITY" if score is not None else "UNKNOWN", "activity",
            "bernoulli_event_occupancy", ("activity_score_NOT_lamp_probability",),
            logical.observation_support,
            logical.abstention_reason or ("NO_PHASE_ACTIVITY_SCORE" if score is None else None),
            {"movement":movement},mode)
        proposed="UNKNOWN"; transition=None
        if mode != "reconstructed" and score is not None:
            current_green=score>=model["activity_threshold"]
            previous_green=probabilities.get(previous_phase,0.)>=model["activity_threshold"]
            next_green=probabilities.get(next_phase,0.)>=model["activity_threshold"]
            proposed="GREEN" if current_green else "RED"
            if current_green and next_phase is not None and not next_green and 0<distance_to_end<=yellow_duration_seconds:
                proposed="YELLOW"
                transition={"from_state":"GREEN","to_state":"RED","duration_seconds":float(yellow_duration_seconds)}
            elif current_green and previous_phase is not None and not previous_green and 0<=distance_from_start<red_yellow_duration_seconds:
                proposed="RED_YELLOW"
                transition={"from_state":"RED","to_state":"GREEN","duration_seconds":float(red_yellow_duration_seconds)}
        physical=physical_estimate(proposed,mode=mode,source="v9_event_activity",
            assumptions=("activity_threshold_is_assumed_plan_proxy",) if mode!="reconstructed" else (),
            observation_support=logical.observation_support,provenance={"movement":movement},logical_support=logical)
        streams.append({"movement":movement,"approach":movement.split("->",1)[0].strip(),
            "state":physical.estimated_state, **physical.to_dict(),
            "activity":{**activity.to_dict(),"activity_score":score},
            "logical_phase":logical.to_dict(),"physical_section":physical.to_dict(),
            "confidence":0.,"confidence_semantics":"no_calibrated_lamp_confidence",
            "source":"UNKNOWN" if physical.abstention_reason else "MODELLED_TRANSITION" if transition else "INFERRED_MODEL",
            "transition":transition})
    grouped=defaultdict(list)
    for stream in streams:
        grouped[stream["approach"]].append(stream)
    return {"timestamp_s":logical.observation_support["timestamp_s"],
        "cycle_position_s":position,"phase_id":phase_id,"phase_name":logical.estimated_state,
        "logical_phase":logical.to_dict(),"mode":mode,
        "physical_section":physical_estimate("UNKNOWN",mode=mode,logical_support=logical).to_dict(),
        "transition":any(s["transition"] is not None for s in streams),
        "approaches":dict(grouped),"streams":streams,
        "semantics":{"activity":"vehicle_event_occupancy_NOT_lamp_probability",
                     "physical":"UNKNOWN unless explicitly configured/simulated", "history":"validated_half_open_intervals"}}


__all__=["DEFAULT_ACTIVITY_THRESHOLD","DEFAULT_RED_YELLOW_DURATION_SECONDS",
         "DEFAULT_YELLOW_DURATION_SECONDS","SignalQueryModel","build_signal_model","signal_state_at"]
