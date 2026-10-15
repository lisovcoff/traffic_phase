"""Small provenance/precision counterexamples; no real media or decoder."""
import hashlib
import json

from PIL import Image
import pytest

from scripts.build_video_boundary_evidence import build


def fixture(root):
    for name, pts in (('coarse',1),('refined',2),('followup',3)):
        folder = root/name
        folder.mkdir()
        path = folder/'frame.png'
        Image.new('RGB',(180,120)).save(path)
        data = {'source':{'sampled_identity_sha256':'same-sampled-identity'},
                'runtime_s':0,'media_bytes_served':0,
                'frames':[{'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                           'requested_elapsed_s':pts,'actual_media_time_s':pts}]}
        (folder/'frames.json').write_text(json.dumps(data))
    (root/'visual_review.json').write_text(json.dumps({'transitions':[
        {'event':'SYNTHETIC_REVIEW','before':['coarse',1],'after':['refined',2]}],
        'notes':{'test_only':True}}))


def test_video_bracket_never_fabricates_absolute_sync_or_lamp_accuracy(tmp_path):
    fixture(tmp_path)
    out = build(tmp_path)
    assert out['json_video_sync']=='UNVERIFIED'
    assert out['lamp_accuracy_evaluated'] is False
    assert out['transitions'][0]['json_boundary_timestamp_ms'] is None
    assert out['transitions'][0]['physical_switch_timing_error_ms'] is None
    assert out['transitions'][0]['continuous_monitoring'] is False


def test_tampered_frame_rejected(tmp_path):
    fixture(tmp_path)
    (tmp_path/'coarse/frame.png').write_bytes(b'changed')
    with pytest.raises(ValueError,match='FRAME_HASH_MISMATCH'):
        build(tmp_path)


@pytest.mark.parametrize('pts',[1,float('nan')])
def test_duplicate_or_nonfinite_presentation_times_cannot_claim_precision(tmp_path,pts):
    fixture(tmp_path)
    path = tmp_path/'refined/frames.json'
    data = json.loads(path.read_text())
    data['frames'][0]['actual_media_time_s']=pts
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='NONPOSITIVE_PRESENTATION_BRACKET'):
        build(tmp_path)


def test_changed_video_identity_rejected(tmp_path):
    fixture(tmp_path)
    path = tmp_path/'refined/frames.json'
    data = json.loads(path.read_text())
    data['source']['sampled_identity_sha256']='different'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='VIDEO_SAMPLED_IDENTITY_CHANGED'):
        build(tmp_path)
