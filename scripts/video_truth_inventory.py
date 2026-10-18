"""Fresh native frames and clocks for the two supplied video files; no model use."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from fractions import Fraction
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/direct_video_truth_20261018'
LOCAL=ROOT/'.web_runtime/direct_video_truth_20261018'
SOURCES={
 'sverdlovsky':Path('C:/Users/sheld/Downloads/len_sverdl 2025-02-27T10_00_00_2025-02-27T12_00_00.mp4'),
 'enthusiasts':Path('C:/Users/sheld/Downloads/lenina_entuziastov.mp4')}


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf8',newline='\n') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(site,video,t,folder):
    folder.mkdir(parents=True,exist_ok=False)
    cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-copyts','-ss',str(t),'-i',str(video),
         '-map','0:v:0','-vf','showinfo','-frames:v','1','-fps_mode','passthrough',str(folder/'frame.png')]
    result=subprocess.run(cmd,capture_output=True,timeout=30,check=True)
    (folder/'decode.log').write_bytes(result.stderr)
    pts=re.findall(rb'n:\s*0\s+pts:\s*(-?\d+)\s+pts_time:([\d.]+)',result.stderr)
    if not pts:raise ValueError('no actual frame PTS')
    ticks=int(pts[0][0]);seconds=float(Fraction(ticks,90000))
    with Image.open(folder/'frame.png') as im:
        # Full camera clock area, source pixels retained without resampling.
        clock=im.crop((0,im.height-160,1100,im.height))
        clockpath=OUT/site/f'clock_{t:05}.png';clockpath.parent.mkdir(parents=True,exist_ok=True)
        clock.save(clockpath)
        preview=im.copy();preview.thumbnail((1344,760))
        previewpath=OUT/site/f'context_{t:05}.jpg';preview.save(previewpath,quality=95)
    return dict(requested_pts_s=t,pts_ticks=ticks,pts_s=seconds,time_base='1/90000',
                full_frame=str((folder/'frame.png').relative_to(ROOT)),frame_sha256=sha(folder/'frame.png'),
                clock=str(clockpath.relative_to(OUT)),clock_sha256=sha(clockpath),
                context=str(previewpath.relative_to(OUT)),context_sha256=sha(previewpath),command=cmd)


def main():
    OUT.mkdir(exist_ok=False);LOCAL.mkdir(exist_ok=False)
    reports=[]
    for site,video in SOURCES.items():
        info=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries',
            'stream=width,height,time_base,avg_frame_rate,r_frame_rate,start_time,duration:format=duration,start_time',
            '-of','json',str(video)],capture_output=True,timeout=20,check=True)
        metadata=json.loads(info.stdout);stream=metadata['streams'][0]
        assert (stream['width'],stream['height'],stream['time_base'])==(2688,1520,'1/90000')
        points=[0,900,2700,3600]
        rows=[extract(site,video,t,LOCAL/site/str(t)) for t in points]
        save(OUT/site/'inventory.json',dict(source=str(video),bytes=video.stat().st_size,
            mtime_ns=video.stat().st_mtime_ns,metadata=metadata,frames=rows,
            prediction_data_read=False,clock_mapping_accepted=False))
        # Labelled clock contact sheet, native clock pixels.
        sheet=Image.new('RGB',(1100,190*len(rows)),(24,29,37));draw=ImageDraw.Draw(sheet)
        for i,row in enumerate(rows):
            draw.text((10,i*190+4),f"{site} requested={row['requested_pts_s']} actual PTS={row['pts_s']:.6f}",fill='white')
            with Image.open(OUT/row['clock']) as crop:sheet.paste(crop,(0,i*190+25))
        sheet.save(OUT/site/'clock_sheet.png')
        reports.append(dict(site=site,frames=len(rows),duration_s=metadata['format']['duration']))
        print(json.dumps(reports[-1]),flush=True)
    save(OUT/'inventory.json',reports)


if __name__=='__main__':main()
