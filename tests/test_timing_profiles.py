import hashlib
import json
from app.core.v10 import timing_profiles
from app.core.v10.estimated_signals import build_estimated_signals
from tests.test_estimated_signals import prediction


def test_source_scoping_does_not_transfer_delays_to_other_day(tmp_path,monkeypatch):
    (tmp_path/'config').mkdir();source=tmp_path/'data.json';source.write_bytes(b'tracks')
    record=dict(model_id='site',source_member='one.json',input_sha256=[hashlib.sha256(b'tracks').hexdigest()],calibration={'approach':'N'})
    (tmp_path/'config/signal_timing_profiles.json').write_text(json.dumps({'profiles':[record]}))
    monkeypatch.setattr(timing_profiles,'ROOT',tmp_path)
    assert timing_profiles.resolve_timing_profile(source,'one.json','site')=={'approach':'N'}
    assert timing_profiles.resolve_timing_profile(source,'other.json','site') is None
    source.write_bytes(b'different day')
    assert timing_profiles.resolve_timing_profile(source,'one.json','site') is None


def test_enthusiasts_exposes_only_confirmed_main_pair_without_inventing_n_s_heads():
    value=prediction();value['schedule']['phase_names']=['x','z'];value['schedule']['phase_count']=2
    value['schedule']['raw_hsmm_segments']=[[0,15,0],[15,30,1]]
    for r in value['schedule']['stream_activity_by_phase']:r['event_probability_by_phase'].pop('y')
    result=build_estimated_signals(value,profile_id='lenina_entuziastov')
    assert result['available'] and set(result['topology'])=={'E','W'}
    assert result['hardware_scope'].startswith('represented_main_pair_only')
    assert all(s['heads']['E']['main']['state']==s['heads']['W']['main']['state'] for s in result['states'])
