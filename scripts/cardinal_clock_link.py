"""Preserve cardinal reply and one wider-support development registration attempt."""
import hashlib
import json
from pathlib import Path
import time
from app.experimental.vehicle_clock_alignment import fit_training,inspect_registration_support

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/cardinal_clock_link_20261018'
RAW=ROOT/'.web_runtime/enthusiasts_vehicle_link_20261018/first_entry.json'
OLD=ROOT/'evidence/enthusiasts_car_registration_20261018'


def read(path):return json.loads(path.read_text(encoding='utf8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf8',newline='\n') as f:json.dump(data,f,ensure_ascii=False,indent=2)


def main():
    OUT.mkdir(exist_ok=False)
    save(OUT/'user_orientation.json',dict(
        reply_verbatim='на светдловском - снизу n, справа e, слева w, сверху s\nна энтузиастов сверху n, слева w',
        sverdlovsky=dict(bottom='N',right='E',left='W',top='S'),
        enthusiasts=dict(top='N',left='W',opposites_inferred=dict(right='E',bottom='S')),
        scope='image-relative approach names; head assignments require view/traffic interpretation',
        clock_mapping_verified=False,production_model_changed=False))
    points=read(OLD/'corrected_points.json')['rows']
    points+= [r for r in read(OLD/'heldout_points.json')['rows'] if r['track_id']==7]
    records=read(RAW);selected=[r for r in records if r['id'] in [2,6,7]]
    sourcehash=sha(RAW)
    assert sourcehash=='f71585ad7a887514d6fd254cdf86b3e08be54e915ca032f42ce08123efe501f6'
    save(OUT/'freeze.json',dict(source_sha256=sourcehash,
        training_ids=[2,6,7],development_reuse=True,new_controls_if_admitted=[36,116],
        points=points,origin_ms=1740300628994,delta_bounds_s=[-5,5],max_seconds=15,max_nfev=1000,
        max_solver_calls=1,train_pixel_gate=30,control_pixel_gate=50,
        independent_clock_fit_from_lights=False,phase_predictions_read=False,
        code_sha256=sha(ROOT/'app/experimental/vehicle_clock_alignment.py')))
    began=time.monotonic()
    try:
        model=fit_training(selected,points,training_ids=[2,6,7],heldout_id=36,
            origin_ms=1740300628994,delta_bounds=(-5,5),max_seconds=15,max_nfev=1000)
        save(OUT/'candidate_model.json',model)
        support=inspect_registration_support(model,records);save(OUT/'support.json',support)
        admitted=model['training_max_error_px']<=30 and support['geometry_usable_on_supplied_support']
        result=dict(status='DEVELOPMENT_GEOMETRY_ADMITTED_PENDING_NEW_CONTROLS' if admitted else 'REJECTED',
            training_max_error_px=model['training_max_error_px'],training_rmse_px=model['training_rmse_px'],
            delta_s=model['delta_s'],support_status=support['status'],runtime_s=time.monotonic()-began,
            independent_clock_mapping_verified=False,production_enabled=False,phase_fits=0)
    except ValueError as exc:
        result=dict(status='REJECTED',reason=str(exc),runtime_s=time.monotonic()-began,
            independent_clock_mapping_verified=False,production_enabled=False,phase_fits=0)
    save(OUT/'result.json',result);print(json.dumps(result),flush=True)


if __name__=='__main__':main()
