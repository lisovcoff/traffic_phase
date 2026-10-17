"""Fixed bounded coarse contexts for correspondence search, not timing truth."""
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
source=json.loads((ROOT/'evidence/enthusiasts_video_20261017/source.json').read_text(encoding='utf-8'))
selection=json.loads((OUT/'coarse_selection.json').read_text(encoding='utf-8'))
frames=[];started=time.monotonic()
initial=json.loads((OUT/'context_selection.json').read_text(encoding='utf-8'))['decode_wall_s']
for at in selection['requested_media_s']:
    if time.monotonic()-started+initial>220:raise ValueError('total decode budget exhausted')
    output=OUT/f'coarse_{at:05d}.jpg'
    if output.exists():raise ValueError('fresh output required')
    cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-copyts','-ss',str(at),'-i',source['path'],
        '-map','0:v:0','-vf','showinfo,scale=1024:-1','-frames:v','1','-fps_mode','passthrough','-q:v','2','-update','1',str(output)]
    done=subprocess.run(cmd,capture_output=True,check=True,timeout=20)
    (OUT/f'coarse_{at:05d}.log').write_bytes(done.stderr)
    rows=re.findall(rb'n:\s*0\s+pts:\s*(\d+)\s+pts_time:([\d.]+)',done.stderr)
    if not rows:raise ValueError('missing native PTS')
    pts=int(rows[0][0])
    frames.append(dict(requested_s=at,actual_pts_ticks=pts,actual_pts_s=float(Fraction(pts,90000)),
        file=output.name,sha256=hashlib.sha256(output.read_bytes()).hexdigest(),command=cmd,
        interpretation='lossy scaled coarse context; not native timing/localization evidence'))
result=dict(frames=frames,decode_wall_s=time.monotonic()-started,time_base='1/90000',clock_transform=None)
(OUT/'coarse_manifest.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
for group in range(3):
    subset=frames[group*9:(group+1)*9]
    if not subset:continue
    rows=(len(subset)+2)//3
    sheet=Image.new('RGB',(3*672,rows*406),'white');draw=ImageDraw.Draw(sheet)
    for i,r in enumerate(subset):
        im=Image.open(OUT/r['file']).resize((672,380));x=i%3*672;y=i//3*406
        sheet.paste(im,(x,y+26));draw.text((x+8,y+6),f"PTS {r['actual_pts_s']:.6f}s (coarse scaled context)",fill='black')
    sheet.save(OUT/f'coarse_contact_{group}.jpg',quality=92)
print(json.dumps(dict(new_frames=len(frames),decode_wall_s=result['decode_wall_s'],total_decode_wall_s=initial+result['decode_wall_s'])))
