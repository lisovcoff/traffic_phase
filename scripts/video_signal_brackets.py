"""Bounded native-frame evidence. No phase fitting, clock alignment or lamp inference."""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import subprocess


def presentation_bracket(before, after, *, time_base='1/90000'):
    """Bracket a reviewed IMAGE appearance, never calibrated physical switch time."""
    a,b=before['pts_ticks'],after['pts_ticks']
    if any(isinstance(v,bool) or not isinstance(v,int) for v in (a,b)) or a<0 or b<=a:
        raise ValueError('strictly increasing integer PTS required')
    base=Fraction(time_base)
    if base<=0:raise ValueError('positive time base required')
    return dict(video_presentation_bracket_s=[float(a*base),float(b*base)],
        width_ms=float((b-a)*base*1000),before_file=before['file'],after_file=after['file'],
        bracket_semantics='reviewed_decoded_appearance_NOT_calibrated_lamp_switch_interval',
        json_boundary_timestamp_ms=None,physical_switch_timing_error_ms=None,
        second_phase_state='UNKNOWN',calibrated_probability=None)


def extract_window(video,out,start,end,max_frames=60):
    if not 0<=start<end or end-start>2 or not 1<=max_frames<=60:
        raise ValueError('at most2s/60 frames per window')
    # This pilot's fixed ROI/time base must not silently label another source
    # using incompatible geometry or timestamp units.
    probe=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries',
        'stream=width,height,time_base','-of','json',str(video)],capture_output=True,timeout=15,check=True)
    streams=json.loads(probe.stdout)['streams']
    if (len(streams)!=1 or streams[0]['width']!=2688 or streams[0]['height']!=1520 or
            Fraction(streams[0]['time_base'])!=Fraction(1,90000)):
        raise ValueError('this video pilot requires2688x1520/90000Hz; review a new ROI/time base first')
    out.mkdir(parents=True,exist_ok=False)
    cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-copyts','-ss',str(start),
        '-t',str(end-start),'-i',str(video),'-map','0:v:0','-vf',
        f'crop=120:130:390:650,trim=start={start}:end={end},showinfo',
        '-frames:v',str(max_frames),'-fps_mode','passthrough',str(out/'frame_%03d.png')]
    done=subprocess.run(cmd,capture_output=True,timeout=30,check=True)
    (out/'decode.log').write_bytes(done.stderr)
    parsed=re.findall(rb'n:\s*(\d+)\s+pts:\s*(\d+)\s+pts_time:([\d.]+)',done.stderr)
    files=sorted(out.glob('frame_*.png'))
    if len(parsed)<len(files) or not files:raise ValueError('missing frame PTS')
    frames=[dict(file=p.name,pts_ticks=int(row[1]),pts_s=float(Fraction(int(row[1]),90000)),
        sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p,row in zip(files,parsed)]
    if any(a['pts_ticks']>=b['pts_ticks'] for a,b in zip(frames,frames[1:])):
        raise ValueError('nonmonotonic decoded frames')
    result=dict(requested_window_s=[start,end],frames=frames,time_base='1/90000',
        source_roi_xywh=[390,650,120,130],interpolated_frames=False,
        truncated=len(files)>=max_frames,truth_from_model=False,command=cmd)
    (out/'frames.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(out=str(out),frames=len(frames),first_pts_s=frames[0]['pts_s'],
        last_pts_s=frames[-1]['pts_s'],truncated=result['truncated'])))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--start',type=float,required=True);p.add_argument('--end',type=float,required=True)
    a=p.parse_args();extract_window(a.video,a.out,a.start,a.end)
