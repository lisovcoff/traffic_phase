import pytest
from app.experimental.video_onset_bias import evaluate_bias,fit_constant_bias,pair_unique,production_bias


def truth():return [dict(index=i,bracket_s=[i*100.,i*100.+.1]) for i in range(4)]


def test_a_broad_video_interval_is_not_spurious_precise_midpoint_truth():
    report=evaluate_bias([1.], [dict(index=0,bracket_s=[0.,2.])])
    assert report['mean_distance_to_truth_bracket_s']==0
    assert report['physical_clock_uncertainty_included'] is False


def test_one_prediction_cannot_explain_two_truth_onsets():
    with pytest.raises(ValueError,match='cannot match two'):
        pair_unique([5.],[dict(index=0,bracket_s=[0,1]),dict(index=1,bracket_s=[10,11])])


def test_two_candidate_predictions_do_not_silently_select_the_best():
    with pytest.raises(ValueError,match='ambiguous'):
        pair_unique([2.,3.],[dict(index=0,bracket_s=[0,1])])


def test_noisy_lags_reject_the_constant_bias_hypothesis():
    with pytest.raises(ValueError,match='unsupported'):
        fit_constant_bias([0,103,209,317],truth())


def test_calibration_never_grants_a_clock_certificate_and_keeps_all_extra_onsets():
    model=fit_constant_bias([4.05,104.05,204.05,304.05],truth())
    assert model['bias_s']==pytest.approx(4.)
    report=evaluate_bias([404.05,504.05,604.05],[dict(index=i,bracket_s=[t,t+.1]) for i,t in enumerate([400,500])],model['bias_s'])
    assert report['within_0_5s_of_bracket']==2 and report['unpaired_predictions']==1
    with pytest.raises(ValueError,match='independent clock'):
        production_bias(model,clock_mapping_verified=False,head_mapping_verified=True)
