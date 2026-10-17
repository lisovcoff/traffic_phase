"""One bounded car-context extraction; preserve native PTS and hashes."""
import hashlib,json,re,subprocess,time
from pathlib import Path
from fractions import Fraction
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
plan=json.loads((OUT/'plan.json').read_text(encoding='utf-8'))
source=json.loads((ROOT/'evidence/enthusiasts_video_20261017/source.json').read_text(encoding='utf-8'))
dest=ROOT/'.web_runtime'/OUT.name;dest.mkdir(exist_ok=False)
frames=[];start=time.monotonic()
for at in plan['initial_review_times_s']:
    if time.monotonic()-start>plan['max_decode_wall_seconds']-20:raise ValueError('decode wall budget')
    p=dest/f'{at:05d}.png'
    cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-copyts','-ss',str(at),'-i',source['path'],
         '-map','0:v:0','-vf','showinfo','-frames:v','1','-fps_mode','passthrough','-update','1',str(p)]
    done=subprocess.run(cmd,capture_output=True,check=True,timeout=plan['max_command_wall_seconds'])
    (OUT/f'decode_{at:05d}.log').write_bytes(done.stderr)
    pts=int(re.findall(rb'n:\s*0\s+pts:\s*(\d+)',done.stderr)[0])
    frames.append(dict(requested_s=at,pts_ticks=pts,pts_s=float(Fraction(pts,90000)),file=str(p.relative_to(ROOT)),
        sha256=hashlib.sha256(p.read_bytes()).hexdigest(),command=cmd))
(OUT/'frames.json').write_text(json.dumps(dict(frames=frames,decode_wall_s=time.monotonic()-start,time_base='1/90000'),indent=2)+'\n',encoding='utf-8')
for g in range(2):
    rows=frames[g*8:(g+1)*8];sheet=Image.new('RGB',(4*672,2*406),'white');draw=ImageDraw.Draw(sheet)
    for i,r in enumerate(rows):
        x=i%4*672;y=i//4*406;sheet.paste(Image.open(ROOT/r['file']).resize((672,380)),(x,y+26))
        draw.text((x+8,y+6),f"PTS {r['pts_s']:.6f}s",fill='black')
    sheet.save(OUT/f'contact_{g}.jpg',quality=94)
print(json.dumps(dict(frames=len(frames),decode_wall_s=time.monotonic()-start)))
