"""Bounded native lamp sequence sampling, independent of phase predictions."""
import argparse
import re
import subprocess
from PIL import Image,ImageDraw
from scripts.video_truth_inventory import ROOT,SOURCES,save,sha
from scripts.sample_video_truth import ROIS

OUT=ROOT/'evidence/yellow_timing_20261019'
WINDOWS={'sverdlovsky':[(1015.5,1020),(1065.5,1071),(1115.5,1120),(1165.5,1171)],
         'enthusiasts':[(1005,1010),(1072,1079),(1105,1110),(1172,1179)]}


def collect(site,validation=False):
    folder=OUT/site/('validation' if validation else 'development');folder.mkdir(parents=True,exist_ok=False)
    windows=[(3300,3600)] if validation else WINDOWS[site]
    save(folder/'plan.json',dict(site=site,windows_s=windows,spacing_s=.5 if validation else .2,
        labels_selected_from_video=True,prediction_data_read=False,
        purpose='coarse review proposals only; native PTS retained; refine ambiguous endpoints separately'))
    for index,(a,b) in enumerate(windows):
        target=folder/str(index);target.mkdir()
        x,y,w,h=ROIS[site]['crop'];spacing=.5 if validation else .2
        cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-copyts','-ss',str(a),'-t',str(b-a),'-i',str(SOURCES[site]),
             '-vf',f"crop={w}:{h}:{x}:{y},trim=start={a}:end={b},select='isnan(prev_selected_t)+gte(t-prev_selected_t,{spacing})',showinfo",
             '-fps_mode','passthrough',str(target/'frame_%05d.png')]
        r=subprocess.run(cmd,capture_output=True,check=True,timeout=90);(target/'decode.log').write_bytes(r.stderr)
        parsed=re.findall(rb'n:\s*(\d+)\s+pts:\s*(\d+)\s+pts_time:([\d.]+)',r.stderr)
        paths=sorted(target.glob('frame_*.png'));assert len(parsed)>=len(paths)>0
        frames=[dict(file=p.name,pts_s=int(v[1])/90000,pts_ticks=int(v[1]),sha256=sha(p)) for p,v in zip(paths,parsed)]
        save(target/'frames.json',dict(rows=frames,command=cmd))
        if not validation:
            sheet=Image.new('RGB',(1000,((len(paths)+7)//8)*155),(20,25,35));draw=ImageDraw.Draw(sheet)
            for i,(p,f) in enumerate(zip(paths,frames)):
                im=Image.open(p);im.thumbnail((120,130));xx=i%8*125;yy=i//8*155
                sheet.paste(im,(xx,yy+22));draw.text((xx,yy+3),f"{f['pts_s']:.3f}",fill='white')
            sheet.save(folder/f'sheet_{index}.png')
        print(site,a,b,len(paths),flush=True)


def refine(site):
    times=[1017,1019,1067,1070,1117,1119,1167,1170] if site=='sverdlovsky' else [1006.75,1008.75,1074,1077,1106.75,1108.75,1174,1177]
    folder=OUT/site/'development_native_v2';folder.mkdir(parents=True,exist_ok=False)
    save(folder/'plan.json',dict(targets_s=times,window_width_s=.8,maximum_frames_per_window=26,phase_predictions_used=False))
    for i,t in enumerate(times):
        target=folder/str(i);target.mkdir();a=t-.4;b=t+.4;x,y,w,h=ROIS[site]['crop']
        cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-copyts','-ss',str(a),'-t','0.8','-i',str(SOURCES[site]),
            '-vf',f'crop={w}:{h}:{x}:{y},trim=start={a}:end={b},showinfo','-frames:v','26','-fps_mode','passthrough',str(target/'frame_%05d.png')]
        r=subprocess.run(cmd,capture_output=True,check=True,timeout=30);(target/'decode.log').write_bytes(r.stderr)
        parsed=re.findall(rb'n:\s*(\d+)\s+pts:\s*(\d+)\s+pts_time:([\d.]+)',r.stderr)
        files=sorted(target.glob('frame_*.png'));assert 0<len(files)<=26 and len(parsed)>=len(files)
        rows=[dict(file=p.name,pts_ticks=int(v[1]),pts_s=int(v[1])/90000,sha256=sha(p)) for p,v in zip(files,parsed)]
        save(target/'frames.json',dict(rows=rows,command=cmd))
    print('native development windows collected',site,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('site',choices=SOURCES);p.add_argument('--validation',action='store_true');p.add_argument('--native',action='store_true');a=p.parse_args()
    refine(a.site) if a.native else collect(a.site,a.validation)
