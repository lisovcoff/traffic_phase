"""Evaluation-only backward feature tracking of the visible crashed white car.

Optical-flow proposals are not certified vehicle identities or JSON clock links.
Input frames retain original video PTS; no signal colors are used here.
"""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import json
import argparse
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
LOCAL=ROOT/'.web_runtime/coherent_signal_20261020'
sys.path.insert(0,str(LOCAL/'vision_deps'))
import cv2
import numpy as np
from PIL import Image,ImageDraw


def main(seed_pts=None,polygon_native=None,tag='car_flow'):
    paths=sorted(p for p in LOCAL.glob('car_flow_*.jpg') if p.stem.removeprefix('car_flow_').isdigit())
    blob=(LOCAL/'car_flow_frames.log').read_bytes()
    log=blob.decode('utf16' if blob.startswith(b'\xff\xfe') else 'utf8',errors='replace')
    pts=[int(x)/90000 for x in re.findall(r'n:\s*\d+\s+pts:\s*(\d+)',log)]
    assert len(paths)==len(pts)==281
    first_index=len(paths)-1 if seed_pts is None else min(range(len(pts)),key=lambda i:abs(pts[i]-seed_pts))
    old=cv2.imread(str(paths[first_index]),cv2.IMREAD_GRAYSCALE)
    # Native source ROI starts at (900,400); seed is wholly on the white car.
    polygon=np.float32([[336,214],[389,211],[404,244],[347,251]]) if polygon_native is None else np.float32(polygon_native)-[900,400]
    rows=[];snapshots={}
    for i in range(first_index,-1,-1):
        gray=cv2.imread(str(paths[i]),cv2.IMREAD_GRAYSCALE)
        if i<first_index:
            mask=np.zeros(old.shape,np.uint8);cv2.fillConvexPoly(mask,polygon.astype(int),255)
            features=cv2.goodFeaturesToTrack(old,maxCorners=100,qualityLevel=.005,minDistance=3,mask=mask,blockSize=3)
            if features is None or len(features)<4:raise ValueError(f'insufficient car features at {pts[i]}')
            moved,status,_=cv2.calcOpticalFlowPyrLK(old,gray,features,None,winSize=(31,31),maxLevel=4)
            backward,status2,_=cv2.calcOpticalFlowPyrLK(gray,old,moved,None,winSize=(31,31),maxLevel=4)
            good=(status[:,0]>0)&(status2[:,0]>0)&(np.linalg.norm(features[:,0]-backward[:,0],axis=1)<1.5)
            if good.sum()<4:raise ValueError(f'flow lost at {pts[i]}')
            matrix,inliers=cv2.estimateAffinePartial2D(features[good,0],moved[good,0],method=cv2.RANSAC,ransacReprojThreshold=2)
            if matrix is None or inliers.sum()<4:raise ValueError(f'affine lost at {pts[i]}')
            scale=float(np.linalg.norm(matrix[:,0]))
            if not .75<scale<1.25:raise ValueError(f'unexpected scale {scale} at {pts[i]}')
            polygon=np.c_[polygon,np.ones(4)]@matrix.T
        old=gray
        rows.append(dict(actual_media_pts_s=pts[i],image_point_px=(polygon.mean(axis=0)+[900,400]).tolist(),
                         polygon_px=(polygon+[900,400]).tolist(),review_status='UNREVIEWED_OPTICAL_FLOW_PROPOSAL'))
        nearest=int(round(pts[i]))
        if nearest in (3812,3815,3818,3821,3824,3827,3830,3833,3836,3840) and nearest not in snapshots:
            picture=Image.open(paths[i]).convert('RGB');d=ImageDraw.Draw(picture)
            d.line([tuple(p) for p in np.r_[polygon,polygon[:1]]],fill='magenta',width=4)
            d.text((20,20),f'Actual PTS {pts[i]:.6f}; optical-flow proposal',fill='yellow')
            picture.thumbnail((894,425));snapshots[nearest]=picture
    sheet=Image.new('RGB',(1788,425*5))
    for j,(n,picture) in enumerate(sorted(snapshots.items())):sheet.paste(picture,((j%2)*894,(j//2)*425))
    sheet.save(LOCAL/(tag+'_contact.jpg'),quality=95)
    with (LOCAL/(tag+'_proposals.json')).open('x',encoding='utf8') as f:json.dump(dict(rows=list(reversed(rows)),
        source='lenina_entuziastov.mp4',source_pts_preserved=True,signal_labels_used=False,clock_accepted=False),f,indent=2)
    print('PROPOSALS',len(rows),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--seed-pts',type=float)
    parser.add_argument('--polygon',type=json.loads);parser.add_argument('--tag',default='car_flow')
    args=parser.parse_args();main(args.seed_pts,args.polygon,args.tag)
