"""Single documented annotation correction, before any heldout scoring."""
import hashlib,json
from pathlib import Path
from PIL import Image,ImageDraw
from app.experimental.vehicle_clock_alignment import fit_training
ROOT=Path.cwd();OUT=ROOT/'evidence/enthusiasts_car_registration_20261018'
for f in ('corrected_model.json','corrected_points.json','corrected_seal.json'):
    if (OUT/f).exists():raise ValueError('fresh correction outputs required')
if (OUT/'heldout_points.json').exists():raise ValueError('correction forbidden after heldout annotation')
correction=json.loads((OUT/'annotation_correction.json').read_text(encoding='utf-8'))
points=json.loads((OUT/'training_points.json').read_text(encoding='utf-8'))
frames=[r for name in ('frames.json','fine_frames.json') for r in json.loads((OUT/name).read_text(encoding='utf-8'))['frames']]
for r in points['rows']:
    if r['track_id']==6:
        at=next(f['requested_s'] for f in frames if f['pts_s']==r['actual_media_pts_s'])
        b=correction['corrected_bbox_crop_xyxy_by_requested_s'][str(at)]
        b=[b[0]+100,b[1]+450,b[2]+100,b[3]+450]
        r.update(bbox_native_px=b,image_point_px=[(b[0]+b[2])/2,b[1]+.75*(b[3]-b[1])])
points['annotation_correction']='annotation_correction.json; track6 blue sedan in same lane as track2'
(OUT/'corrected_points.json').write_text(json.dumps(points,indent=2)+'\n',encoding='utf-8')
raw=(ROOT/'.web_runtime/enthusiasts_vehicle_link_20261018/first_entry.json').read_bytes();records=json.loads(raw)
selection=json.loads((OUT/'training_selection.json').read_text(encoding='utf-8'))
model=fit_training([r for r in records if r['id'] in (2,6)],points['rows'],training_ids=[2,6],heldout_id=7,
    origin_ms=selection['candidate_origin_ms'],delta_bounds=(-10,10),max_nfev=1000,max_seconds=15)
model.update(association_status='PROVISIONAL_NOT_CERTIFIED',all_clock_fit_calls_including_invalid=2,
    train_gate_pass=model['training_max_error_px']<=30 and model['optimizer_success'] and not model['limit_active'],
    annotation_correction_reference='annotation_correction.json',production_usable=False)
(OUT/'corrected_model.json').write_text(json.dumps(model,indent=2)+'\n',encoding='utf-8')
seal={name:hashlib.sha256((OUT/name).read_bytes()).hexdigest() for name in ('corrected_model.json','corrected_points.json','annotation_correction.json','fit_seal.json')}
(OUT/'corrected_seal.json').write_text(json.dumps(seal,indent=2)+'\n',encoding='utf-8')
for at in (13,13.5,14,15):
    f=next(f for f in frames if f['requested_s']==at)
    im=Image.open(ROOT/f['file']).convert('RGB');draw=ImageDraw.Draw(im)
    for r in points['rows']:
        if r['actual_media_pts_s']==f['pts_s']:
            draw.rectangle(r['bbox_native_px'],outline='magenta',width=3)
            draw.text(tuple(r['bbox_native_px'][:2]),f"candidate ID {r['track_id']}",fill='yellow')
    im.crop((100,450,1900,1250)).save(OUT/f'corrected_proof_{str(at).replace(".","_")}.jpg',quality=95)
print(json.dumps({k:model[k] for k in ('delta_s','training_max_error_px','training_rmse_px','homography','jacobian_rank','optimizer_success','nfev','train_gate_pass')}))
