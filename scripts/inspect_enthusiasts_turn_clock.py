"""Bounded, no-fit motion inspection after the user's E->E clarification."""
from pathlib import Path
import re
import subprocess
from PIL import Image,ImageDraw
from scripts.cardinal_clock_link import ROOT,read,save,sha,RAW

OUT=ROOT/'evidence/enthusiasts_turn_clock_20261019'
VIDEO=Path('C:/Users/sheld/Downloads/lenina_entuziastov.mp4')


def main():
    OUT.mkdir(exist_ok=False)
    save(OUT/'plan.json',dict(user_reply_verbatim='она хочет повернуть на _E но ждет поток w=>_E чтобы завершить маневр',
        user_followup_verbatim='E→_E',
        interpretation='User confirms the marked video car maneuver, consistent with raw ID7. Identity/time correspondence still empirical.',
        native_pts_request_s=list(range(28,37)),roi_xywh=[1450,700,1050,650],
        native_frame_budget=9,new_fits=0,signal_predictions_used=False,
        purpose='Inspect waiting/resumption of the proposed same car, independently of traffic lights; do not accept a clock from one maneuver.'))
    track=next(r for r in read(RAW) if r['id']==7)
    save(OUT/'source_track7.json',dict(source_json_sha256=sha(RAW),record=track,
        old_provisional_origin_ms=1740300628994,origin_not_accepted=True))
    cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-copyts','-ss','28','-t','8.2','-i',str(VIDEO),
        '-vf',"crop=1050:650:1450:700,trim=start=28:end=36.2,select='isnan(prev_selected_t)+gte(t-prev_selected_t,1)',showinfo",
        '-frames:v','9','-fps_mode','passthrough',str(OUT/'frame_%02d.png')]
    r=subprocess.run(cmd,capture_output=True,timeout=30,check=True);(OUT/'decode.log').write_bytes(r.stderr)
    parsed=re.findall(rb'n:\s*(\d+)\s+pts:\s*(\d+)\s+pts_time:([\d.]+)',r.stderr)
    rows=[];sheet=Image.new('RGB',(1575,1050),(20,25,35));draw=ImageDraw.Draw(sheet)
    for i,(p,row) in enumerate(zip(sorted(OUT.glob('frame_*.png')),parsed)):
        pts=int(row[1])/90000;rows.append(dict(file=p.name,pts_s=pts,pts_ticks=int(row[1]),sha256=sha(p)))
        image=Image.open(p);image.thumbnail((525,325));sheet.paste(image,((i%3)*525,(i//3)*350+25))
        draw.text(((i%3)*525+6,(i//3)*350+6),f'PTS {pts:.6f}; native crop origin1450,700',fill='white')
    assert len(rows)==9
    sheet.save(OUT/'motion_sheet.png');save(OUT/'frames.json',dict(rows=rows,command=cmd))
    print('Collected9 native motion crops, no geometry/clock/phase fit')


if __name__=='__main__':main()
