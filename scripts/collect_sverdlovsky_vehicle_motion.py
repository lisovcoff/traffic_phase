"""Independent neighboring-frame car crops for the frozen clock hypothesis."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from PIL import Image,ImageDraw
from scripts.cardinal_clock_link import ROOT,OUT,save
from scripts.build_cardinal_clock_review import VIDEO

SPECS=[(900,9917625,[1720,700,560,350]),(1800,9919993,[1640,650,560,350]),
       (2700,9922632,[1330,550,560,350])]


def main():
    target=OUT/'sverdlovsky_motion';target.mkdir(exist_ok=False)
    save(target/'plan.json',dict(cases=SPECS,new_frames_reason='One frame cannot establish motion/identity. Neighbor frames check direction and same vehicle without clock refit or signals.',
        maximum_native_frames=9,new_fits=0,phase_predictions_read=False,
        source_label_caveat='raw E/W names may not equal the user-defined image-left/right; do not silently remap'))
    cases=[]
    sheet=Image.new('RGB',(1680,1155),(20,25,35));draw=ImageDraw.Draw(sheet)
    for index,(at,identity,box) in enumerate(SPECS):
        folder=target/str(at);folder.mkdir()
        x,y,w,h=box;start=at-.5;end=at+.6
        cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-copyts','-ss',str(start),'-t','1.1','-i',str(VIDEO),
             '-vf',f"crop={w}:{h}:{x}:{y},trim=start={start}:end={end},select='isnan(prev_selected_t)+gte(t-prev_selected_t,0.5)',showinfo",
             '-frames:v','3','-fps_mode','passthrough',str(folder/'frame_%02d.png')]
        done=subprocess.run(cmd,capture_output=True,timeout=30,check=True);(folder/'decode.log').write_bytes(done.stderr)
        parsed=re.findall(rb'n:\s*(\d+)\s+pts:\s*(\d+)\s+pts_time:([\d.]+)',done.stderr)
        frames=[]
        for col,(path,row) in enumerate(zip(sorted(folder.glob('frame_*.png')),parsed)):
            pts=int(row[1])/90000
            frames.append(dict(file=path.relative_to(OUT).as_posix(),pts_s=pts,pts_ticks=int(row[1]),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            draw.text((col*560+5,index*385+4),f'raw candidate {identity}; PTS {pts:.6f}; origin{x},{y}',fill='white')
            with Image.open(path) as image:sheet.paste(image,(col*560,index*385+30))
        assert len(frames)==3
        cases.append(dict(track_id_hypothesis=identity,roi_xywh=box,frames=frames,command=cmd))
    sheet.save(target/'native_motion_sheet.png')
    save(target/'frames.json',dict(cases=cases,clock_refit=False,identities_not_yet_confirmed=True))
    print('9 native car crops collected; no model/clock fit')


if __name__=='__main__':main()
