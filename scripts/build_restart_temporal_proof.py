"""Native proof tiles from saved frames; no decoding, extraction or fitting."""
import hashlib
import json
from pathlib import Path

from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/restart_multicycle_validation_20261015'
review=json.loads((OUT/'visual_review.json').read_text())
anchors=json.loads((OUT/'clock_anchor_review.json').read_text())
boxes=json.loads((OUT/'review_crop_boxes.json').read_text())
manifest=[]
(OUT/'proof').mkdir(exist_ok=True)


def source(block,file,digest):
    p=ROOT/f'.annotation_runtime/multicycle_{block}'/file
    assert hashlib.sha256(p.read_bytes()).hexdigest()==digest
    return Image.open(p).convert('RGB')


def save(name,image,frames,processing):
    target=OUT/'proof'/name
    image.save(target)
    manifest.append(dict(file='proof/'+name,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                         source_frames=frames,processing=processing))


for row in review['rows']:
    block=row['window'];tid=row['track_id_hypothesis'];box=boxes[block][str(tid)]
    w=max(box[2]-box[0],180);h=box[3]-box[1]
    canvas=Image.new('RGB',(3*w,h+120+65),'#111');draw=ImageDraw.Draw(canvas)
    for i,frame in enumerate(row['frames']):
        im=source(block,frame['file'],frame['sha256']);x=i*w
        canvas.paste(im.crop(box),(x,45));canvas.paste(im.crop((940,14,1120,134)),(x,h+65))
        draw.text((x+3,3),f'{block} ID{tid}? media{frame["actual_media_time_s"]:.6f}',fill='white')
        draw.text((x+3,22),row['appearance'][:38],fill='white')
        draw.text((x+3,h+48),'H1 SAME FRAME',fill='white')
    save(f'onset_{block}_{tid}.png',canvas,row['frames'],
         'native fixed-scene vehicle crop and simultaneous H1 crop; text outside pixels, no resize')
for row in review['head_references']:
    canvas=Image.new('RGB',(360,145),'#111');draw=ImageDraw.Draw(canvas)
    for i,frame in enumerate(row['frames']):
        canvas.paste(source(row['window'],frame['file'],frame['sha256']).crop((940,14,1120,134)),(i*180,25))
        draw.text((i*180+3,4),str(frame['actual_media_time_s']),fill='white')
    save(f'H1_{row["window"]}.png',canvas,row['frames'],'native H1 appearance bracket, not calibrated switch-error interval')
for row in anchors['rows']:
    im=source(row['window'],row['frame_file'],row['frame_sha256'])
    a,b,c,d=row['manual_bbox_px'];box=(max(0,a-1000-20),max(0,b-850-20),min(1500,c-1000+20),min(670,d-850+20))
    crop=im.crop(box);draw=ImageDraw.Draw(crop)
    x=row['image_point_px'][0]-1000-box[0];y=row['image_point_px'][1]-850-box[1]
    draw.ellipse((x-4,y-4,x+4,y+4),outline='lime',width=2)
    canvas=Image.new('RGB',(max(260,crop.width),crop.height+25),'#111');canvas.paste(crop,(0,25))
    ImageDraw.Draw(canvas).text((3,4),f'anchor {row["track_id"]} media{row["actual_media_pts_s"]:.3f}',fill='white')
    save(f'anchor_{row["window"]}_{row["track_id"]}_{row["requested_media_s"]}.png',canvas,
         [dict(file=row['frame_file'],sha256=row['frame_sha256'],actual_media_pts_s=row['actual_media_pts_s'])],
         'native bbox feature crop, green manual feature circle; source ROI offset1000,850; no resize')
(OUT/'proof_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
print('21 native proof images, all source frame SHA verified; no media sampling')
