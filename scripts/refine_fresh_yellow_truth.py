"""Refine video-only fresh proposals; no predicted times or fitting."""
import re
import subprocess
from scripts.yellow_video_review import OUT,ROIS,SOURCES
from scripts.video_truth_inventory import save,sha

TARGETS={'sverdlovsky':[3319,3419,3519,3367,3467,3567,3370,3470,3570],
         'enthusiasts':[3407.5,3507.2,3367.9,3468.1,3371.4,3471.1,3570.8]}


def main(site):
    base=OUT/site/'validation_native';base.mkdir(parents=True,exist_ok=False)
    save(base/'plan.json',dict(targets_s=TARGETS[site],basis='reviewed video-only coarse contact sheets, no prediction read',
        native_window_s=.8,maximum_frames_each=26,ambiguous_first_Enth_green_left_broad=True))
    for i,t in enumerate(TARGETS[site]):
        folder=base/str(i);folder.mkdir();a=t-.4;b=t+.4;x,y,w,h=ROIS[site]['crop']
        cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-copyts','-ss',str(a),'-t','0.8','-i',str(SOURCES[site]),
            '-vf',f'crop={w}:{h}:{x}:{y},trim=start={a}:end={b},showinfo','-frames:v','26','-fps_mode','passthrough',str(folder/'frame_%05d.png')]
        r=subprocess.run(cmd,capture_output=True,check=True,timeout=30);(folder/'decode.log').write_bytes(r.stderr)
        parsed=re.findall(rb'n:\s*(\d+)\s+pts:\s*(\d+)\s+pts_time:([\d.]+)',r.stderr)
        paths=sorted(folder.glob('frame_*.png'));assert len(parsed)>=len(paths)>0
        rows=[dict(file=p.name,pts_s=int(v[1])/90000,pts_ticks=int(v[1]),sha256=sha(p)) for p,v in zip(paths,parsed)]
        save(folder/'frames.json',dict(rows=rows,command=cmd))
    print('native fresh video refinements collected',site,flush=True)


if __name__=='__main__':
    import sys
    main(sys.argv[1])
