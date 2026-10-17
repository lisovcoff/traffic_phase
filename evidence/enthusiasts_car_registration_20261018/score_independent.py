"""Frozen-model independent vehicle scoring; never refits from these points."""
import hashlib,json
from pathlib import Path
import numpy as np
from app.experimental.vehicle_clock_alignment import prepare_tracks,predict
ROOT=Path.cwd();OUT=ROOT/'evidence/enthusiasts_car_registration_20261018'
for name,digest in json.loads((OUT/'corrected_seal.json').read_text(encoding='utf-8')).items():
    assert hashlib.sha256((OUT/name).read_bytes()).hexdigest()==digest
if (OUT/'heldout_points.json').exists():raise ValueError('fresh independent scoring required')
model=json.loads((OUT/'corrected_model.json').read_text(encoding='utf-8'))
frames=[r for name in ('frames.json','fine_frames.json') for r in json.loads((OUT/name).read_text(encoding='utf-8'))['frames']]
index={r['requested_s']:r for r in frames}
boxes={7:{13:[1985,882,2097,977],15:[1745,843,1915,932],17:[1673,835,1840,922],24:[1610,825,1790,918],28:[1585,824,1755,915]},
       19:{13:[2064,402,2103,429],15:[1945,442,1998,477],17:[1795,470,1850,505],24:[1678,519,1743,558],28:[1675,517,1746,560]}}
rows=[]
for track,entries in boxes.items():
    for at,b in entries.items():
        f=index[at];rows.append(dict(track_id=track,actual_media_pts_s=f['pts_s'],bbox_native_px=b,
            image_point_px=[(b[0]+b[2])/2,b[1]+.75*(b[3]-b[1])],native_sha256=f['sha256'],source_native_file=f['file'],
            identity_status='independently annotated candidate car sequence; not producer-certified'))
(OUT/'heldout_points.json').write_text(json.dumps(dict(rows=rows,training_model_sha256=hashlib.sha256((OUT/'corrected_model.json').read_bytes()).hexdigest()),indent=2)+'\n',encoding='utf-8')
records=json.loads((ROOT/'.web_runtime/enthusiasts_vehicle_link_20261018/first_entry.json').read_text(encoding='utf-8'))
result=[]
for track in (7,19):
    obs=[r for r in rows if r['track_id']==track]
    predictions=predict(prepare_tracks([r for r in records if r['id']==track]),obs,model['homography'],model['delta_s'],model['origin_ms'])
    errors=np.linalg.norm(predictions-np.asarray([r['image_point_px'] for r in obs]),axis=1)
    result.append(dict(track_id=track,errors_px=errors.tolist(),max_error_px=float(max(errors)),
        predicted_points_px=predictions.tolist(),pass_50px=bool(max(errors)<=50)))
road=np.asarray([[d['centroid_x'],d['centroid_y']] for r in records for d in r['detections']]);h=np.asarray(model['homography']);den=np.c_[road,np.ones(len(road))]@h[2]
report=dict(independent_vehicles=result,all_pass=all(r['pass_50px'] for r in result),refit=False,
    common_road_homogeneous_denominator_extent=[float(min(den)),float(max(den))],
    road_horizon_crossing=bool(min(den)<0<max(den)),accepted_clock_transform=None,
    conclusion='REJECTED if independent errors exceed gate; small training residual is insufficient',
    clock_fits_total=2,phase_fitting_runs=0)
(OUT/'independent_result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report))
