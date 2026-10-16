import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.experimental.h1_confirmation import assess_confirmation


def inputs():
    readouts=[dict(file='one',frame_sha256='a',displayed_local_time='27-02-2025 10:05:21',reviewer='test'),
              dict(file='two',frame_sha256='b',displayed_local_time='27-02-2025 10:05:23',reviewer='test')]
    metadata={'frames':[dict(file='one',sha256='a',actual_media_time_s=326.033333),
                        dict(file='two',sha256='b',actual_media_time_s=328.033333)]}
    model=dict(origin_ms=1740632395000,delta_s=1.253838)
    validation={'tracks':[dict(track_id=7,observations=4,new_max_error_px=10,status='PASS_DECLARED_PIXEL_ALLOWANCE')]}
    mapping={'head_id':'H1','mapping_status':'OPERATOR_CONFIRMED_VIDEO_RELATIVE_DIRECTIONS'}
    raw={'7':dict(zone_in='N',zone_out='_S')}
    return readouts,metadata,model,validation,mapping,raw


def test_overlay_relative_time_matches_without_certifying_json_clock():
    out=assess_confirmation(*inputs())
    assert out['overlay_increments']==[dict(media_elapsed_s=2,displayed_elapsed_s=2)]
    assert out['accepted_json_video_clock_transform'] is out['calibrated_sync_uncertainty_ms'] is None
    assert out['observed_display_resolution_s']==1 and out['display_rounding_convention']=='UNKNOWN'
    assert out['fit_calls']==0


def test_local_geometry_pass_not_promoted_to_hardware_or_mapping_certificate():
    out=assess_confirmation(*inputs())
    assert out['local_raw_zone_anchors'][0]['local_pixel_check_status']=='PASS_DECLARED_PIXEL_ALLOWANCE'
    assert out['movement_mapping_proposals']==[dict(section='main',raw_movement='N->_S',verified=False)]
    assert out['physical_section_state']=='UNKNOWN' and out['protected_permissive_semantics']=='UNKNOWN'


def test_model_delta_not_silently_applied_as_accepted_clock_offset():
    values=list(inputs());values[2]['delta_s']=99
    out=assess_confirmation(*values)
    assert out['accepted_json_video_clock_transform'] is None
    assert out['overlay_increments'][0]['displayed_elapsed_s']==2
    assert not out['phase_labels_used'] and not out['release_timestamps_used']


def test_frame_identity_mismatch_and_duplicates_refused():
    values=list(inputs());values[0][0]['frame_sha256']='wrong'
    with pytest.raises(ValueError,match='IDENTITY_MISMATCH'):assess_confirmation(*values)
    values=list(inputs());values[0][1]=copy.deepcopy(values[0][0])
    with pytest.raises(ValueError,match='DUPLICATE_CLOCK_FRAME'):assess_confirmation(*values)


@pytest.mark.parametrize('pts',[float('nan'),True])
def test_invalid_frame_time_refused(pts):
    values=list(inputs());values[1]['frames'][0]['actual_media_time_s']=pts
    with pytest.raises(ValueError,match='INVALID_MEDIA_PTS'):assess_confirmation(*values)


def test_input_snapshots_immutable():
    values=inputs();before=copy.deepcopy(values)
    out=assess_confirmation(*values)
    out['video_relative_H1_mapping']['head_id']='other'
    assert values==before


def test_supplier_warning_kept_separate_from_a_clock_source_certificate():
    excerpt={'top_level_millis':'departure','detection_millis':'detection time','offline_processing_warning':'some records may use non-event wall time'}
    out=assess_confirmation(*inputs(),timestamp_definitions=excerpt)
    assert out['accepted_json_video_clock_transform'] is None
    assert out['json_millis_clock_source']=='AWAITING_SUPPLIER_OR_USER_PROVENANCE'
    out['supplier_timestamp_definition_excerpt']['top_level_millis']='changed'
    assert excerpt['top_level_millis']=='departure'


def test_real_artifact_source_and_output_seals():
    root=Path(__file__).resolve().parents[1];folder=root/'evidence/h1_confirmation_20261016'
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    raw=(folder/'confirmation.json').read_bytes();out=json.loads(raw)
    assert hashlib.sha256(raw).hexdigest()==manifest['confirmation_sha256']
    assert len(out['overlay_readouts'])==3 and len(out['local_raw_zone_anchors'])==4
    assert len(out['movement_mapping_proposals'])==2
    assert not out['production_default_changed']
    assert all(abs(row['nominal_model_json_minus_displayed_second_ms']-1287.171)<.01 for row in out['overlay_readouts'])
    for seal in manifest['source_seals'].values():
        assert hashlib.sha256((root/seal['path']).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==seal['sha256_lf']
