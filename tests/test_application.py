"""Public application entry points and malformed offline uploads."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api import intersection_projects as api
from app.core.intersection_project import run_project
from app.core.v10.estimated_signals import resolve_profile


def test_public_application_exposes_one_workflow():
    with TestClient(app) as client:
        assert client.get('/health').json() == {'status': 'ok'}
        info = client.get('/').json()
        assert info['visualization'] == '/visualization'
        assert info['version'] == '0.14.0'
        page = client.get('/visualization')
        assert page.status_code == 200 and '<iframe' in page.text
        paths = client.get('/openapi.json').json()['paths']
        assert '/api/v1/intersections' in paths
        assert '/api/v1/v9/analyze' not in paths
        assert not any('/annotation' in p or '/learned' in p for p in paths)


@pytest.mark.parametrize('raw', [b'[{},]]', b'[]'])
def test_invalid_offline_upload_retains_input_and_fails_before_fitting(raw, tmp_path, monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('No model fitting for malformed or empty inputs')

    class InlineExecutor:
        def submit(self, worker, source, folder):
            try:
                run_project(source, folder, predictor=forbidden)
            except ValueError:
                pass

    monkeypatch.setattr(api, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(api, '_executor', InlineExecutor())
    with TestClient(app) as client:
        response = client.post('/api/v1/intersections', files={'file': ('raw.json', raw)})
        assert response.status_code == 202
        model_id = response.json()['model_id']
        status = client.get('/api/v1/intersections/' + model_id).json()
        assert status['status'] == 'FAILED'
        assert (tmp_path / model_id / 'input.json').read_bytes() == raw
        assert client.get('/api/v1/intersections/' + model_id + '/model').status_code == 409
    assert not calls


def test_signal_mapping_never_selects_hardware_by_filename():
    for name in ('unknown.json', '17_2025_2_27_10.json', 'lenina_sverdlovsky.zip'):
        assert resolve_profile(name, 'auto') == (None, None)
    with pytest.raises(ValueError, match='named intersection profiles'):
        resolve_profile('record.json', 'lenina_sverdlovsky')
