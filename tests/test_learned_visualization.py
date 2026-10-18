from fastapi.testclient import TestClient
from app.main import app


def test_learned_page_has_three_explicit_calibrated_sites_and_no_auto_k_claim():
    with TestClient(app) as client:
        response=client.get('/visualization/learned')
    assert response.status_code==200
    text=response.text
    assert '/visualization/learned/analyze' in text
    assert 'Число фаз задано обучением' in text
    assert 'chicherina_40let' in text and 'lenina_entuziastov' in text


def test_unknown_model_rejected_before_inference():
    with TestClient(app) as client:
        response=client.post('/visualization/learned/analyze',files={'file':('cars.json',b'[]')},
            data={'intersection_profile':'missing'})
    assert response.status_code==400


def test_learned_upload_passes_model_and_scope_without_any_annotation(monkeypatch,tmp_path):
    import app.api.learned_visualization as api
    calls=[]
    def build(path,**kwargs):
        calls.append(kwargs)
        return {'html':'<html>LEARNED OK</html>','result':{},'physical_plan':{'enabled':False}}
    monkeypatch.setattr(api,'LOG_ROOT',tmp_path)
    monkeypatch.setattr(api,'build_learned_visualization',build)
    monkeypatch.setattr(api,'_write_visualization_logs',lambda **kwargs:None)
    with TestClient(app) as client:
        response=client.post('/visualization/learned/analyze',files={'file':('cars.zip',b'archive')},
            data={'intersection_profile':'chicherina_40let','source_member':'19.json','session_id':'one'})
    assert response.status_code==200 and 'LEARNED OK' in response.text
    assert calls==[{'model_id':'chicherina_40let','source_member':'19.json','session_id':'one'}]
