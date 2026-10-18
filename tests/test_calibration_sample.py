from io import BytesIO
import copy
import hashlib
import json
import pytest

from app.core.calibration_sample import select_raw_window


def run(rows,**kw):
    raw=json.dumps(rows).encode();chosen,report=select_raw_window(BytesIO(raw),10000,20000,**kw)
    return chosen,report,raw


def track(id,times):return {'id':id,'millis':999999,'speed':44,'detections':[{'millis':t,'centroid_x':.1,'centroid_y':.2} for t in times]}


def test_unsorted_records_whole_tracks_absolute_time_and_hash():
    rows=[track(1,[30000,31000]),track(2,[9000,10000,19000,21000]),track(3,[11000])]
    before=copy.deepcopy(rows);chosen,r,raw=run(rows)
    assert [t['id'] for t in chosen]==[2,3]
    assert chosen[0]==rows[1] and rows==before
    assert r['complete_entry_sha256']==hashlib.sha256(raw).hexdigest()
    assert r['lineage'][0]['source_record_index']==1
    assert r['recommended_preview_start_s']==1
    assert r['recommended_preview_duration_s']==10
    assert r['geometry'].startswith('UNKNOWN')


def test_no_interpolation_through_gap_and_no_top_level_millis_as_entry():
    chosen,_,_=run([track(1,[9000,21000]),track(2,[10000,20000])])
    assert [t['id'] for t in chosen]==[2]
    assert chosen[0]['millis']==999999


@pytest.mark.parametrize('kw',[{'max_input_bytes':5},{'max_output_bytes':5},{'max_tracks':1},{'max_seconds':1e-12}])
def test_budget_exhaustion_never_returns_complete_partial_sample(kw):
    with pytest.raises(ValueError):run([track(1,[11000]),track(2,[12000])],**kw)


def test_no_records_in_window_and_malformed_timestamps():
    with pytest.raises(ValueError,match='NO_TRACKS'):run([track(1,[True,float('nan'),20000])])


def test_duplicate_ids_preserved_for_explicit_review_not_silently_collapsed():
    chosen,r,_=run([track(1,[11000]),track(1,[15000])])
    assert len(chosen)==2
    assert r['lineage'][0]['canonical_raw_record_sha256']!=r['lineage'][1]['canonical_raw_record_sha256']


def test_reader_refuses_io_at_exact_deadline(monkeypatch):
    from app.core import calibration_sample as module
    monkeypatch.setattr(module.time, 'perf_counter', lambda: 100.)
    stream = BytesIO(b'[]')
    reader = module.BudgetReader(stream, max_bytes=100, deadline=100.)
    with pytest.raises(ValueError, match='INPUT_TIME_BUDGET_EXCEEDED'):
        reader.read(10)
    assert stream.tell() == 0


def test_complete_scan_at_exact_deadline_does_not_publish_sample(monkeypatch):
    from app.core import calibration_sample as module
    clock = [0.]
    monkeypatch.setattr(module.time, 'perf_counter', lambda: clock[0])
    class FinishAtDeadline(BytesIO):
        def read(self, size):
            data = super().read(size)
            if not data:
                clock[0] = 1.
            return data
    stream = FinishAtDeadline(json.dumps([track(1, [11000])]).encode())
    with pytest.raises(ValueError, match='INPUT_TIME_BUDGET_EXCEEDED'):
        module.select_raw_window(stream, 10000, 20000, max_seconds=1.)
