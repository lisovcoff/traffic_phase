import pytest

from scripts.validate_causal_v8 import comparison,cases,TRAINING


def scored(correct=90,green=40,red_yellow=5,false_green=3):
    return dict(counts=dict(total=100,correct=correct,GREEN_correct=green,
        RED_correct=40,YELLOW_correct=5,RED_YELLOW_correct=red_yellow),
        confusion={'RED->GREEN':false_green,'GREEN->GREEN':green})


def test_acceptance_does_not_hide_short_color_or_false_green_regression_in_total_accuracy():
    r=comparison(scored(),scored(correct=94,green=44,red_yellow=4,false_green=4))
    assert r['aggregate_nondecreasing'] and r['green_recall_nondecreasing']
    assert not r['false_green_nonincreasing'] and not r['all_color_recalls_nondecreasing']
    other=scored();other['counts']['total']=101
    with pytest.raises(ValueError,match='denominators'):comparison(scored(),other)


def test_replay_seeds_are_disjoint_from_offline_training():
    assert not {row[3] for row in TRAINING}&{config['seed'] for _,_,config in cases()}
    assert len(cases())==8 and any(c.get('program_changes') for _,_,c in cases())
