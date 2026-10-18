"""Fresh frozen-hypothesis vehicle overlays, no refit and no light matching."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile
from PIL import Image,ImageDraw,ImageFont
import numpy as np
from app.core.v9.events import _iter_json_records
from app.experimental.vehicle_clock_alignment import project,inspect_registration_support
from scripts.cardinal_clock_link import ROOT,OUT,read,save,sha

VIDEO=Path('C:/Users/sheld/Downloads/len_sverdl 2025-02-27T10_00_00_2025-02-27T12_00_00.mp4')
ARCHIVE=ROOT.parent/'data/Ленина-Свердловский 27.02.25.zip'
MEMBER='17_2025_2_27_10.json'
MODEL=ROOT/'evidence/local_vehicle_registration_20261015/local_model.json'


def main():
    target=OUT/'sverdlovsky_frozen_review';target.mkdir(exist_ok=False)
    local=ROOT/'.web_runtime/cardinal_clock_link_20261018';local.mkdir(exist_ok=False)
    model=read(MODEL);origin=model['origin_ms']
    source=[];frame_times=[900.,1800.,2700.0333333333]
    save(target/'freeze.json',dict(times_s=frame_times,frozen_model_sha256=sha(MODEL),
        existing_delta_s=model['delta_s'],new_fit_calls=0,phase_predictions_read=False,
        offsets_to_display_s=[0.,model['delta_s']],max_actual_detection_distance_ms=150,
        identity_policy='projected dots are candidate associations, not confirmed car identities'))
    with zipfile.ZipFile(ARCHIVE) as archive:
        with archive.open(MEMBER) as stream:
            for record in _iter_json_records(stream):
                points=[d for d in record.get('detections',[]) if any(abs((d['millis']-origin)/1000-t)<4 for t in frame_times)]
                if points:source.append(dict(id=record['id'],category=record.get('category_name'),
                    zone_in=record.get('zone_in'),zone_out=record.get('zone_out'),detections=points))
    save(local/'fresh_tracks.json',source)
    support=inspect_registration_support(model,source);save(target/'support.json',support)
    assert support['geometry_usable_on_supplied_support']
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',20)
    reports=[]
    for requested in frame_times:
        if requested==1800.:
            folder=local/'frame_1800';folder.mkdir()
            cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-copyts','-ss','1800','-i',str(VIDEO),
                 '-vf','showinfo','-frames:v','1','-fps_mode','passthrough',str(folder/'frame.png')]
            result=subprocess.run(cmd,capture_output=True,timeout=30,check=True)
            (folder/'decode.log').write_bytes(result.stderr)
            match=re.search(rb'n:\s*0\s+pts:\s*(\d+)\s+pts_time:([\d.]+)',result.stderr)
            actual=int(match[1])/90000;frame=folder/'frame.png'
        else:
            label='900' if requested<1000 else '2700'
            frame=ROOT/'.web_runtime/direct_video_truth_20261018/sverdlovsky'/label/'frame.png'
            actual=requested
        row=dict(actual_pts_s=actual,native_frame_sha256=sha(frame),offsets=[])
        for offset in (0.,model['delta_s']):
            at=origin+(actual+offset)*1000;matches=[]
            for track in source:
                d=min(track['detections'],key=lambda p:abs(p['millis']-at))
                if abs(d['millis']-at)>150:continue
                point=project([[d['centroid_x'],d['centroid_y']]],model['homography'])[0]
                if 0<=point[0]<2688 and 0<=point[1]<1520:
                    matches.append(dict(id=track['id'],category=track['category'],zone_in=track['zone_in'],zone_out=track['zone_out'],
                        detection_ms=d['millis'],distance_from_requested_ms=d['millis']-at,
                        raw_centroid=[d['centroid_x'],d['centroid_y']],projected_px=point.tolist()))
            image=Image.open(frame).convert('RGB');draw=ImageDraw.Draw(image)
            draw.rectangle((0,0,1550,48),fill=(10,15,25));draw.text((8,8),f'PTS {actual:.6f}; JSON = old origin + PTS + {offset:.6f}s; CANDIDATE DOTS, NOT CONFIRMED',font=font,fill='white')
            for item in matches:
                x,y=item['projected_px'];color={'N':'#ffce55','E':'#5aebee','W':'#f38bf1','S':'#a1ee68'}.get(item['zone_in'],'white')
                draw.ellipse((x-7,y-7,x+7,y+7),outline=color,width=3)
                text=f"{item['id']} {item['zone_in']}->{item['zone_out']}";bounds=draw.textbbox((x+10,y-18),text,font=font)
                draw.rectangle(bounds,fill=(10,15,25));draw.text((x+10,y-18),text,font=font,fill=color)
            name=f"overlay_{round(actual)}_{offset:.3f}.jpg";image.save(target/name,quality=96)
            row['offsets'].append(dict(offset_s=offset,matches=matches,overlay=name,sha256=sha(target/name)))
        reports.append(row)
        print(json.dumps(dict(pts_s=actual,active_candidates=[len(v['matches']) for v in row['offsets']])),flush=True)
    save(target/'candidates.json',dict(frames=reports,source_member=MEMBER,source_track_subset_sha256=sha(local/'fresh_tracks.json'),
        model_sha256=sha(MODEL),refit=False,clock_mapping_verified=False))


if __name__=='__main__':main()
