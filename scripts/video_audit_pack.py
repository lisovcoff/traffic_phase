"""Build a compact local video-audit package for manual/video-vs-trajectory validation."""
from __future__ import annotations
import argparse, json, shutil, subprocess, zipfile
from collections import Counter
from pathlib import Path
from typing import Any

def parse_args() -> argparse.Namespace:
    p=argparse.ArgumentParser(description="Create a compact video audit pack.")
    p.add_argument("--video",type=Path,required=True); p.add_argument("--zip",type=Path,required=True)
    p.add_argument("--output-dir",type=Path,default=Path("video_audit_pack"))
    p.add_argument("--every-seconds",type=float,default=10.0); p.add_argument("--jpeg-quality",type=int,default=5)
    p.add_argument("--event-window",action="append",default=[],metavar="CENTER:BEFORE:AFTER")
    p.add_argument("--event-every-seconds",type=float,default=1.0); p.add_argument("--max-trajectories",type=int,default=20000)
    return p.parse_args()

def require_ffmpeg() -> str:
    exe=shutil.which("ffmpeg")
    if not exe: raise SystemExit("ffmpeg is required and must be on PATH.")
    return exe

def trajectory_start_ms(item: dict[str,Any]) -> int|None:
    starts=[]
    for d in item.get("detections") or []:
        if not isinstance(d,dict): continue
        try: starts.append(int(d["millis"]))
        except (KeyError,TypeError,ValueError): pass
    if starts: return min(starts)
    try: return int(item["millis"])
    except (KeyError,TypeError,ValueError): return None

def trajectory_stats(zip_path:Path,max_trajectories:int)->dict[str,Any]:
    members=[]; starts=[]; dirs=Counter(); cars_total=0
    with zipfile.ZipFile(zip_path) as archive:
        infos=[i for i in archive.infolist() if not i.is_dir() and i.filename.lower().endswith(".json")]
        for info in infos:
            with archive.open(info) as raw: value=json.load(raw)
            rows=value if isinstance(value,list) else []
            rows=[x for x in rows[:max_trajectories] if isinstance(x,dict)]
            cars=[x for x in rows if x.get("category_name")=="car"]
            car_starts=[s for x in cars if (s:=trajectory_start_ms(x)) is not None]
            cars_total+=len(cars); starts.extend(car_starts)
            for x in cars:
                if x.get("zone_in") and x.get("zone_out"): dirs[f"{x['zone_in']}->{x['zone_out']}"]+=1
            members.append({"name":info.filename,"trajectories_inspected":len(rows),"cars":len(cars),
                            "start_min_ms":min(car_starts) if car_starts else None,
                            "start_max_ms":max(car_starts) if car_starts else None})
    hist={}
    for s in starts:
        m=(s//60000)*60000; hist[str(m)]=hist.get(str(m),0)+1
    return {"zip":str(zip_path.resolve()),"json_members":len(infos),"members":members,
            "cars_inspected":cars_total,"car_start_min_ms":min(starts) if starts else None,
            "car_start_max_ms":max(starts) if starts else None,
            "car_direction_counts":dict(dirs.most_common()),
            "car_start_histogram_1min":dict(sorted(hist.items(),key=lambda x:int(x[0])))}

def run_ffmpeg(ffmpeg,video,pattern,fps,quality,start=None,duration=None):
    cmd=[ffmpeg,"-hide_banner","-loglevel","error","-y"]
    if start is not None: cmd += ["-ss",f"{start:.3f}"]
    cmd += ["-i",str(video)]
    if duration is not None: cmd += ["-t",f"{duration:.3f}"]
    cmd += ["-vf",f"fps={fps:g}","-q:v",str(max(2,min(31,quality))),str(pattern)]
    subprocess.run(cmd,check=True)

def parse_window(value:str):
    try: center,before,after=(float(x) for x in value.split(":"))
    except ValueError as exc: raise SystemExit(f"Invalid --event-window {value!r}; use CENTER:BEFORE:AFTER") from exc
    if min(center,before,after)<0: raise SystemExit("event-window values must be non-negative")
    return center,before,after

def main():
    args=parse_args(); ffmpeg=require_ffmpeg()
    if not args.video.is_file(): raise SystemExit(f"Video not found: {args.video}")
    if not args.zip.is_file(): raise SystemExit(f"ZIP not found: {args.zip}")
    if args.every_seconds<=0 or args.event_every_seconds<=0: raise SystemExit("Frame intervals must be positive.")
    if not 2<=args.jpeg_quality<=31: raise SystemExit("--jpeg-quality must be between 2 and 31.")
    out=args.output_dir.resolve(); (out/"overview").mkdir(parents=True,exist_ok=True); (out/"events").mkdir(exist_ok=True)
    stats=trajectory_stats(args.zip,args.max_trajectories)
    run_ffmpeg(ffmpeg,args.video,out/"overview"/"frame_%06d.jpg",1.0/args.every_seconds,args.jpeg_quality)
    windows=[]
    for i,raw in enumerate(args.event_window,1):
        center,before,after=parse_window(raw); start=max(0,center-before); d=out/"events"/f"event_{i:02d}"; d.mkdir(parents=True,exist_ok=True)
        run_ffmpeg(ffmpeg,args.video,d/"frame_%06d.jpg",1.0/args.event_every_seconds,args.jpeg_quality,start,before+after)
        windows.append({"center_seconds":center,"before_seconds":before,"after_seconds":after,"video_start_seconds":start,
                        "duration_seconds":before+after,"frame_interval_seconds":args.event_every_seconds,"directory":str(d.relative_to(out))})
    manifest={"source_video":str(args.video.resolve()),"source_zip":str(args.zip.resolve()),
              "video_frames":{"every_seconds":args.every_seconds,"jpeg_quality":args.jpeg_quality},
              "event_windows":windows,"trajectory_stats":stats,
              "notes":["Source video is not copied.","Video timestamps are relative to video start.",
                       "Trajectory millis may not equal wall-clock video time for offline accident processing.",
                       "Establish a video/trajectory time offset before interpreting event windows."]}
    (out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"[video-audit] output: {out}"); print(f"[video-audit] cars inspected: {stats['cars_inspected']}")
    print(f"[video-audit] overview interval: {args.every_seconds}s"); print("[video-audit] source video was not copied")

if __name__=="__main__": main()
