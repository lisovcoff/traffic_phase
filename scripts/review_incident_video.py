"""Video-only context contact sheets with actual presentation timestamps."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
VIDEO=Path.home()/'Downloads/lenina_entuziastov.mp4'


def main(start,end,step,name):
    target=ROOT/'.web_runtime/incident_validation_20261020/video'/name
    target.mkdir(parents=True,exist_ok=False);rows=[]
    for second in range(start,end+1,step):
        path=target/f'{second:05d}.jpg'
        cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-copyts','-ss',str(second),
             '-i',str(VIDEO),'-map','0:v:0','-vf','showinfo','-frames:v','1','-fps_mode','passthrough',
             '-q:v','2','-update','1',str(path)]
        result=subprocess.run(cmd,capture_output=True,check=True,timeout=60)
        (target/f'{second:05d}.log').write_bytes(result.stderr)
        ticks=int(re.findall(rb'n:\s*0\s+pts:\s*(-?\d+)',result.stderr)[0])
        rows.append(dict(file=str(path.relative_to(ROOT)),requested_s=second,actual_pts_s=ticks/90000,
                         actual_pts_ticks=ticks,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),command=cmd))
        print('FRAME',second,flush=True)
    for page in range((len(rows)+8)//9):
        sheet=Image.new('RGB',(1800,3*365),'white');draw=ImageDraw.Draw(sheet)
        for i,row in enumerate(rows[page*9:(page+1)*9]):
            image=Image.open(ROOT/row['file']);image.thumbnail((600,340))
            x=(i%3)*600;y=(i//3)*365
            draw.text((x+5,y+4),f"PTS {row['actual_pts_s']:.3f}s",fill='black')
            sheet.paste(image,(x,y+25))
        sheet.save(target/f'contact_{page}.jpg',quality=94)
    with (target/'frames.json').open('x',encoding='utf8') as f:
        json.dump(dict(source=str(VIDEO),source_bytes=VIDEO.stat().st_size,frames=rows,
                       model_predictions_read=False,labels_not_inferred_from_contact_sheet=True),f,indent=2)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('start',type=int);p.add_argument('end',type=int);p.add_argument('step',type=int);p.add_argument('name')
    args=p.parse_args();main(args.start,args.end,args.step,args.name)
