import json
from copy import deepcopy

import pytest

from app.core.intersection_project import digest,model_fingerprint,write_json,read_model
from scripts.enrich_intersection_model import enrich
from tests.test_intersection_online import model
from tests.test_intersection_queue_observations import offline_tracks


def saved_project(tmp_path):
    folder=tmp_path/'original';folder.mkdir()
    source=folder/'input.json';source.write_text(json.dumps(offline_tracks()),encoding='utf8')
    fit=folder/'sessions'/'one.json.gz';fit.parent.mkdir();fit.write_bytes(b'preserved fit')
    m=model();m.update(input_path_private=str(source.resolve()),
        input=dict(sha256=digest(source),source_count=1),
        source_inventory=[dict(source_member='input.json',status='READY')],
        sessions=[dict(prediction='sessions/one.json.gz',prediction_sha256=digest(fit))])
    m['fingerprint']=model_fingerprint(m)
    write_json(folder/'model.json',m);write_json(folder/'status.json',dict(status='READY'))
    return folder,m


def test_bounded_offline_upgrade_preserves_original_model_fits_and_source(tmp_path):
    folder,m=saved_project(tmp_path);original=deepcopy(m)
    receipt=enrich(folder,tmp_path/'fork',max_tracks=20)
    fork=read_model(tmp_path/'fork')
    assert receipt['original_model_preserved'] and receipt['offline_tracks']==20
    assert fork['regimes']==m['regimes'] and read_model(folder)==original
    assert fork['queue_observations']['references']['N']
    assert not fork['queue_observations']['training']['online_recording_used']
    assert digest(tmp_path/'fork/input.json')==m['input']['sha256']
    assert digest(tmp_path/'fork/sessions/one.json.gz')==m['sessions'][0]['prediction_sha256']
    with pytest.raises(FileExistsError):enrich(folder,tmp_path/'fork')


def test_upgrade_refuses_changed_training_input(tmp_path):
    folder,m=saved_project(tmp_path)
    (folder/'input.json').write_text('[]',encoding='utf8')
    with pytest.raises(ValueError,match='source hash'):enrich(folder,tmp_path/'fork')
    assert not (tmp_path/'fork').exists()


def test_original_single_argument_api_is_preserved(monkeypatch,tmp_path):
    import scripts.enrich_intersection_model as module
    expected=({'model_id':'legacy'},tmp_path/'legacy')
    monkeypatch.setattr(module,'enrich_saved_fits',lambda path:expected)
    assert enrich(tmp_path/'original')==expected
