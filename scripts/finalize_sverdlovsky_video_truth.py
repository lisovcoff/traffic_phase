"""Seal visually reviewed video-only Sverd green-onsets before any model join."""
import hashlib
import json
from pathlib import Path
from PIL import Image,ImageDraw
from scripts.sample_video_truth import sample
from scripts.video_truth_inventory import OUT,save


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    site=OUT/'sverdlovsky'
    adjustment=dict(reason='Validation proposal4 starts after green countdown is already visible. LED dark frames are not a new onset. Capture earlier native window based on video-only previous red and countdown.',
        old_path='validation_native/green_04',new_path='validation_native_recheck/green_04',
        range_s=[3118.5,3120.5],additional_native_frames_max=70,
        model_predictions_consulted=False,budget_deviation='one additional 2s window for an unresolved observation')
    if not (site/'native_refinement_adjustment.json').exists():
        save(site/'native_refinement_adjustment.json',adjustment)
    if not (site/'validation_native_recheck/green_04/frames.json').exists():
        sample('sverdlovsky',3118.5,3120.5,site/'validation_native_recheck/green_04',spacing_s=None,max_frames=70)
    truth=[]
    for window in ('calibration','validation'):
        annotations=[]
        for index in range(6):
            folder=site/(window+'_native')/f'green_{index:02d}'
            data=json.loads((folder/'frames.json').read_text(encoding='utf8'));rows=data['frames']
            rows=[dict(r,source_path=folder/r['file']) for r in rows]
            if window=='validation' and index==4:
                earlier=site/'validation_native_recheck/green_04'
                extra=json.loads((earlier/'frames.json').read_text(encoding='utf8'))['frames']
                rows=sorted(rows+[dict(r,source_path=earlier/r['file']) for r in extra],key=lambda r:r['pts_ticks'])
            # Last confidently red/amber before a green circle. Intermediate
            # mixed exposures stay inside the bracket; LED-off later in green
            # does not reset its start.
            clear=[i for i,r in enumerate(rows) if r['green_pixels']>=8 and r['red_pixels']<20]
            if not clear:raise ValueError('no clear green endpoint')
            after=clear[0]
            old=[i for i in range(after) if rows[i]['red_pixels']>=20 and rows[i]['green_pixels']<=2]
            if not old:raise ValueError('no preceding red/amber endpoint')
            before=old[-1]
            def frame(i):
                p=rows[i]['source_path'];assert sha(p)==rows[i]['sha256']
                return dict(file=p.relative_to(OUT).as_posix(),pts_ticks=rows[i]['pts_ticks'],
                            pts_s=rows[i]['pts_s'],sha256=rows[i]['sha256'])
            annotations.append(dict(index=index,head='H1',section='main',transition='GREEN_ON',
                before=frame(before),after=frame(after),
                bracket_s=[rows[before]['pts_s'],rows[after]['pts_s']],
                width_s=rows[after]['pts_s']-rows[before]['pts_s'],
                visual_review_status='ENDPOINT_SHEET_AWAITING_FINAL_REVIEW',
                interpretation='decoded image appearance bracket; physical exposure and JSON clock uncertainty not included'))
        target=site/(window+'_endpoints_v2.png')
        sheet=Image.new('RGB',(1080,6*270),(24,29,37));draw=ImageDraw.Draw(sheet)
        for j,ann in enumerate(annotations):
            for col,key in enumerate(('before','after')):
                f=ann[key];draw.text((col*360+4,j*270+4),f"{j} {key} {f['pts_s']:.6f}",fill='white')
                with Image.open(OUT/f['file']) as im:sheet.paste(im.resize((360,240),Image.Resampling.NEAREST),(col*360,j*270+25))
            draw.text((730,j*270+25),f"bracket {ann['width_s']*1000:.1f} ms",fill='white')
        sheet.save(target)
        truth.append(dict(window=window,range_s=[900,1500] if window=='calibration' else [2700,3300],
                          transitions=annotations,endpoint_sheet=target.relative_to(OUT).as_posix(),sha256=sha(target)))
    save(site/'video_only_truth_proposal_v2.json',dict(source='local MP4; native PTS',model_predictions_read=False,
        initial_attempt='FAILED: one earlier2s native window contains no visible green circle; combined with later window, conservative wide bracket retained. Original files untouched.',
        head_mapping='video-relative approach from bottom; main straight toward upper right; user confirmed previously',
        json_clock_mapping_accepted=False,physical_switch_accuracy_ms=None,windows=truth))
    print(json.dumps([{w['window']:[r['bracket_s'] for r in w['transitions']]} for w in truth]))


if __name__=='__main__':main()
