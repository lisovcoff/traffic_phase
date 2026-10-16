from io import BytesIO
import json
from pathlib import Path
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.core.temporal_evidence import EvidenceUnavailable
from app.core.v9 import model
from app.core.v9.events import load_event_streams, load_tracks
from app.core.v9.source_scope import ScopeChoiceRequired, choose_source, choose_session, input_sessions
from app.main import app


def track(ident=1, start=1000, origin='N', target='_S'):
    return dict(id=ident, zone_in=origin, zone_out=target, stay_duration_millis=0,
                detections=[dict(millis=start, zone=origin), dict(millis=start+2000, zone=target)])


def write_json(path, rows):
    path.write_text(json.dumps(rows), encoding='utf-8')
    return path


def zip_bytes(members):
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, rows in members:
            archive.writestr(name, json.dumps(rows))
    return stream.getvalue()


def test_multi_source_zip_inventory_does_not_open_members_or_fit(monkeypatch, tmp_path):
    path = tmp_path/'two.zip'
    path.write_bytes(zip_bytes([('a.json', [track()]), ('b.json', [track(origin='E', target='_W')])]))
    monkeypatch.setattr(zipfile.ZipFile, 'open', lambda *a, **kw: pytest.fail('inventory must not decompress'))
    monkeypatch.setattr(model, 'load_event_streams', lambda *a, **kw: pytest.fail('no ingestion before choice'))
    with pytest.raises(ScopeChoiceRequired) as caught:
        model.discover_path(path)
    out = caught.value.to_dict()
    assert out['reason_code'] == 'SOURCE_SELECTION_REQUIRED'
    assert [r['source_member'] for r in out['choices']] == ['a.json', 'b.json']
    assert out['phase_count'] is None and out['state'] == 'UNKNOWN' and not out['fitting_performed']


@pytest.mark.parametrize('member', ['a.json', 'b.json'])
def test_source_choice_keeps_same_track_ids_and_times_in_separate_namespaces(member, monkeypatch, tmp_path):
    path = tmp_path/'two.zip'
    path.write_bytes(zip_bytes([('a.json', [track()]), ('b.json', [track(origin='E', target='_W')])]))
    calls = []

    def accept(bundle, **kwargs):
        calls.append(bundle)
        return {'test_only': True}

    monkeypatch.setattr(model, '_discover_bundle', accept)
    result = model.discover_path(path, source_member=member)
    assert result['input_scope']['source_member'] == member
    assert {e.provenance['source'] for e in calls[0].temporal_events} == {member}
    assert {e.movement for e in calls[0].temporal_events} == ({'N->S'} if member == 'a.json' else {'E->W'})
    assert len(load_tracks(path, source_member=member)) == 1


def test_sessions_are_partitioned_before_selection_and_model_building(monkeypatch, tmp_path):
    path = write_json(tmp_path/'raw.json', [track(2, 86401000), track(1, 1000)])
    monkeypatch.setattr(model, '_discover_bundle', lambda *a, **kw: pytest.fail('choice must precede fitting'))
    with pytest.raises(ScopeChoiceRequired) as caught:
        model.discover_path(path)
    choices = caught.value.to_dict()['choices']
    assert [c['observation_start_ms'] for c in choices] == [1000, 86401000]
    assert all(c['track_count'] == 1 for c in choices)
    captured = []
    monkeypatch.setattr(model, '_discover_bundle', lambda bundle, **kw: captured.append(bundle) or {})
    result = model.discover_path(path, session_id=choices[1]['session_id'])
    assert {e.source_track_id for e in captured[0].temporal_events} == {2}
    assert captured[0][6] == captured[0][7] == 86401000
    assert result['input_scope']['other_sessions_analysed'] is False


def test_in_memory_entry_point_cannot_bypass_session_boundary(monkeypatch):
    monkeypatch.setattr(model, '_discover_bundle', lambda *a, **kw: pytest.fail('must choose session'))
    with pytest.raises(ScopeChoiceRequired) as caught:
        model.discover_records([track(1), track(2, 86401000)])
    assert caught.value.to_dict()['reason_code'] == 'SESSION_SELECTION_REQUIRED'
    selected = caught.value.choices[1]['session_id']
    seen = []
    monkeypatch.setattr(model, '_discover_bundle', lambda bundle, **kw: seen.append(bundle) or {})
    result = model.discover_records([track(1), track(2, 86401000)], session_id=selected)
    assert {e.source_track_id for e in seen[0].temporal_events} == {2}
    assert result['input_scope']['source_member'] == 'records'


def test_gap_rule_reuses_existing_default_and_does_not_split_at_exact_threshold(tmp_path):
    from app.core.reconstruction import DEFAULT_SESSION_GAP_SECONDS
    gap = int(DEFAULT_SESSION_GAP_SECONDS*1000)
    path = write_json(tmp_path/'raw.json', [track(1), track(2, 3000+gap)])
    assert len(input_sessions(load_event_streams(path), 'raw.json')) == 1
    write_json(path, [track(1), track(2, 3001+gap)])
    assert len(input_sessions(load_event_streams(path), 'raw.json')) == 2


def test_single_session_uses_original_bundle_identity_and_selection(tmp_path):
    path = write_json(tmp_path/'raw.json', [track(1), track(2, 5000)])
    bundle = load_event_streams(path)
    scoped, selected, choices = choose_session(bundle, 'raw.json')
    assert scoped is bundle
    assert selected == choices[0]


