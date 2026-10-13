import copy
import json
import pytest

from app.core.state_contract import logical_phase_at, prepare_logical_query
from app.core.v9.signal_renderer import build_signal_model, signal_state_at
from app.core.v10.semantic_mapping import signal_state_at as v10_state_at


def result(segments=None):
    return {"schedule_base_timestamp_ms":1000,"schedule":{
        "phase_names":["A","B"],"phase_count":2,"period_s":20,
        "raw_hsmm_segments":segments if segments is not None else [[0,10,0],[10,20,1]],
        "baseline_segments":[[0,10,0],[10,20,1]],
        "stream_activity_by_phase":[{"stream":"turn", "event_probability_by_phase":{"A":.9,"B":0.}}]}}


@pytest.mark.parametrize("segments,error",[
    ([[0,10,0],[5,15,1]],"OVERLAPPING_SEGMENTS"),
    ([[0,10,0],[5,15,0]],"OVERLAPPING_SEGMENTS"),
    ([[10,20,1],[0,10,0]],"UNSORTED_SEGMENTS"),
    ([[0,float('nan'),0]],"NONFINITE_OR_NONNUMERIC_BOUNDARY"),
    ([[float('-inf'),10,0]],"NONFINITE_OR_NONNUMERIC_BOUNDARY"),
    ([[0,float('inf'),0]],"NONFINITE_OR_NONNUMERIC_BOUNDARY"),
    ([[10,10,0]],"NONPOSITIVE_OR_NEGATIVE_INTERVAL"),
    ([[10,5,0]],"NONPOSITIVE_OR_NEGATIVE_INTERVAL"),
    ([[-1,5,0]],"NONPOSITIVE_OR_NEGATIVE_INTERVAL"),
    ([[0,10,2]],"INVALID_PHASE_INDEX"),
    ([[0,10,-1]],"INVALID_PHASE_INDEX"),
    ([[0,10,.5]],"INVALID_PHASE_INDEX"),
    ([[0,10,True]],"INVALID_PHASE_INDEX"),
    ([[0,10]],"INVALID_SEGMENT_SHAPE"),
])
def test_invalid_history_fails_closed_in_shared_and_real_v9_queries(segments,error):
    pred=result(segments)
    query=prepare_logical_query(pred)
    for timestamp in (1,7,100):
        logical=logical_phase_at(query,timestamp)
        assert logical.estimated_state=="UNKNOWN"
        assert logical.abstention_reason=="INVALID_PHASE_HISTORY"
        assert logical.observation_support["history_validation_error"]==error
        snapshot=signal_state_at(build_signal_model(pred),timestamp)
        assert snapshot["logical_phase"]==logical.to_dict()
        stream=snapshot["streams"][0]
        assert stream["estimated_state"]=="UNKNOWN"
        assert stream["abstention_reason"]=="INVALID_PHASE_HISTORY"
        assert stream["activity"]["estimated_state"]=="UNKNOWN"
        json.dumps(snapshot,allow_nan=False)


def test_malformed_segment_outside_query_invalidates_whole_history():
    pred=result([[0,10,0],[15,20,7]])
    assert logical_phase_at(pred,2).abstention_reason=="INVALID_PHASE_HISTORY"


@pytest.mark.parametrize("timestamp",[-1,4,5,10,100,float('nan')])
def test_v9_gaps_and_outside_history_do_not_extrapolate(timestamp):
    pred=result([[0,4,0],[6,10,1]])
    snapshot=signal_state_at(pred,timestamp)
    assert snapshot["phase_id"] is None
    assert snapshot["logical_phase"]["abstention_reason"]=="NO_TEMPORAL_COVERAGE"
    assert snapshot["streams"][0]["state"]=="UNKNOWN"
    assert snapshot["streams"][0]["transition"] is None
    assert snapshot["streams"][0]["activity"]["activity_score"] is None
    json.dumps(snapshot,allow_nan=False)


def test_half_open_intervals_and_original_logical_phase_preserved():
    pred=result()
    assert signal_state_at(pred,9.99)["logical_phase"]["estimated_state"]=="A"
    snap=signal_state_at(pred,10)
    assert snap["logical_phase"]["estimated_state"]=="B"
    assert snap["streams"][0]["activity"]["activity_score"]==0
    assert snap["streams"][0]["state"]=="UNKNOWN"


@pytest.mark.parametrize("time,configured",[(1,"RED_YELLOW"),(5,"GREEN"),(9,"YELLOW"),(15,"RED")])
def test_real_v9_fixed_colors_require_explicit_mode(time,configured):
    assert signal_state_at(result(),time)["streams"][0]["state"]=="UNKNOWN"
    for mode in ("configured","simulated"):
        stream=signal_state_at(result(),time,mode=mode)["streams"][0]
        assert stream["state"]==configured
        assert stream["mode"]==mode
        assert stream["calibrated_lamp_probability"] is None
        assert stream["physical_section"]["assumptions"]


def test_v9_reusable_snapshot_is_json_compatible_and_not_revalidated(monkeypatch):
    import app.core.state_contract as contract
    import app.core.v9.signal_renderer as renderer
    pred=result(); original=copy.deepcopy(pred); model=build_signal_model(pred)
    json.dumps(model,allow_nan=False)
    assert pred==original
    pred["schedule"]["raw_hsmm_segments"][0][1]=999
    model["segments"][0][1]=999
    model["mode"]="configured"  # The prepared snapshot, not mutable metadata, is authoritative.
    def forbidden(*args,**kwargs):
        pytest.fail("bulk query must not rebuild or revalidate history")
    monkeypatch.setattr(contract,"prepare_logical_query",forbidden)
    monkeypatch.setattr(renderer,"prepare_logical_query",forbidden)
    for time in (1,7,10,19,21):
        assert signal_state_at(model,time)["mode"]=="reconstructed"
    assert signal_state_at(model,21)["logical_phase"]["estimated_state"]=="UNKNOWN"
    with pytest.raises(ValueError,match="mode differs"):
        signal_state_at(model,1,mode="configured")


def test_prepared_v10_core_caller_uses_same_invalid_history_contract():
    pred=result([[0,10,0],[5,15,1]])
    snap=v10_state_at(pred,7,[],{},query_model=prepare_logical_query(pred))
    assert snap["logical_phase"]["abstention_reason"]=="INVALID_PHASE_HISTORY"
    assert snap["physical_section"]["abstention_reason"]=="INVALID_PHASE_HISTORY"


def test_configured_malformed_history_also_abstains():
    pred=result();pred["schedule"]["baseline_segments"]=[[0,10,0],[5,15,1]]
    assert signal_state_at(pred,7,mode="configured")["streams"][0]["abstention_reason"]=="INVALID_PHASE_HISTORY"
    assert v10_state_at(pred,7,[],{},mode="configured")["logical_phase"]["estimated_state"]=="UNKNOWN"


def test_renaming_movements_preserves_physical_abstention_and_activity():
    a=result();b=copy.deepcopy(a);b["schedule"]["stream_activity_by_phase"][0]["stream"]="arbitrary"
    first=signal_state_at(a,1)["streams"][0]; second=signal_state_at(b,1)["streams"][0]
    assert first["estimated_state"]==second["estimated_state"]=="UNKNOWN"
    assert first["activity"]["activity_score"]==second["activity"]["activity_score"]
