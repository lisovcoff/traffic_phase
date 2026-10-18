"""Extend the unchanged clock check beyond the last lamp validation onset."""
import re
import subprocess
import zipfile
from PIL import Image, ImageDraw
from app.core.v9.events import _iter_json_records
from app.experimental.vehicle_clock_alignment import project
from scripts.build_cardinal_clock_review import VIDEO, ARCHIVE, MEMBER, MODEL
from scripts.cardinal_clock_link import ROOT, OUT, read, save, sha


def main():
    target=OUT/'sverdlovsky_late_control';target.mkdir(exist_ok=False)
    save(target/'plan.json',dict(reason='Previous fresh checks stop at2700s; lamp evaluation extends to3219s. Check3300s to avoid extrapolating clock support.',
        at_pts_s=3300,new_fits=0,maximum_native_frames=4,allowance_px=50,
        identity_policy='review an undotted moving car across three frames; no adjustment of frozen H/delta',
        selection_uses_lamp_predictions=False))
    model=read(MODEL);origin=model['origin_ms'];records=[]
    with zipfile.ZipFile(ARCHIVE) as archive:
        with archive.open(MEMBER) as stream:
            for r in _iter_json_records(stream):
                ds=[d for d in r.get('detections',[]) if abs((d['millis']-origin)/1000-3300)<4]
                if len(ds)>1:records.append(dict(id=r['id'],zone_in=r.get('zone_in'),zone_out=r.get('zone_out'),detections=ds))
    save(target/'tracks_clipped.json',records)
    cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-copyts','-ss','3300','-i',str(VIDEO),'-vf','showinfo','-frames:v','1','-fps_mode','passthrough',str(target/'native.png')]
    result=subprocess.run(cmd,capture_output=True,check=True,timeout=30)
    (target/'decode.log').write_bytes(result.stderr)
    match=re.search(rb'n:\s*0\s+pts:\s*(\d+)\s+pts_time:([\d.]+)',result.stderr)
    pts=int(match[1])/90000;at=origin+1000*(pts+model['delta_s'])
    im=Image.open(target/'native.png').convert('RGB');draw=ImageDraw.Draw(im);candidates=[]
    for r in records:
        d=min(r['detections'],key=lambda d:abs(d['millis']-at))
        if abs(d['millis']-at)>150:continue
        x,y=project([[d['centroid_x'],d['centroid_y']]],model['homography'])[0]
        if not (0<=x<2688 and 0<=y<1520):continue
        draw.ellipse((x-7,y-7,x+7,y+7),outline='cyan',width=3)
        draw.text((x+10,y-15),str(r['id']),fill='cyan',stroke_width=1)
        candidates.append(dict(id=r['id'],raw_movement=[r['zone_in'],r['zone_out']],projected_px=[x,y]))
    im.save(target/'candidates.jpg',quality=96)
    save(target/'candidates.json',dict(pts_s=pts,source_frame_sha256=sha(target/'native.png'),model_sha256=sha(MODEL),candidates=candidates))
    print('Collected fresh3300s context; frozen geometry/clock unchanged.',flush=True)


def motion():
    target=OUT/'sverdlovsky_late_control'
    save(target/'motion_plan.json',dict(track_id_hypothesis=9924578,roi_xywh=[1810,660,560,350],
        reason='Isolated white sedan crossing in the foreground; no result-based identity replacement',new_fits=0))
    folder=target/'motion';folder.mkdir(exist_ok=False)
    cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-copyts','-ss','3299.5','-t','1.1','-i',str(VIDEO),
         '-vf',"crop=560:350:1810:660,trim=start=3299.5:end=3300.6,select='isnan(prev_selected_t)+gte(t-prev_selected_t,0.5)',showinfo",
         '-frames:v','3','-fps_mode','passthrough',str(folder/'frame_%02d.png')]
    result=subprocess.run(cmd,capture_output=True,check=True,timeout=30)
    (folder/'decode.log').write_bytes(result.stderr)
    parsed=re.findall(rb'n:\s*(\d+)\s+pts:\s*(\d+)\s+pts_time:([\d.]+)',result.stderr)
    frames=[];sheet=Image.new('RGB',(1680,350))
    for i,(path,row) in enumerate(zip(sorted(folder.glob('frame_*.png')),parsed)):
        frames.append(dict(file=path.relative_to(OUT).as_posix(),pts_s=int(row[1])/90000,sha256=sha(path)))
        sheet.paste(Image.open(path),(560*i,0))
    assert len(frames)==3
    sheet.save(target/'motion_sheet.png')
    save(target/'frames.json',dict(track_id_hypothesis=9924578,roi_xywh=[1810,660,560,350],frames=frames,command=cmd))


if __name__=='__main__':
    import sys
    (motion if len(sys.argv)>1 and sys.argv[1]=='motion' else main)()
