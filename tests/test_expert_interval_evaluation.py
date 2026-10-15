import copy
import pytest

from app.core.expert_interval_evaluation import adapt_review, evaluate_review


def review(rows):
    return {'schema': 'trajectory-review-v1', 'reviewer': 'test',
            'source': {'sha256': 'a'*64, 'timestamp_origin_ms': 0, 'end_timestamp_ms': 200000},
            'display': {'preview_window_ms': [0, 180000]},
            'annotations': [{'id': str(i), 'kind': 'phase_hypothesis', 'label': label,
                'interval_start_ms': a, 'interval_end_ms': b,
                'evidence_source': {'kind': 'trajectory_with_onsite_knowledge'},
                'independently_verified': False, 'interpretation': 'trajectory_based_hypothesis',
                'movement': 'INCIDENTAL_SELECTED_CAR'} for i, (a,b,label) in enumerate(rows)]}


GROUPS = {'one': ['E->W'], 'two': ['N->S']}


def pred(rows):
    return {'schedule_base_timestamp_ms': 0, 'schedule': {'phase_count': 2, 'period_s': 100,
            'raw_hsmm_segments': rows, 'baseline_segments': rows}}


def test_censored_edges_and_internal_return_only():
    original = review([(0,30000,'one'), (30000,80000,'two'), (80000,130000,'one'), (130000,180000,'two')])
    saved = copy.deepcopy(original)
    adapter = adapt_review(original, GROUPS)
    report = evaluate_review(pred([[0,30,0],[30,80,1],[80,130,0],[130,180,1],[180,200,0]]), adapter)
    h = report['histories']['raw_hsmm_segments']
    assert (h['matched'], h['truth'], h['predicted']) == (3,3,3)
    assert report['period_absolute_error_s']['recurrence_s'] == [100]
    assert report['period_absolute_error_s']['value'] == 0
    assert report['physical_lamp_accuracy']['value'] is None
    assert original == saved


def test_overlap_retained_with_fixed_midpoint_not_signal_interval():
    adapter = adapt_review(review([(0,30115,'one'), (30000,180000,'two')]), GROUPS)
    b = adapter['boundary_hypotheses'][0]
    assert b['endpoint_interval_ms'] == [30000,30115]
    assert b['point_diagnostic_ms'] == 30057
    assert adapter['operator_error_claim_ms'] == 2000


def test_gap_is_unscored_and_does_not_manufacture_switch():
    adapter = adapt_review(review([(10000,30000,'one'), (50000,180000,'two')]), GROUPS)
    assert len(adapter['blocks']) == 2
    assert adapter['boundary_hypotheses'] == []
    h = evaluate_review(pred([[0,40,0],[40,200,1]]),adapter)['histories']['raw_hsmm_segments']
    assert h['truth'] == h['predicted'] == 0
    assert h['recall']['value'] is None
    assert h['temporal_coverage']['labelled_s'] == 150


def test_same_group_continuation_not_a_switch_or_period_return():
    a = adapt_review(review([(0,30000,'one'), (30000,180000,'one')]),GROUPS)
    r = evaluate_review(pred([[0,200,0]]),a)
    assert not a['boundary_hypotheses']
    assert r['period_absolute_error_s']['n_observations'] == 0


@pytest.mark.parametrize('rows', [
    [(30000,180000,'one'), (0,30000,'two')],
    [(0,100000,'one'), (30000,90000,'two')],
    [(0,100000,'one'), (20000,120000,'two'), (50000,180000,'one')],
    [(0,30000,'one'), (30000,30000,'two')],
])
def test_invalid_interval_layout_rejected(rows):
    with pytest.raises(ValueError): adapt_review(review(rows),GROUPS)


def test_arbitrary_group_and_movement_renaming_preserves_metrics():
    a = review([(0,30000,'one'), (30000,180000,'two')])
    b = copy.deepcopy(a)
    for m in b['annotations']: m['label'] = {'one':'x','two':'y'}[m['label']]
    p = pred([[0,31,0],[31,200,1]])
    ra = evaluate_review(p,adapt_review(a,GROUPS))
    rb = evaluate_review(p,adapt_review(b,{'x':['arbitrary'],'y':['another']}))
    for field in ra['histories']:
        assert ra['histories'][field]['recall'] == rb['histories'][field]['recall']
    assert ra['phase_count'] == rb['phase_count']


def test_missing_prediction_and_history_gaps_explicit():
    a = adapt_review(review([(0,30000,'one'), (30000,180000,'two')]),GROUPS)
    missing = evaluate_review({},a)
    assert missing['histories']['raw_hsmm_segments']['recall']['reason'] == 'missing_schedule_time_anchor'
    r = evaluate_review(pred([[0,20,0],[40,180,1]]),a)
    assert r['histories']['raw_hsmm_segments']['predicted'] == 0
    assert r['histories']['raw_hsmm_segments']['temporal_coverage']['value'] == pytest.approx(160/180)


def test_unmapped_label_not_inferred_from_selected_track():
    with pytest.raises(ValueError, match='group definition'):
        adapt_review(review([(0,180000,'unknown')]),GROUPS)


def test_worker_command_cannot_receive_review_or_mapping(tmp_path):
    from scripts.expert_review_benchmark import worker_command
    cmd = worker_command(tmp_path/'17_2025_2_12_7.json',tmp_path/'prediction.json')
    assert cmd[-2:] == ['--dt','1.0']
    assert not any('review' in x or 'marks' in x or 'mapping' in x for x in cmd[3:])
    with pytest.raises(ValueError): worker_command(tmp_path/'17_2025_2_12_7_review.json',tmp_path/'p.json')


def test_all_predictions_sealed_before_scoring_and_no_rerun(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    from scripts import expert_review_benchmark as runner
    data, output = tmp_path/'data',tmp_path/'out'
    data.mkdir()
    for name,groups in runner.GROUPS.items():
        source = data/name
        source.write_text('[]')
        labels = list(groups)
        r = review([(0,30000,labels[0]),(30000,180000,labels[1])])
        r['source']['sha256'] = runner.sha256_file(source)
        (data/(source.stem+'_review.json')).write_text(json.dumps(r),encoding='utf-8')
    monkeypatch.setattr(runner,'code_manifest',lambda:{'file_hashes':{}})
    runner.prepare(data,output)
    calls=[]
    def fake_infer(command,**kwargs):
        calls.append(command)
        assert command[-2:] == ['--dt','1.0']
        runner.write_json(__import__('pathlib').Path(command[-3]),pred([[0,30,0],[30,200,1]]))
        return SimpleNamespace(returncode=0,stdout=b'',stderr=b'')
    original_eval=runner.evaluate_review
    def check_seal(p,a):
        assert len(calls)==3
        assert (output/'predictions_seal.json').exists()
        return original_eval(p,a)
    monkeypatch.setattr(runner.subprocess,'run',fake_infer)
    monkeypatch.setattr(runner,'evaluate_review',check_seal)
    runner.run(output)
    assert (output/'comparison.json').exists()
    with pytest.raises(FileExistsError): runner.run(output)
    assert len(calls)==3