def test_session_selection_is_independent_of_record_order(tmp_path):
    path = write_json(tmp_path/'raw.json', [track(1), track(2, 86401000)])
    before = [s.metadata for s in input_sessions(load_event_streams(path), 'raw.json')]
    write_json(path, [track(2, 86401000), track(1)])
    assert [s.metadata for s in input_sessions(load_event_streams(path), 'raw.json')] == before


def test_legacy_comparison_cannot_silently_ignore_requested_scope(tmp_path):
    path = write_json(tmp_path/'raw.json', [track()])
    with pytest.raises(ValueError, match='legacy_v9'):
        load_event_streams(path, evidence_policy='legacy_v9', source_member='raw.json')


def test_product_and_offline_payload_retain_scope_without_mutating_source():
    from app.core.offline_product_report import build_report_payload
    from app.core.product_result import build_product_result
    from tests.test_web_archive_contract import model as fixture_model
    source = fixture_model()
    source['input_scope'] = dict(status='SELECTED_SESSION_ONLY', source_member='test.json')
    product = build_product_result(source)
    assert build_report_payload(source)['input_scope'] == source['input_scope']
    product['input_scope']['source_member'] = 'other'
    assert source['input_scope']['source_member'] == 'test.json'


def test_track_with_large_internal_observation_gap_does_not_bridge_sessions(tmp_path):
    row = track(); row['detections'][-1]['millis'] += 86400000
    bundle = load_event_streams(write_json(tmp_path/'raw.json', [row]))
    with pytest.raises(EvidenceUnavailable) as caught:
        input_sessions(bundle, 'raw.json')
    assert caught.value.reason_code == 'AMBIGUOUS_TRACK_SESSION_GAP'


def test_mixed_source_bundle_cannot_be_relabelled_as_one_camera(tmp_path):
    path = write_json(tmp_path/'raw.json', [track()])
    with pytest.raises(EvidenceUnavailable) as caught:
        input_sessions(load_event_streams(path), 'other.json')
    assert caught.value.reason_code == 'MIXED_SOURCE_EVENT_BUNDLE'


@pytest.mark.parametrize('names', [('a.json', 'A.json'), ('../bad.json',), ('C:/bad.json',)])
def test_duplicate_or_unsafe_member_names_are_rejected(names, tmp_path):
    path = tmp_path/'bad.zip'; path.write_bytes(zip_bytes([(name, []) for name in names]))
    with pytest.raises(ValueError):
        choose_source(path)


def test_invalid_choice_and_explicit_byte_budget_fail_before_fitting(tmp_path):
    path = write_json(tmp_path/'raw.json', [track()])
    with pytest.raises(ValueError, match='unknown source_member'):
        choose_source(path, 'other.json')
    with pytest.raises(EvidenceUnavailable) as caught:
        choose_source(path, max_bytes=1)
    assert caught.value.reason_code == 'SOURCE_BYTE_BUDGET'
    with pytest.raises(ValueError, match='session_id'):
        choose_session(load_event_streams(path), 'raw.json', 'stale-session')


@pytest.mark.parametrize('endpoint', ['/api/v1/v9/analyze', '/visualization/analyze'])
def test_http_source_then_session_choices_do_not_fit_or_unpack_unselected_member(endpoint, monkeypatch):
    monkeypatch.setattr(model, '_discover_bundle', lambda *a, **kw: pytest.fail('inventory must not fit'))
    data = zip_bytes([('a.json', [track(1), track(2, 86401000)]), ('unselected.json', {'not': 'trajectories'})])
    with TestClient(app) as client:
        first = client.post(endpoint, files={'file': ('two.zip', data)})
        assert first.status_code == 409
        assert first.json()['detail']['choice_kind'] == 'source'
        second = client.post(endpoint, files={'file': ('two.zip', data)}, data={'source_member': 'a.json'})
        assert second.status_code == 409
        assert second.json()['detail']['choice_kind'] == 'session'
        assert len(second.json()['detail']['choices']) == 2


def test_spatial_render_scope_limits_tracks_and_escapes_member(monkeypatch, tmp_path):
    import scripts.v9_spatial_visualizer as spatial
    from tests.test_web_archive_contract import model as fixture_model
    result = fixture_model()
    result['input_scope'] = dict(status='SELECTED_SESSION_ONLY', source_member='<camera>.json',
                                source_session_count=2, selected_session=dict(session_number=2,
                                observation_start_ms=1000, observation_end_ms=3000))
    seen = []
    monkeypatch.setattr(spatial, 'discover_path', lambda *a, **kw: result)
    monkeypatch.setattr(spatial, 'load_tracks', lambda *a, **kw: seen.append(kw) or [])
    monkeypatch.setattr(spatial, 'build_spatial_projection', lambda *a, **kw: {})
    monkeypatch.setattr(spatial, 'compact_trajectories', lambda *a, **kw: [])
    out = spatial.build_spatial_visualization(tmp_path/'raw.zip', source_member='<camera>.json', session_id='chosen')
    assert seen == [dict(source_member='<camera>.json', start_timestamp_ms=1000, end_timestamp_ms=3000)]
    assert '&lt;camera&gt;.json' in out['html']
    assert 'id=\'input-scope\'' in out['html']
