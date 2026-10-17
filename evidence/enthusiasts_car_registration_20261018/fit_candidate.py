"""One empirical candidate fit; no accepted identity or calibrated clock claim."""
import hashlib,json
from pathlib import Path
from PIL import Image,ImageDraw
from app.experimental.vehicle_clock_alignment import fit_training

ROOT=Path.cwd();OUT=ROOT/'evidence/enthusiasts_car_registration_20261018'
selection=json.loads((OUT/'training_selection.json').read_text(encoding='utf-8'))
raw=(ROOT/'.web_runtime/enthusiasts_vehicle_link_20261018/first_entry.json').read_bytes()
records=json.loads(raw)
manifests=[json.loads((OUT/n).read_text(encoding='utf-8'))['frames'] for n in ('frames.json','fine_frames.json')]
frames={r['requested_s']:r for rows in manifests for r in rows}
# Manually reviewed bboxes in native crop coordinates; crop origin=(100,450).
annotations=[(2,13,[665,376,844,507]),(2,13.5,[795,440,998,590]),
             (6,13,[686,232,796,309]),(6,13.5,[751,250,872,337]),
             (6,14,[830,281,963,374]),(6,15,[1053,368,1229,471])]
rows=[]
for track,at,bbox in annotations:
    b=[bbox[0]+100,bbox[1]+450,bbox[2]+100,bbox[3]+450];f=frames[at]
    rows.append(dict(track_id=track,actual_media_pts_s=f['pts_s'],bbox_native_px=b,
        image_point_px=[(b[0]+b[2])/2,b[1]+.75*(b[3]-b[1])],
        source_native_file=f['file'],source_native_sha256=f['sha256'],identity='PROVISIONAL_SEQUENCE_CANDIDATE'))
points=dict(rows=rows,excluded_selected_track=dict(track_id=16,reason='No defensible annotation from selected crop sequence; excluded before fit, not filled from model.'),
    training_tracks=[2,6],heldout_tracks=[7,19],source_raw_sha256=hashlib.sha256(raw).hexdigest())
for name in ('training_points.json','candidate_model.json','fit_seal.json'):
    if (OUT/name).exists():raise ValueError('fresh fit outputs required')
(OUT/'training_points.json').write_text(json.dumps(points,indent=2)+'\n',encoding='utf-8')
for at in (13,13.5,14,15):
    frame=frames[at];im=Image.open(ROOT/frame['file']).convert('RGB');draw=ImageDraw.Draw(im)
    for r in rows:
        if r['actual_media_pts_s']==frame['pts_s']:
            draw.rectangle(r['bbox_native_px'],outline='magenta',width=3)
            draw.text(tuple(r['bbox_native_px'][:2]),f"candidate track {r['track_id']}",fill='yellow')
    im.crop((100,450,1900,1250)).save(OUT/f'train_proof_{str(at).replace(".","_")}.jpg',quality=95)
model=fit_training([r for r in records if r['id'] in (2,6)],rows,training_ids=[2,6],heldout_id=7,
    origin_ms=selection['candidate_origin_ms'],delta_bounds=(-10,10),max_nfev=1000,max_seconds=15)
model.update(association_status='PROVISIONAL_NOT_CERTIFIED',fit_calls=1,
    train_gate_pass=model['training_max_error_px']<=30 and model['optimizer_success'] and not model['limit_active'],
    purpose='falsifiable empirical registration hypothesis, not a lamp timing certificate')
(OUT/'candidate_model.json').write_text(json.dumps(model,indent=2)+'\n',encoding='utf-8')
seal={name:hashlib.sha256((OUT/name).read_bytes()).hexdigest() for name in ('training_points.json','candidate_model.json','training_selection.json','plan.json')}
(OUT/'fit_seal.json').write_text(json.dumps(seal,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:model[k] for k in ('delta_s','training_max_error_px','training_rmse_px','jacobian_rank','optimizer_success','nfev','train_gate_pass')}))
