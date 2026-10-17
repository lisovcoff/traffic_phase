import pytest
from scripts.video_signal_brackets import presentation_bracket,extract_window


def test_pts_granularity_is_not_switch_accuracy_and_does_not_invert_other_phase():
    out=presentation_bracket({'pts_ticks':9000,'file':'old.png'},{'pts_ticks':12000,'file':'new.png'})
    assert out['video_presentation_bracket_s']==pytest.approx([.1,.1333333333333])
    assert out['width_ms']==pytest.approx(1000/30)
    assert out['json_boundary_timestamp_ms'] is None
    assert out['physical_switch_timing_error_ms'] is None
    assert out['second_phase_state']=='UNKNOWN' and out['calibrated_probability'] is None


@pytest.mark.parametrize('a,b',[(0,0),(2,1),(-1,1),(True,2),(0,1.5)])
def test_invalid_or_duplicate_pts_rejected(a,b):
    with pytest.raises(ValueError):presentation_bracket({'pts_ticks':a,'file':'a'},{'pts_ticks':b,'file':'b'})


def test_missing_frames_produce_wider_bracket_not_millisecond_precision():
    assert presentation_bracket({'pts_ticks':0,'file':'a'},{'pts_ticks':9000,'file':'b'})['width_ms']==100.


@pytest.mark.parametrize('start,end,limit',[(0,3,60),(-1,1,60),(1,1,60),(0,1,61)])
def test_budget_rejected_before_video_access(tmp_path,start,end,limit):
    with pytest.raises(ValueError):extract_window(tmp_path/'absent.mp4',tmp_path/'out',start,end,limit)
    assert not (tmp_path/'out').exists()


def test_incompatible_time_base_is_rejected_before_frame_extraction(monkeypatch,tmp_path):
    from types import SimpleNamespace
    from scripts import video_signal_brackets as tool
    calls=[]
    def probe(cmd,**kwargs):
        calls.append(cmd[0])
        return SimpleNamespace(stdout=b'{"streams":[{"width":2688,"height":1520,"time_base":"1/1000"}]}')
    monkeypatch.setattr(tool.subprocess,'run',probe)
    with pytest.raises(ValueError,match='time base'):
        extract_window(tmp_path/'input.mp4',tmp_path/'out',0,1)
    assert calls==['ffprobe'] and not (tmp_path/'out').exists()
