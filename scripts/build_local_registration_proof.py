"""Proof crops from sealed sampled frames; no fit, extraction or media decoding."""
import csv
import hashlib
import json
from pathlib import Path
import sys

from PIL import Image,ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.experimental.vehicle_clock_alignment import predict,prepare_tracks

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/local_vehicle_registration_20261015'
model=json.loads((OUT/'local_model.json').read_text())
train=json.loads((OUT/'training_points.json').read_text())['rows']
validation=json.loads((OUT/'validation_points.json').read_text())['rows']
tracks=prepare_tracks(json.loads((ROOT/'evidence/seven_restart_review_20261015/selected_raw_tracks.json').read_text()))
(OUT/'proof').mkdir(exist_ok=True)
manifest=[]
for role,rows in [('training',train),('validation',validation)]:
    predicted=predict(tracks,rows,model['homography'],model['delta_s'],model['origin_ms'])
    for row,point in zip(rows,predicted):
        t=row['requested_media_s']
        old=t in [318,324]
        parent=ROOT/('.annotation_runtime/seven_restart_frames' if old else '.annotation_runtime/local_registration_frames')
        source=parent/f'frame_{t:05d}.png'
        assert hashlib.sha256(source.read_bytes()).hexdigest()==row['frame_sha256']
        ox,oy=(1050,900) if old else (0,0)
        a,b,c,d=row['manual_bbox_px']
        source_image=Image.open(source).convert('RGB')
        # A fixed native-image crop; circles mark measured and predicted features.
        left=max(0,a-ox-25);top=max(0,b-oy-25)
        right=min(source_image.width,c-ox+25);bottom=min(source_image.height,d-oy+25)
        image=source_image.crop((left,top,right,bottom))
        draw=ImageDraw.Draw(image)
        for xy,color in [(row['image_point_px'],'lime'),(point,'red')]:
            x,y=xy[0]-ox-left,xy[1]-oy-top
            draw.ellipse((x-4,y-4,x+4,y+4),outline=color,width=2)
        canvas=Image.new('RGB',(max(image.width,210),image.height+38),'#111111')
        canvas.paste(image,(0,38));draw=ImageDraw.Draw(canvas)
        draw.text((3,3),f"{role} {row['track_id']} media{row['actual_media_pts_s']:.3f}",fill='white')
        draw.text((3,20),'green=manual red=frozen model',fill='white')
        name=f"proof/{role}_{row['track_id']}_{t}.png";canvas.save(OUT/name)
        manifest.append(dict(file=name,sha256=hashlib.sha256((OUT/name).read_bytes()).hexdigest(),
            source_frame_sha256=row['frame_sha256'],actual_media_pts_s=row['actual_media_pts_s'],
            source_roi_origin_px=[ox,oy],crop_in_source_roi_px=[left,top,right,bottom],
            processing='native crop; point circles and text; no resize, no model fitting'))
(OUT/'proof_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
comparison=json.loads((OUT/'release_comparison.json').read_text())
with (OUT/'release_comparison.csv').open('w',newline='',encoding='utf8') as f:
    writer=csv.writer(f)
    writer.writerow(['track_id_hypothesis','movement','candidate_minus_onset_min_s','candidate_minus_onset_max_s',
        'frozen_H_clock_set_overlaps_visible_bracket','timing_validation_status'])
    for row in comparison['rows']:
        writer.writerow([row['track_id'],row['movement'],*row['point_event_minus_onset_range_s'],
            row['conditional_sets_overlap_video_bracket'],row['timing_validation_status']])
print('33 native proof crops and seven-event CSV saved; source frame hashes checked')
