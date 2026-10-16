from io import BytesIO
import json
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.core.preprocessing import iter_trajectory_payload_stream
from app.core.v9.events import _iter_json_records, _iter_source_records
from app.core.v9 import model
from app.main import app


READERS = [_iter_json_records, iter_trajectory_payload_stream]


@pytest.mark.parametrize('reader', READERS)
@pytest.mark.parametrize('chunk_size', [1, 2, 7, 65536])
@pytest.mark.parametrize('payload', ['[]', ' [ ] \r\n', '[{}]', '[{}, {}]',
                                    '[{"note":"\u041f\u0440\u0438\u0432\u0435\u0442 , ] \\\""}]'])
def test_valid_arrays_and_split_utf8_are_accepted(reader, chunk_size, payload):
    expected = json.loads(payload)
    actual = list(reader(BytesIO(payload.encode()), chunk_size=chunk_size))
    if reader is _iter_json_records:
        assert actual == expected
    else:
        assert actual == []  # these grammar fixtures are not car trajectories


@pytest.mark.parametrize('reader', READERS)
@pytest.mark.parametrize('chunk_size', [1, 2, 7, 65536])
@pytest.mark.parametrize('payload', ['[{},]]', '[],{}]', '[{},]', '[]]',
                                    '[] []', '[{}]suffix', '[', '[{}', '[,{}]'])
def test_malformed_complete_document_is_rejected(reader, chunk_size, payload):
    with pytest.raises(ValueError):
        json.loads(payload)
    with pytest.raises(ValueError, match='trajectory JSON|Trajectory JSON'):
        list(reader(BytesIO(payload.encode()), chunk_size=chunk_size))


@pytest.mark.parametrize('reader', READERS)
def test_valid_json_object_is_rejected_by_the_array_root_contract(reader):
    assert json.loads('{}') == {}
    with pytest.raises(ValueError, match='root must be a list'):
        list(reader(BytesIO(b'{}')))


@pytest.mark.parametrize('reader', READERS)
@pytest.mark.parametrize('trailer', [b'', b'[{}]'])
def test_long_whitespace_tail_is_consumed_and_later_garbage_is_rejected(reader, trailer):
    stream = BytesIO(b'[]' + b' '*131072 + trailer)
    if trailer:
        with pytest.raises(ValueError, match='unexpected data'):
            list(reader(stream, chunk_size=64))
    else:
        assert list(reader(stream, chunk_size=64)) == []
    assert stream.tell() == len(stream.getvalue())


@pytest.mark.parametrize('reader', READERS)
@pytest.mark.parametrize('chunk_size', [1, 65536])
def test_object_limit_applies_even_if_value_completes_in_one_read(reader, chunk_size):
    payload = json.dumps([{'text': 'x'*100}]).encode()
    with pytest.raises(ValueError, match='bounded streaming size'):
        list(reader(BytesIO(payload), chunk_size=chunk_size, max_object_chars=32))


@pytest.mark.parametrize('reader', READERS)
@pytest.mark.parametrize('keyword', ['chunk_size', 'max_object_chars'])
def test_zero_resource_limit_is_explicit(reader, keyword):
    with pytest.raises(ValueError, match='positive'):
        list(reader(BytesIO(b'[]'), **{keyword: 0}))


@pytest.mark.parametrize('suffix', ['.json', '.zip'])
def test_source_reader_rejects_extra_closing_bracket(suffix, tmp_path):
    path = tmp_path / ('raw'+suffix)
    if suffix == '.json':
        path.write_bytes(b'[{},]]')
    else:
        with ZipFile(path, 'w') as archive:
            archive.writestr('nested/raw.json', b'[{},]]')
    with pytest.raises(ValueError, match='trajectory JSON'):
        for _, records in _iter_source_records(path):
            list(records)


@pytest.mark.parametrize('endpoint', ['/api/v1/v9/analyze', '/visualization/analyze'])
@pytest.mark.parametrize('suffix', ['.json', '.zip'])
def test_http_rejects_malformed_input_before_model_or_html(endpoint, suffix, monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('model must not start on malformed input')

    monkeypatch.setattr(model, '_discover_bundle', forbidden)
    # A valid source record prefix ensures the old bug can reach model building.
    record = dict(id=1, zone_in='N', zone_out='_S', stay_duration_millis=0,
                  detections=[dict(millis=1000, zone='N'), dict(millis=2000, zone='_S')])
    raw = b'[],' + json.dumps(record).encode() + b']'
    if suffix == '.zip':
        buffer = BytesIO()
        with ZipFile(buffer, 'w') as archive:
            archive.writestr('raw.json', raw)
        raw = buffer.getvalue()
    with TestClient(app) as client:
        response = client.post(endpoint, files={'file': ('raw'+suffix, raw)}, data={'dt': '1'})
    assert response.status_code == 422
    assert 'unexpected data after trajectory JSON array' in response.json()['detail']
    assert not calls


def test_canonical_ingestion_closes_source_even_if_extractor_raises(monkeypatch, tmp_path):
    from app.core.v9 import events, vehicle_evidence
    closed = []

    def sources(_):
        try:
            yield 'record.json', iter([{}])
        finally:
            closed.append(True)

    def fail(*args, **kwargs):
        raise ValueError('extractor rejected track')

    monkeypatch.setattr(events, '_iter_source_records', sources)
    monkeypatch.setattr(vehicle_evidence, 'extract_vehicle_evidence', fail)
    with pytest.raises(ValueError, match='extractor rejected'):
        events.load_event_streams(tmp_path)
    assert closed == [True]


@pytest.mark.parametrize('endpoint', ['/api/v1/v9/analyze', '/visualization/analyze'])
def test_http_empty_array_is_unknown_evidence_not_broken_json(endpoint, monkeypatch):
    monkeypatch.setattr(model, '_discover_bundle', lambda *a, **kw: pytest.fail('no evidence must not fit'))
    with TestClient(app) as client:
        response = client.post(endpoint, files={'file': ('empty.json', b'[]')}, data={'dt': '1'})
    assert response.status_code == 422
    assert 'evidence is UNKNOWN' in response.json()['detail']
    assert 'unterminated' not in response.json()['detail']
    assert 'phase_count' not in response.json()
