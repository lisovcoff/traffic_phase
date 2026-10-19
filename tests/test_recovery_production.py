"""Production input isolation, default selection and frozen-core integration."""
import builtins
from copy import deepcopy
import io
import json
from pathlib import Path
import zipfile

import pytest

from app.core.recovery import engine
from app.core.v9.events import load_event_streams
from app.core.v9.source_scope import ScopeChoiceRequired
from scripts.realistic_traffic_benchmark import generate


def test_prediction_is_filename_truth_field_and_video_independent(monkeypatch):
    from app.core.v9 import model
    environment = dict(vehicle_classes={'car':100}, positive_raw_speed_quantiles=[20.,30.,40.,50.],
                       detection_step_quantiles_s=[.11,.12,.13])
    tracks, _ = generate(dict(id='independence', k=2, duration_s=600, period_s=80,
                             arrival_rate_s=.1, seed=918721, all_red_s=1.), environment)
    before = (model.discover_phase_count, model.infer_period, model._local_regime_selection)
    original_builtin, original_io = builtins.open, io.open
    denied = []

    def guard(original):
        def opened(file, *args, **kwargs):
            name = str(file).replace('\\', '/').lower()
            if (name.endswith(('.mp4', '.avi', '.mov')) or '/evidence/' in name or
                '/annotations/' in name or 'manual_marks' in name or 'truth.json' in name or
                'learned_phase_profiles' in name or 'reference_video_timing' in name):
                denied.append(name)
                raise AssertionError('non-trajectory prediction input: '+name)
            return original(file, *args, **kwargs)
        return opened
    monkeypatch.setattr(builtins, 'open', guard(original_builtin))
    monkeypatch.setattr(io, 'open', guard(original_io))
    first = engine.discover_bundle(load_event_streams(Path('records'), _records=tracks), input_name='unknown.json')
    altered = deepcopy(tracks)
    for track in altered:
        track['ground_truth'] = {'phase':999, 'green':False}
    second = engine.discover_bundle(load_event_streams(Path('records'), _records=altered),
                                    input_name='17_2025_2_27_10.json')
    assert first['schedule'] == second['schedule']
    assert first['physical_signal_plan'] == second['physical_signal_plan']
    assert first['recovery_model']['version'] == engine.VERSION
    assert first['recovery_model']['video_used'] is False
    assert not denied
    assert before == (model.discover_phase_count, model.infer_period, model._local_regime_selection)


def test_recovery_zip_requires_source_before_reading_trajectories(monkeypatch, tmp_path):
    path = tmp_path/'two.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('a.json', '[]'); archive.writestr('b.json', '[]')
    monkeypatch.setattr('app.core.v9.events.load_event_streams',
                        lambda *a, **kw: pytest.fail('must choose source before extracting'))
    with pytest.raises(ScopeChoiceRequired) as error:
        engine.discover_path(path)
    assert error.value.kind == 'source'


def test_recovery_scopes_one_session_before_fitting(monkeypatch, tmp_path):
    from tests.test_v9_source_scope import track
    path = tmp_path/'two_sessions.json'
    path.write_text(json.dumps([track(), track(2, start=86401000, origin='E', target='_W')]))
    calls = []

    def fit(bundle, **kwargs):
        calls.append(bundle)
        return {'regime_detection':{'method':'global_fallback'}}
    monkeypatch.setattr(engine, 'discover_bundle', fit)
    with pytest.raises(ScopeChoiceRequired) as error:
        engine.discover_path(path)
    assert error.value.kind == 'session' and not calls
    chosen = error.value.choices[0]
    result = engine.discover_path(path, session_id=chosen['session_id'])
    assert len(calls) == 1 and calls[0][8] == 1
    assert result['input_scope']['selected_session'] == chosen
    assert result['input_scope']['other_sessions_analysed'] is False


def test_spatial_builder_selects_recovery_backend(monkeypatch, tmp_path):
    from scripts.v9_spatial_visualizer import build_spatial_visualization
    class Selected(Exception):
        pass

    def chosen(path, **kwargs):
        assert kwargs == {'dt':1., 'source_member':'a.json', 'session_id':'selected'}
        raise Selected
    monkeypatch.setattr(engine, 'discover_path', chosen)
    with pytest.raises(Selected):
        build_spatial_visualization(tmp_path/'source.zip', algorithm_version=engine.VERSION,
                                    source_member='a.json', session_id='selected')
    with pytest.raises(ValueError, match='algorithm_version'):
        build_spatial_visualization(tmp_path/'source.zip', algorithm_version='typo')


def test_recovery_batch_uses_motion_extractor_and_separate_session_fits(monkeypatch, tmp_path):
    from app.core import archive_batch as batch
    from tests.test_archive_batch import request
    from tests.test_web_archive_contract import model as prediction
    req = request(tmp_path); req['algorithm_version'] = engine.VERSION
    calls = []

    def fit(bundle, **kwargs):
        calls.append(bundle)
        assert bundle[8] == 1
        return prediction()
    monkeypatch.setattr(engine, 'discover_bundle', fit)
    batch.run_source_worker(req)
    state = json.loads((Path(req['output'])/'checkpoint.json').read_text())
    assert len(calls) == 2
    assert [r['status'] for r in state['jobs']] == ['ESTIMATED', 'ESTIMATED']
