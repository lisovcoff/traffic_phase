"""The new comparison worker preserves annotation-free canonical inference."""
from pathlib import Path

from scripts import score_contract_review as runner


def test_infer_cannot_access_phase_annotation_and_forwards_unchanged_bundle(monkeypatch,tmp_path):
    from app.core.v9 import model
    monkeypatch.setattr(runner,'ROOT',tmp_path)
    source=tmp_path/'source_v9.json'
    source.write_bytes(b'opaque cache; restoration independently tested')
    bundle=object()
    pred={'input':'source','archive':{'source_files':['source.json']}}
    monkeypatch.setattr(runner,'cached_bundle',lambda p:(pred,bundle))
    seen=[]
    def discovery(value,**kwargs):
        assert value is bundle
        assert kwargs['marks_path'] is None
        assert kwargs['experimental_local_history'] is False
        assert kwargs['evidence_policy']=='permission_per_stream'
        seen.append(kwargs)
        return {'event_extraction':{'temporal_events':[]}}
    monkeypatch.setattr(model,'_discover_bundle',discovery)
    monkeypatch.setattr(Path,'read_text',lambda *a,**k: (_ for _ in ()).throw(AssertionError('ANNOTATIONS_NOT_AVAILABLE_TO_INFER')))
    target=tmp_path/'out.json'
    runner.infer(source,target)
    assert len(seen)==1
    assert target.exists()
