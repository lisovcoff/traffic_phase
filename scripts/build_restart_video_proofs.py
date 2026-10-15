"""Crop already sampled pixels; never rereads media or infers vehicle motion."""
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'evidence/seven_restart_review_20261015'
FRAMES = ROOT/'.annotation_runtime/seven_restart_frames'
review = json.loads((OUT/'visual_review.json').read_text())
manifest = json.loads((OUT/'frames.json').read_text())
proof = OUT/'proof'
proof.mkdir(exist_ok=True)
records = []
for row in review['rows']:
    a,b,c,d = row['stationary_roi_bbox_at_318_requested_px']
    box = [max(0,a-50),max(0,b-60),min(1450,c+110),min(620,d+35)]
    w,h = box[2]-box[0],box[3]-box[1]
    sheet = Image.new('RGB',(3*w,h+44),'#101010')
    draw = ImageDraw.Draw(sheet)
    for i,frame in enumerate(row['frames']):
        src = FRAMES/frame['file']
        assert hashlib.sha256(src.read_bytes()).hexdigest() == frame['sha256']
        sheet.paste(Image.open(src).crop(box),(i*w,44))
        draw.text((i*w+4,5),row['video_object'],fill='white')
        draw.text((i*w+4,24),f"media {frame['actual_media_time_s']:.6f}",fill='white')
    target = proof/f"track_hypothesis_{row['track_id_hypothesis']}.png"
    sheet.save(target)
    records.append(dict(file=str(target.relative_to(OUT)).replace('\\','/'),
        sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        roi_crop_px=box,source_frames=row['frames'],pixel_processing='native crop, no resize; text above pixels'))
# Context image shows all seven objects and the visible head, without track-following crops.
frame = next(f for f in manifest['frames'] if f['requested_elapsed_s']==318)
src = FRAMES/frame['file']
assert hashlib.sha256(src.read_bytes()).hexdigest() == frame['sha256']
context = Image.open(src).convert('RGB')
draw = ImageDraw.Draw(context)
for row in review['rows']:
    box = row['stationary_roi_bbox_at_318_requested_px']
    draw.rectangle(box,outline='yellow',width=2)
    draw.text((box[0],max(0,box[1]-15)),str(row['track_id_hypothesis'])+'?',fill='yellow')
target = proof/'context_318.png'
context.save(target)
records.append(dict(file='proof/context_318.png',sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
    source_frames=[frame],pixel_processing='native pixels; yellow provisional identity boxes/text'))
(OUT/'proof_manifest.json').write_text(json.dumps(records,indent=2),encoding='utf8')
print('8 proof images; frame hashes verified; no video decoding or fitting')
