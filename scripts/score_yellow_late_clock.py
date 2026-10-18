import numpy as np
from app.experimental.vehicle_clock_alignment import prepare_tracks,predict,conditional_clock_set,_intersect
from scripts.yellow_video_review import OUT
from scripts.build_cardinal_clock_review import MODEL
from scripts.cardinal_clock_link import read,save,sha


def main():
    folder=OUT/'clock3600';frames=read(folder/'motion/frames.json')['rows'];boxes=[[145,100,226,153],[224,124,305,181],[301,150,386,210]]
    points=[]
    for f,b in zip(frames,boxes):
        assert sha(folder/'motion'/f['file'])==f['sha256'];x,y,u,v=b
        points.append(dict(track_id=9925445,actual_media_pts_s=f['pts_s'],bbox_native_px=[1580+x,650+y,1580+u,650+v],
            image_point_px=[1580+(x+u)/2,650+y+.75*(v-y)],frame=f))
    save(folder/'manual_points_sealed.json',dict(rows=points,annotation='UNDOTTED gold SUV body, center X/75% height; three consecutive native frames',new_fit=False))
    model=read(MODEL);record=next(r for r in read(folder/'tracks_clipped.json') if r['id']==9925445)
    tracks=prepare_tracks([record]);truth=np.asarray([p['image_point_px'] for p in points]);results={}
    for delta in [0.,model['delta_s']]:
        errors=np.linalg.norm(predict(tracks,points,model['homography'],delta,model['origin_ms'])-truth,axis=1)
        results[str(delta)]=dict(errors_px=errors.tolist(),max_error_px=float(max(errors)))
    feasible=conditional_clock_set(model,record,points,50)
    old=read(OUT.parent/'cardinal_clock_link_20261018/sverdlovsky_late_control/clock_validation.json')
    common=_intersect(old['all_four_car_conditional_delta_intersection_s'],feasible['delta_sets_s'])
    passed=results[str(model['delta_s'])]['max_error_px']<=50 and bool(common)
    save(folder/'result.json',dict(status='PASS' if passed else 'REJECTED',comparisons=results,
        conditional_clock=feasible,all_five_car_conditional_bounds_s=common,delta_s=model['delta_s'],
        geometry_refit=False,clock_refit=False,no_second_human_point_review=True,
        bounds_semantics=old['bounds_semantics']))
    print(dict(passed=passed,results=results,common=common),flush=True)


if __name__=='__main__':main()
