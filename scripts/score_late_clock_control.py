"""Score the sealed late white sedan without refitting clock or geometry."""
import numpy as np
from app.experimental.vehicle_clock_alignment import prepare_tracks,predict,conditional_clock_set,_intersect
from scripts.cardinal_clock_link import OUT,read,save,sha
from scripts.build_cardinal_clock_review import MODEL


def main():
    target=OUT/'sverdlovsky_late_control';data=read(target/'frames.json');identity=data['track_id_hypothesis']
    boxes=[[145,141,246,197],[259,176,362,235],[375,212,476,274]]
    x,y,_,_=data['roi_xywh'];points=[]
    for frame,box in zip(data['frames'],boxes):
        assert sha(OUT/frame['file'])==frame['sha256']
        x1,y1,x2,y2=box
        points.append(dict(track_id=identity,actual_media_pts_s=frame['pts_s'],
            bbox_native_px=[x+x1,y+y1,x+x2,y+y2],image_point_px=[x+(x1+x2)/2,y+y1+.75*(y2-y1)],
            native_crop=frame['file'],native_crop_sha256=frame['sha256']))
    save(target/'manual_points_sealed.json',dict(rows=points,source='UNDOTTED three-frame crop; isolated white sedan moving left-to-right/down',
        feature='center X /75% car-body height',no_second_human_review=True,video_lamps_used=False))
    model=read(MODEL);record=next(r for r in read(target/'tracks_clipped.json') if r['id']==identity)
    tracks=prepare_tracks([record]);truth=np.array([p['image_point_px'] for p in points]);comparisons={}
    for delta in [0.,model['delta_s']]:
        projected=predict(tracks,points,model['homography'],delta,model['origin_ms'])
        errors=np.linalg.norm(projected-truth,axis=1)
        comparisons[str(delta)]=dict(errors_px=errors.tolist(),max_error_px=float(max(errors)),predicted_px=projected.tolist())
    bounds=conditional_clock_set(model,record,points,50)
    earlier=read(OUT/'sverdlovsky_motion/clock_validation.json')
    common=_intersect(earlier['conditional_delta_intersection_s'],bounds['delta_sets_s'])
    passed=comparisons[str(model['delta_s'])]['max_error_px']<=50 and bool(common)
    save(target/'clock_validation.json',dict(status='PASS' if passed else 'REJECTED',comparisons=comparisons,conditional_clock=bounds,
        all_four_car_conditional_delta_intersection_s=common,fixed_delta_s=model['delta_s'],model_sha256=sha(MODEL),
        clock_refit=False,geometry_refit=False,late_control_pts_s=[p['actual_media_pts_s'] for p in points],
        bounds_semantics=earlier['bounds_semantics'],production_enabled=False))
    print(dict(passed=passed,comparisons=comparisons,common=common),flush=True)


if __name__=='__main__':main()
