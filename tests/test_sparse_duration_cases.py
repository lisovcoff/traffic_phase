import inspect

from scripts.sparse_duration_cases import make_case,suite


def test_suite_is_frozen_reproducible_sparse_and_truth_not_in_inputs():
    inputs,truth=suite();again,labels=suite()
    assert inputs==again and truth==labels and len(inputs)==16
    assert {x['seed'] for x in inputs}=={7,23}
    for x in inputs:
        assert not {'initial_phase','initial_phase_start_s','observed_segment_count'} & x['spec'].keys()
        assert 'segments' not in x and 'truth' not in x
        assert all(r['event']['timestamp_ms']==int(r['event']['timestamp_ms']) for r in x['view']['events'])
    assert 'infer_unanchored' not in inspect.getsource(make_case)


def test_hold_shortening_truth_and_initial_ages_independent():
    for seed,age in ((7,2),(23,6)):
        for kind,d in (('stable',10),('hold10',20),('shortening',6),('hold30',40)):
            _,truth=make_case(2,seed,kind)
            assert truth['initial_age_s']==age
            assert truth['segments'][0][1]==10-age
            a,b,_=truth['segments'][1];assert b-a==d
            assert all(b>a for a,b,_ in truth['segments'])


def test_no_demand_and_supplied_gap_not_fabricated_from_silence():
    empty,_=make_case(2,7,'no_demand');assert empty['view']['events']==[]
    assert empty['spec']['observation_windows_s']==[[0,34]]
    gap,_=make_case(2,7,'gap')
    assert gap['spec']['observation_windows_s']==[[0,10],[18,34]]
    assert all(not 10000<=r['event']['timestamp_ms']<18000 for r in gap['view']['events'])


def test_worker_separates_inference_and_truth_evaluation():
    from scripts.check_sparse_duration import run
    source=inspect.getsource(run)
    assert 'truth.json' not in source and 'match_boundaries' not in source
