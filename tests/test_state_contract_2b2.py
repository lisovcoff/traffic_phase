import copy
import pytest

from app.core.state_contract import attach_state_contract, logical_phase_at, physical_estimate
from app.core.signal_renderer import build_signal_renderer_data
from app.core.signal_state_estimator import ApproachState, SignalState
from app.core.v10.semantic_mapping import PhaseSpec, signal_state_at


def result():
    return {"schedule_base_timestamp_ms": 1000, "schedule": {
        "phase_count": 2, "phase_names": ["A", "B"], "period_s": 10,
        "raw_hsmm_segments": [[0,4,0],[6,10,1]],
        "baseline_segments": [[0,5,0],[5,10,1]],
        "stream_activity_by_phase": [{"stream":"turn", "event_probability_by_phase":{"A":.9,"B":.01}}]}}


@pytest.mark.parametrize("scenario,events,proposed", [
    ("green_without_demand",0,SignalState.RED),
    ("blocked_queue_under_green",4,SignalState.RED),
    ("permissive_restart_under_red",1,SignalState.GREEN),
    ("restart_under_green",1,SignalState.GREEN)])
def test_vehicle_proposals_abstain_regardless_of_demand(scenario,events,proposed):
    payload = build_signal_renderer_data(states=[ApproachState("N",proposed,
        signal_head_id="N_MAIN",confidence=.99,supporting_event_count=events)])
    section = next(h for h in payload["heads"] if h["id"]=="N_MAIN")["sections"][0]
    assert section["state"] == section["estimated_state"] == "UNKNOWN"
    assert section["abstention_reason"] == "UNVERIFIED_SECTION_MAPPING"
    assert section["calibrated_lamp_probability"] is None


def test_same_restart_cannot_identify_different_lamps_even_with_known_hardware():
    for proposed in ("GREEN","RED"):
        state=physical_estimate(proposed,mapping_verified=True,hardware_verified=True,
                                observation_support={"restart_count":1})
        assert state.estimated_state=="UNKNOWN"
        assert state.abstention_reason=="PHYSICAL_STATE_NOT_IDENTIFIABLE_FROM_VEHICLE_EVIDENCE"


def test_turn_and_unverified_phase_mapping_never_prove_arrow():
    state=signal_state_at(result(),1,[PhaseSpec("P",frozenset({"turn"}),additional_movements=frozenset({"turn"}))],{"A":"P"})
    assert state["logical_phase"]["estimated_state"]=="A"
    assert state["mapping_candidate"]=="P"
    assert state["additional_movements"]==state["green_movements"]==[]
    assert state["physical_section"]["estimated_state"]=="UNKNOWN"
    assert signal_state_at(result(),1,[],{})["physical_section"]["abstention_reason"]=="UNVERIFIED_SECTION_MAPPING"


@pytest.mark.parametrize("timestamp",[-1,4,5,10,100,float('nan')])
def test_gaps_and_outside_history_do_not_wrap(timestamp):
    state=logical_phase_at(result(),timestamp)
    assert state.estimated_state=="UNKNOWN"
    assert state.abstention_reason=="NO_TEMPORAL_COVERAGE"
    assert state.observation_support["temporally_covered"] is False


@pytest.mark.parametrize("color",["YELLOW","RED_YELLOW","OFF","GREEN","RED"])
def test_fixed_transitions_and_hardware_states_require_explicit_mode(color):
    assert physical_estimate(color).estimated_state=="UNKNOWN"
    for mode in ("configured","simulated"):
        state=physical_estimate(color,mode=mode)
        assert state.estimated_state==color and state.mode==mode
        assert state.calibrated_lamp_probability is None
        assert state.assumptions


def test_direct_lamp_observation_is_separate_from_vehicle_evidence():
    state=physical_estimate("YELLOW",source="video_review",mapping_verified=True,hardware_verified=True,
        verified_lamp_observation=True,observation_support={"frame":2},provenance={"video_sha":"example"})
    assert state.estimated_state=="YELLOW"
    assert state.calibrated_lamp_probability is None


def test_movement_renaming_preserves_contract_without_direction_rules():
    a=result(); b=copy.deepcopy(a)
    b["schedule"]["stream_activity_by_phase"][0]["stream"]="arbitrary_identifier"
    attach_state_contract(a); attach_state_contract(b)
    assert a["state_contract"]["physical_section"]==b["state_contract"]["physical_section"]
    assert a["state_contract"]["activity"][0]["estimate"]==b["state_contract"]["activity"][0]["estimate"]
    assert logical_phase_at(a,2)==logical_phase_at(b,2)


def test_sidecar_does_not_mutate_inference_or_segments():
    a=result(); original=copy.deepcopy(a)
    attach_state_contract(a)
    assert a["schedule"]==original["schedule"]
    assert a["schedule_base_timestamp_ms"]==original["schedule_base_timestamp_ms"]
