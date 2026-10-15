from io import BytesIO
import json

import pytest

from app.experimental.temporal_validation_sample import select_review_windows


def record(tid,times):
    return dict(id=tid,zone_in='N',zone_out='_S',millis=999999,
                detections=[dict(millis=t) for t in times])


def run(rows,**kw):
    return select_review_windows(BytesIO(json.dumps(rows).encode()),
        [dict(json_range_ms=[1000,2000]),dict(json_range_ms=[3000,4000])],{1},**kw)


def test_single_pass_disjoint_whole_tracks_and_exclusions():
    rows=[record(1,[1500]),record(2,[500,1500,2500]),record(3,[3500]),record(4,[1500,3500])]
    selected,report=run(rows)
    assert [r['record']['id'] for r in selected]==[2,3]
    assert selected[0]['record']==rows[1]
    assert {e['reason'] for e in report['excluded']}=={'PRIOR_REVIEW_ID','CROSS_WINDOW_TRACK'}
    assert report['complete_entry_scanned']


def test_no_gap_interpolation_or_exit_timestamp_substitution():
    selected,_=run([record(2,[500,2500])])
    assert selected==[]


@pytest.mark.parametrize('kw',[{'max_bytes':10},{'max_output_bytes':10},{'max_tracks':1}])
def test_resource_failure_not_complete_partial_output(kw):
    with pytest.raises(ValueError):
        run([record(2,[1500]),record(3,[3500])],**kw)


def test_id_collision_is_not_hidden():
    with pytest.raises(ValueError,match='DUPLICATE'):
        run([record(2,[1500]),record(2,[3500])])
