"""Bounded native video context, no resampling/interpolation or model labels."""
import hashlib
import json
import re
import subprocess
import time
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
CACHE = ROOT/'.web_runtime'/OUT.name


def main():
    source = json.loads((ROOT/'evidence/enthusiasts_video_20261017/source.json').read_text(encoding='utf-8'))
    video = Path(source['path'])
    if video.stat().st_size != source['bytes']:
        raise ValueError('source size changed')
    with video.open('rb') as stream:
        for chunk in source['sampled_chunks']:
            stream.seek(chunk['offset'])
            if hashlib.sha256(stream.read(chunk['bytes'])).hexdigest()!=chunk['sha256']:
                raise ValueError('source partial fingerprint changed')
    # Declared before decoding: first source timestamp could be the start of this
    # media, but that hypothesis is explicitly NOT an accepted clock association.
    requested = [0,2,4,6,8,10,20,30,60]
    selection = dict(requested_media_s=requested, hypothesis='compare source-start traffic geometry/ordering only; NOT clock truth',
        source_start_ms=1740300640994, video_fingerprint_verified=True, fitted_transform=False)
    manifest = OUT/'context_selection.json'
    if manifest.exists():
        raise ValueError('fresh context selection required')
    manifest.write_text(json.dumps(selection,indent=2)+'\n',encoding='utf-8')
    dest=CACHE/'context'; dest.mkdir(parents=True,exist_ok=False)
    started=time.monotonic(); frames=[]
    for at in requested:
        if time.monotonic()-started>220:
            raise ValueError('decode budget exhausted')
        output=dest/f'{at:05d}.png'
        cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-copyts','-ss',str(at),'-i',str(video),
            '-map','0:v:0','-vf','showinfo','-frames:v','1','-fps_mode','passthrough','-update','1',str(output)]
        done=subprocess.run(cmd,capture_output=True,check=True,timeout=20)
        log=OUT/f'context_{at:05d}.log'; log.write_bytes(done.stderr)
        rows=re.findall(rb'n:\s*0\s+pts:\s*(\d+)\s+pts_time:([\d.]+)',done.stderr)
        if not rows: raise ValueError('missing native PTS')
        pts=int(rows[0][0])
        frames.append(dict(requested_s=at,actual_pts_ticks=pts,actual_pts_s=float(Fraction(pts,90000)),
            native_file=str(output.relative_to(ROOT)),sha256=hashlib.sha256(output.read_bytes()).hexdigest(),command=cmd))
    selection.update(frames=frames,decode_wall_s=time.monotonic()-started,
        native_bytes=sum((ROOT/r['native_file']).stat().st_size for r in frames),time_base='1/90000')
    manifest.write_text(json.dumps(selection,indent=2)+'\n',encoding='utf-8')
    sheet=Image.new('RGB',(3*672,3*406),'white'); draw=ImageDraw.Draw(sheet)
    for index,r in enumerate(frames):
        im=Image.open(ROOT/r['native_file']).convert('RGB').resize((672,380))
        x=(index%3)*672;y=(index//3)*406
        sheet.paste(im,(x,y+26));draw.text((x+8,y+6),f"Native PTS {r['actual_pts_s']:.6f}s - display scaled only",fill='black')
    sheet.save(OUT/'context_contact.jpg',quality=92)
    print(json.dumps({k:selection[k] for k in ('decode_wall_s','native_bytes')},indent=2))


if __name__=='__main__':main()
