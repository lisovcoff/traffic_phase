"""Score three fresh moving cars under an unchanged geometry/clock hypothesis."""
import copy
import json
from pathlib import Path
from PIL import Image,ImageDraw
import numpy as np
from app.experimental.vehicle_clock_alignment import prepare_tracks,predict,conditional_clock_set,_intersect
from scripts.cardinal_clock_link import ROOT,OUT,read,save,sha

# Manual native car-body boxes from the UNDOTTED motion crops. Point convention
# is the old declared center X /75% height; no coordinates copied from projected dots.
BOXES={9917625:[[109,91,196,143],[239,135,330,188],[375,181,469,232]],
       9919993:[[100,104,193,166],[185,132,280,193],[283,166,380,230]],
       9922632:[[129,110,204,156],[214,138,292,184],[300,166,384,215]]}


def main():
    source=OUT/'sverdlovsky_motion';frames=read(source/'frames.json')['cases']
    modelpath=ROOT/'evidence/local_vehicle_registration_20261015/local_model.json'
    model=read(modelpath);records=read(OUT/'sverdlovsky_frozen_review/source_tracks_clipped.json')
    records={r['id']:r for r in records if r['id'] in BOXES}
    annotations=[]
    for case in frames:
        identity=case['track_id_hypothesis'];x,y,w,h=case['roi_xywh']
        for frame,box in zip(case['frames'],BOXES[identity]):
            x1,y1,x2,y2=box;path=OUT/frame['file'];assert sha(path)==frame['sha256']
            annotations.append(dict(track_id=identity,actual_media_pts_s=frame['pts_s'],
                bbox_native_px=[x+x1,y+y1,x+x2,y+y2],
                image_point_px=[x+(x1+x2)/2,y+y1+.75*(y2-y1)],
                native_crop=frame['file'],native_crop_sha256=frame['sha256'],
                car_feature='manually reviewed same moving car across three adjacent frames',
                appearance={9917625:'dark hatchback',9919993:'white SUV with roof rails',9922632:'gray-green MPV, left of two white cars'}[identity]))
    sealed=dict(rows=annotations,annotations_from_undotted_crops=True,
        old_geometry_not_refit=True,allowance_px=50,source_model_sha256=sha(modelpath),
        no_second_human_review=True,video_lamp_states_used=False)
    if (source/'manual_points_sealed.json').exists():assert read(source/'manual_points_sealed.json')==sealed
    else:save(source/'manual_points_sealed.json',sealed)
    trackmap=prepare_tracks(list(records.values()));results=[];common=[model['common_observed_delta_bounds_s']]
    for identity in BOXES:
        points=[p for p in annotations if p['track_id']==identity]
        target=np.asarray([p['image_point_px'] for p in points])
        estimates={}
        for delta in (0.,model['delta_s']):
            projected=predict(trackmap,points,model['homography'],delta,model['origin_ms'])
            errors=np.linalg.norm(projected-target,axis=1)
            estimates[str(delta)]=dict(errors_px=errors.tolist(),max_error_px=float(max(errors)),predicted_px=projected.tolist())
        feasible=conditional_clock_set(model,records[identity],points,50)
        common=_intersect(common,feasible['delta_sets_s'])
        results.append(dict(track_id=identity,observations=len(points),comparisons=estimates,conditional_clock=feasible))
    frozen_pass=all(r['comparisons'][str(model['delta_s'])]['max_error_px']<=50 for r in results)
    zero_pass=all(r['comparisons']['0.0']['max_error_px']<=50 for r in results)
    result=dict(status='EMPIRICAL_FROZEN_HYPOTHESIS_PASSES' if frozen_pass and common else 'REJECTED',
        cars=results,all_fresh_car_observations=len(annotations),fixed_delta_s=model['delta_s'],
        zero_delta_passes=zero_pass,conditional_delta_intersection_s=common,
        clock_scale_drift_fitted=False,clock_refit=False,geometry_refit=False,
        empirical_support='Three fresh distinct cars at15/30/45min, same-car motion over1s percar; fixed pre-existing model only.',
        bounds_semantics='conditional on fixed geometry, manual identity/feature and50px allowance; not an absolute hardware-clock certificate',
        source_clock_device_accuracy_calibrated=False,production_enabled=False)
    save(source/'clock_validation.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='cars'}),flush=True)
    print(json.dumps([(r['track_id'],r['comparisons'][str(model['delta_s'])]['max_error_px']) for r in results]),flush=True)


if __name__=='__main__':main()
