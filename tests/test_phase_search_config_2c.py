import pytest
from app.core.v9.fit import PhaseSearchConfig
from app.core.v9 import model


def test_public_records_and_path_forward_explicit_search_config(monkeypatch,tmp_path):
    config=PhaseSearchConfig(kmin=5,kmax=8,max_candidates=2,max_seconds=10.)
    monkeypatch.setattr(model,'extract_timing_streams',lambda tracks:())
    monkeypatch.setattr(model,'load_event_streams',lambda *args,**kwargs:())
    monkeypatch.setattr(model,'_discover_bundle',lambda bundle,**kwargs:kwargs['phase_search_config'])
    assert model.discover_records([{}],phase_search_config=config) is config
    source=tmp_path/'source.json';source.write_text('[]')
    assert model.discover_path(source,phase_search_config=config) is config


def test_empty_search_has_structured_unknown_and_no_fabricated_k(monkeypatch):
    monkeypatch.setattr(model,'infer_period',lambda entries:(20.,{}))
    with pytest.raises(model.PhaseSearchUnavailable) as caught:
        model._discover_from_stream_views({'a':[1.,2.]},{'a':[1.,2.]},{},{},
            release_streams={'a':[1.,2.]},phase_search_config=PhaseSearchConfig(max_candidates=0))
    result=caught.value.to_dict()
    assert result['estimated_state']=='UNKNOWN' and result['phase_count'] is None
    assert result['phase_search']['search_status']=='partial_or_unavailable'
    assert len(result['phase_search']['candidate_ledger'])==5


def test_local_regime_search_retains_budget_ledger_without_fit():
    result=model._regime_phase_structure({'a':[1.,2.]},{'a':[1.,2.]},{'a':[1.,2.]},
        period=20.,window_s=80.,phase_search_config=PhaseSearchConfig(kmin=5,kmax=8,max_candidates=0))
    assert result['phase_count'] is None
    assert [row['k'] for row in result['phase_search']['candidate_ledger']]==[5,6,7,8]
