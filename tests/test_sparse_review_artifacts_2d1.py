import pytest
import json
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'evidence/stage2d1_sparse_review'


def test_failed_gate_prevents_real_replay_and_no_candidate_is_published():
    report=json.loads((ROOT/'comparison.json').read_text())
    assert report['overall_gate']=='FAIL' and report['real_replays']==0
    assert report['candidate_sparse_recovery_gate']=='FAIL'
    assert all(r['published_UNKNOWN_fraction']==1 for r in report['rows'])
    assert any(not r['candidate_recovery_pass'] for r in report['rows'])


def test_saved_predictions_and_adapters_match_hashes_without_new_decoding():
    report=json.loads((ROOT/'comparison.json').read_text())
    for row in report['rows']:
        name=f"{row['case']}_seed{row['seed']}.json"
        pred=ROOT/'synthetic_predictions'/name;adapter=ROOT/'evaluation_adapters'/name
        assert hashlib.sha256(pred.read_bytes()).hexdigest()==row['prediction_sha256']
        assert hashlib.sha256(adapter.read_bytes()).hexdigest()==row['adapter_sha256']
        result=json.loads(pred.read_text())
        assert result['proposed_published_history']['segments']==[]
        assert result['physical_section']['estimated_state']=='UNKNOWN'
        assert result['physical_section']['calibrated_lamp_probability'] is None


pytestmark = pytest.mark.local_evidence
