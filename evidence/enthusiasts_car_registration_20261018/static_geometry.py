"""Single static registration diagnostic, with no clock estimation or phase data."""
import json,hashlib
from pathlib import Path
import numpy as np
ROOT=Path.cwd();OUT=ROOT/'evidence/enthusiasts_car_registration_20261018'
plan=json.loads((OUT/'static_geometry_plan.json').read_text(encoding='utf-8'))
records=json.loads((ROOT/'.web_runtime/enthusiasts_vehicle_link_20261018/first_entry.json').read_text(encoding='utf-8'))
origin=1740300640994
boxes={7:[1610,825,1790,918],12:[1570,655,1725,722],14:[1660,708,1805,782],19:[1678,519,1743,558]}
rows=[];A=[];b=[]
for track,box in boxes.items():
    ds=next(r for r in records if r['id']==track)['detections']
    ds=[d for d in ds if origin+12000<=d['millis']<=origin+13000]
    point=np.median([[d['centroid_x'],d['centroid_y']] for d in ds],axis=0)
    target=np.array([(box[0]+box[2])/2,box[1]+.75*(box[3]-box[1])])/np.array([2688,1520])
    x,y=point;u,v=target
    A.extend([[x,y,1,0,0,0,-u*x,-u*y],[0,0,0,x,y,1,-v*x,-v*y]]);b.extend([u,v])
    rows.append(dict(track_id=track,source_stationary_feature=point.tolist(),video_bbox_px=box,video_feature_normalized=target.tolist(),source_observations=len(ds)))
params=np.linalg.solve(A,b);H=np.r_[params,1].reshape(3,3)
road=np.array([[d['centroid_x'],d['centroid_y']] for r in records for d in r['detections']]);den=np.c_[road,np.ones(len(road))]@H[2]
report=dict(rows=rows,homography=H.tolist(),linear_system_condition=float(np.linalg.cond(A)),
    road_denominator_extent=[float(min(den)),float(max(den))],road_horizon_crossing=bool(min(den)<0<max(den)),
    exact_fit_is_not_validation=True,clock_parameter_fit_calls=0,production_usable=False,
    source_point_semantics='empirical centroid /75pct bbox feature, not surveyed road contact')
p=OUT/'static_geometry_model.json'
if p.exists():raise ValueError('fresh static geometry result required')
p.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
(OUT/'static_geometry_seal.json').write_text(json.dumps({n:hashlib.sha256((OUT/n).read_bytes()).hexdigest() for n in ('static_geometry_model.json','static_geometry_plan.json')},indent=2)+'\n',encoding='utf-8')
print(json.dumps(report))
