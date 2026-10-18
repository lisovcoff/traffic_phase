import pytest

from app.core.manual_delay_evaluation import match_reaction_intervals, evaluate_reaction_bound


@pytest.mark.parametrize('prediction,compatible', [(7000,True),(10000,True),(6999,False),(10001,False)])
def test_reaction_interval_is_one_sided_with_closed_endpoints(prediction, compatible):
    assert bool(match_reaction_intervals([10000],[prediction])) == compatible


def test_prediction_cannot_explain_two_overlapping_manual_intervals():
    assert len(match_reaction_intervals([10000,11000],[9000])) == 1
    assert len(match_reaction_intervals([10000,11000],[8000,9000])) == 2


def test_non_greedy_matching_maximizes_full_denominator():
    pairs = match_reaction_intervals([10000,12000],[7000,10000])
    assert len(pairs) == 2


def test_truth_edges_and_history_gaps_do_not_create_switches():
    truth = dict(start_ms=0,marks=[dict(timestamp_ms=t,offset_s=t/1000,kind=z)
        for t,z in [(0,'A'),(10000,'B'),(20000,'A')]])
    pred = dict(schedule_base_timestamp_ms=0,schedule=dict(raw_hsmm_segments=[[0,8,0],[9,20,1]]))
    result = evaluate_reaction_bound(pred,truth)
    assert result['truth_boundaries'] == 1
    assert result['predicted_boundaries'] == 0


@pytest.mark.parametrize('delay',[True,-1,float('nan'),float('inf')])
def test_invalid_claimed_bound_is_rejected(delay):
    with pytest.raises(ValueError):
        match_reaction_intervals([10000],[9000],delay)
