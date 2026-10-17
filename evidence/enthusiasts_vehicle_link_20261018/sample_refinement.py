"""Inspect preregistered bus candidates in native frames; no fitted parameters."""
import hashlib
import json
import re
import subprocess
import time
from fractions import Fraction
from pathlib import Path
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
CACHE=ROOT/'.web_runtime'/OUT.name
source=json.loads((ROOT/'evidence/enthusiasts_video_20261017/source.json').read_text(encoding='utf-8'))
selection=json.loads((OUT/'refinement_selection.json').read_text(encoding='utf-8'))
prior_wall=sum(json.loads((OUT/n).read_text(encoding='utf-8'))['decode_wall_s'] for n in ('context_selection.json','coarse_manifest.json'))
dest=CACHE/'refinement';dest.mkdir(exist_ok=False)
frames=[];started=time.monotonic()
for at in selection['requested_media_s']:
    if time.monotonic()-started+prior_wall>220:raise ValueError('total decode wall budget exhausted')
    used=sum(p.stat().st_size for root in (CACHE,OUT) for p in root.rglob('*') if p.is_file())
    if used+8*1024*1024>134217728:raise ValueError('output byte budget exhausted')
    output=dest/f'{at:05d}.png'
    cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-copyts','-ss',str(at),'-i',source['path'],
        '-map','0:v:0','-vf','showinfo','-frames:v','1','-fps_mode','passthrough','-update','1',str(output)]
    done=subprocess.run(cmd,capture_output=True,check=True,timeout=20)
    (OUT/f'refinement_{at:05d}.log').write_bytes(done.stderr)
    rows=re.findall(rb'n:\s*0\s+pts:\s*(\d+)\s+pts_time:([\d.]+)',done.stderr)
    if not rows:raise ValueError('missing native PTS')
    pts=int(rows[0][0])
    frames.append(dict(requested_s=at,actual_pts_ticks=pts,actual_pts_s=float(Fraction(pts,90000)),
        native_file=str(output.relative_to(ROOT)),sha256=hashlib.sha256(output.read_bytes()).hexdigest(),command=cmd))
result=dict(frames=frames,decode_wall_s=time.monotonic()-started,time_base='1/90000',clock_transform=None)
(OUT/'refinement_manifest.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
sheet=Image.new('RGB',(3*672,3*406),'white');draw=ImageDraw.Draw(sheet)
for i,r in enumerate(frames):
    im=Image.open(ROOT/r['native_file']).resize((672,380));x=i%3*672;y=i//3*406
    sheet.paste(im,(x,y+26));draw.text((x+8,y+6),f"PTS {r['actual_pts_s']:.6f}s (native context; scaled display)",fill='black')
sheet.save(OUT/'refinement_contact.jpg',quality=92)
print(json.dumps(dict(new_frames=len(frames),decode_wall_s=result['decode_wall_s'],total_decode_wall_s=prior_wall+result['decode_wall_s'])))
