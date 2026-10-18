"""Native refinement selected by direct coarse-video review, never phase fitting."""
import argparse
import json
from PIL import Image,ImageDraw
from scripts.sample_video_truth import sample
from scripts.video_truth_inventory import OUT,LOCAL,save

# Positions chosen from visible red/amber and green lens crops, not model output.
WINDOWS={
 'calibration':[(908,910),(1007.8,1009.8),(1107.8,1109.8),
                (1207.8,1209.8),(1307.8,1309.8),(1405.8,1407.8)],
 'validation':[(2705.8,2707.8),(2805.8,2807.8),(2905.8,2907.8),
               (3005.8,3007.8),(3105.8,3107.8),(3205.8,3207.8)]}


def run(window):
    target=OUT/'enthusiasts'/(window+'_native_reviewed');target.mkdir(exist_ok=False)
    save(target/'selection.json',dict(selection='Codex visual coarse-lens review',windows=WINDOWS[window],
        excluded='Spurious cyan pixels with red countdown/old red state; not physical green.',
        last_validation='Coarse candidate3205.13 is false; observed old red/amber still at3206.633, next clear green3207.133.',
        predictions_read=False))
    proposed=[]
    for index,(start,end) in enumerate(WINDOWS[window]):
        folder=target/f'green_{index:02d}'
        result=sample('enthusiasts',start,end,folder,spacing_s=None,max_frames=70)
        rows=result['frames']
        # Require a strongly visible cyan lens. Low counts are red-phase color
        # reflections and must not become green merely because R LED is dark.
        green=[i for i,r in enumerate(rows) if r['green_pixels']>=25 and r['red_pixels']<20]
        if not green:
            proposed.append(dict(index=index,status='UNRESOLVED_NO_CLEAR_GREEN',range_s=[start,end]));continue
        after=green[0]
        old=[i for i in range(after) if rows[i]['red_pixels']>=20 and rows[i]['green_pixels']<20]
        if not old:
            proposed.append(dict(index=index,status='UNRESOLVED_NO_PRIOR_RED',range_s=[start,end]));continue
        before=old[-1]
        def frame(i):return dict(rows[i],file=f'green_{index:02d}/'+rows[i]['file'])
        proposed.append(dict(index=index,status='PROPOSAL_REQUIRES_VISUAL_REVIEW',before=frame(before),after=frame(after),
            bracket_s=[rows[before]['pts_s'],rows[after]['pts_s']],
            width_s=rows[after]['pts_s']-rows[before]['pts_s']))
    save(target/'proposals.json',dict(site='enthusiasts',window=window,transitions=proposed,
        predictions_read=False,clock_mapping_accepted=False,reviewed_truth=False))
    sheet=Image.new('RGB',(960,270*len(proposed)),(24,29,37));draw=ImageDraw.Draw(sheet)
    for j,ann in enumerate(proposed):
        if 'before' not in ann:
            draw.text((5,j*270+5),str(ann),fill='white');continue
        for col,key in enumerate(('before','after')):
            f=ann[key];draw.text((col*360+5,j*270+3),f"{j} {key} {f['pts_s']:.6f}",fill='white')
            with Image.open(target/f['file']) as im:sheet.paste(im.resize((360,240),Image.Resampling.NEAREST),(col*360,j*270+25))
        draw.text((730,j*270+25),f"{ann['width_s']*1000:.1f}ms",fill='white')
    sheet.save(target/'endpoints.png')
    print(json.dumps([{k:v for k,v in r.items() if k in ('index','status','bracket_s')} for r in proposed]),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('window',choices=WINDOWS)
    run(p.parse_args().window)
