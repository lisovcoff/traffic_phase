"""Video-only sampler. Actual native PTS; fixed lens ROIs; no model predictions."""
import argparse
import csv
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import numpy as np
from PIL import Image,ImageDraw
from scripts.video_truth_inventory import SOURCES,ROOT,OUT,LOCAL,save

ROIS={
 'sverdlovsky':dict(crop=[1940,864,180,120],green=[88,74,108,92],red=[95,45,114,64],arrow=[73,68,89,86],amber=[90,60,112,78]),
 'enthusiasts':dict(crop=[390,650,120,130],green=[40,52,61,73],red=[37,28,57,47])}


def features(path,site):
    a=np.asarray(Image.open(path)).astype(float)
    result={}
    for key,box in ROIS[site].items():
        if key=='crop':continue
        x1,y1,x2,y2=box;rgb=a[y1:y2,x1:x2]
        r,g,b=np.moveaxis(rgb,-1,0)
        if key=='red':mask=(r>80)&(r>1.3*g)&(r>1.15*b)
        elif key=='amber':mask=(r>80)&(g>50)&(r>1.15*b)&(g>1.15*b)&(r<2.5*g)
        elif site=='enthusiasts':
            # This camera's shaded green lens is cyan in decoded RGB; demanding
            # G>B rejects a visibly lit lens. Used for proposals, never truth.
            mask=(g>45)&(g>1.30*r)&(g>.75*b)
        else:mask=(g>60)&(g>1.25*r)&(g>1.10*b)
        result[key+'_pixels']=int(mask.sum())
    return result


def sample(site,start,end,target,*,spacing_s=.5,max_frames=None):
    if not 0<=start<end or end-start>600:raise ValueError('positive window at most600s')
    if spacing_s and spacing_s<1/3:raise ValueError('coarse sampling at most3fps')
    if spacing_s is None and (end-start>2 or max_frames is None or max_frames>70):
        raise ValueError('native refinement at most2s/70frames')
    target.mkdir(parents=True,exist_ok=False)
    crop=ROIS[site]['crop'];x,y,w,h=crop
    select=f",select='isnan(prev_selected_t)+gte(t-prev_selected_t,{spacing_s})'" if spacing_s else ''
    filt=f'crop={w}:{h}:{x}:{y},trim=start={start}:end={end}'+select+',showinfo'
    cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-copyts','-ss',str(start),
         '-t',str(end-start),'-i',str(SOURCES[site]),'-map','0:v:0','-vf',filt,
         '-frames:v',str(max_frames or int((end-start)/spacing_s)+3),'-fps_mode','passthrough',str(target/'frame_%05d.png')]
    began=time.monotonic();result=subprocess.run(cmd,capture_output=True,timeout=240,check=True)
    (target/'decode.log').write_bytes(result.stderr)
    parsed=re.findall(rb'n:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:([\d.]+)',result.stderr)
    files=sorted(target.glob('frame_*.png'))
    assert files and len(parsed)>=len(files)
    rows=[]
    for path,row in zip(files,parsed):
        ticks=int(row[1]);pts=float(Fraction(ticks,90000))
        rows.append(dict(file=path.name,pts_ticks=ticks,pts_s=pts,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),**features(path,site)))
    assert all(a['pts_ticks']<b['pts_ticks'] for a,b in zip(rows,rows[1:]))
    report=dict(site=site,source=str(SOURCES[site]),source_bytes=SOURCES[site].stat().st_size,
        roi=ROIS[site],range_s=[start,end],spacing_s=spacing_s,frames=rows,
        actual_pts=True,interpolated=False,model_predictions_read=False,
        feature_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        color_features_are_review_proposals_not_truth=True,
        runtime_s=time.monotonic()-began,truncated=len(files)>=(max_frames or int((end-start)/spacing_s)+3),command=cmd)
    save(target/'frames.json',report)
    print(json.dumps(dict(site=site,range=[start,end],frames=len(rows),runtime_s=report['runtime_s'])),flush=True)
    return report


def candidates(report):
    """Long dark gap avoids calling green blinking a fresh release; review required."""
    rows=report['frames'];found=[]
    for kind in ('green','red'):
        previous_on=None
        for i,row in enumerate(rows):
            active=row[kind+'_pixels']>=3
            if active:
                gap=row['pts_s']-previous_on if previous_on is not None else None
                # Require a preceding observed opposite color and future persistence.
                earlier=[r for r in rows[max(0,i-16):i] if row['pts_s']-r['pts_s']<8]
                other='red' if kind=='green' else 'green'
                opposite=any(r[other+'_pixels']>=3 for r in earlier)
                later=rows[i+1:i+4]
                persistent=any(r[kind+'_pixels']>=3 for r in later)
                if i>0 and (previous_on is None or gap>5) and opposite and persistent:
                    found.append(dict(kind=kind,coarse_interval_s=[rows[i-1]['pts_s'],row['pts_s']],
                                      gap_since_color_s=gap,requires_visual_review=True))
                previous_on=row['pts_s']
    return sorted(found,key=lambda r:r['coarse_interval_s'][0])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('site',choices=SOURCES);p.add_argument('start',type=float);p.add_argument('end',type=float)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--native',action='store_true')
    args=p.parse_args()
    report=sample(args.site,args.start,args.end,args.output,spacing_s=None if args.native else .5,
                  max_frames=70 if args.native else None)
    if not args.native:
        choices=candidates(report);save(args.output/'candidates.json',choices)
        print(json.dumps(choices),flush=True)


if __name__=='__main__':main()
