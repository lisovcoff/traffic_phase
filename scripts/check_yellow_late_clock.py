"""Collect a fresh end-window vehicle control for the unchanged clock."""
import zipfile
from PIL import Image,ImageDraw
from app.core.v9.events import _iter_json_records
from app.experimental.vehicle_clock_alignment import project
from scripts.build_cardinal_clock_review import ARCHIVE,MEMBER,MODEL
from scripts.yellow_video_review import OUT,ROOT
from scripts.cardinal_clock_link import read,save,sha


def main():
    folder=OUT/'clock3600';folder.mkdir(exist_ok=False);model=read(MODEL)
    save(folder/'plan.json',dict(pts_s=3600,frozen_delta_s=model['delta_s'],model_sha256=sha(MODEL),
        new_fits=0,allowance_px=50,purpose='extend independent vehicle-clock support to fresh lamp validation end'))
    records=[]
    with zipfile.ZipFile(ARCHIVE) as z:
        with z.open(MEMBER) as f:
            for r in _iter_json_records(f):
                ds=[d for d in r['detections'] if abs((d['millis']-model['origin_ms'])/1000-3600)<4]
                if len(ds)>1:records.append(dict(id=r['id'],detections=ds,zone_in=r.get('zone_in'),zone_out=r.get('zone_out')))
    save(folder/'tracks_clipped.json',records)
    native=ROOT/'.web_runtime/direct_video_truth_20261018/sverdlovsky/3600/frame.png'
    im=Image.open(native).convert('RGB');draw=ImageDraw.Draw(im);items=[]
    for r in records:
        t=model['origin_ms']+1000*(3600+model['delta_s']);d=min(r['detections'],key=lambda d:abs(d['millis']-t))
        if abs(d['millis']-t)>150:continue
        x,y=project([[d['centroid_x'],d['centroid_y']]],model['homography'])[0]
        if not (0<=x<2688 and 0<=y<1520):continue
        draw.ellipse((x-7,y-7,x+7,y+7),outline='cyan',width=3);draw.text((x+10,y-15),str(r['id']),fill='cyan')
        items.append(dict(id=r['id'],point_px=[x,y]))
    im.save(folder/'candidates.jpg',quality=95)
    save(folder/'candidates.json',dict(items=items,native_sha256=sha(native)))
    print('3600s frozen-clock candidates ready',flush=True)


def motion():
    import re,subprocess
    from scripts.build_cardinal_clock_review import VIDEO
    folder=OUT/'clock3600/motion';folder.mkdir()
    save(folder/'plan.json',dict(track_id_hypothesis=9925445,roi_xywh=[1580,650,650,450],
        target='gold/silver SUV crossing just before the green bus; motion review, no refit',maximum_frames=3))
    cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-copyts','-ss','3599.5','-t','1.1','-i',str(VIDEO),
        '-vf',"crop=650:450:1580:650,trim=start=3599.5:end=3600.6,select='isnan(prev_selected_t)+gte(t-prev_selected_t,0.5)',showinfo",'-frames:v','3','-fps_mode','passthrough',str(folder/'frame_%02d.png')]
    r=subprocess.run(cmd,capture_output=True,check=True,timeout=30);(folder/'decode.log').write_bytes(r.stderr)
    parsed=re.findall(rb'n:\s*(\d+)\s+pts:\s*(\d+)\s+pts_time:([\d.]+)',r.stderr)
    paths=sorted(folder.glob('frame_*.png'));assert len(paths)==3
    frames=[];sheet=Image.new('RGB',(1950,450))
    for i,(p,v) in enumerate(zip(paths,parsed)):
        frames.append(dict(file=p.name,pts_s=int(v[1])/90000,sha256=sha(p)));sheet.paste(Image.open(p),(650*i,0))
    sheet.save(folder/'sheet.png');save(folder/'frames.json',dict(rows=frames,command=cmd))


if __name__=='__main__':
    import sys
    motion() if len(sys.argv)>1 else main()
