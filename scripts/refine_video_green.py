"""Refine video-only green candidates into native-frame review proposals."""
import argparse
import json
from pathlib import Path
from PIL import Image,ImageDraw
from scripts.sample_video_truth import sample
from scripts.review_video_candidates import state
from scripts.video_truth_inventory import ROOT,OUT,LOCAL,save


def refine(site,window,variant=''):
    suffix='_'+variant if variant else ''
    source=LOCAL/site/(window+suffix)
    coarse=json.loads((source/'frames.json').read_text(encoding='utf8'))['frames']
    choices=json.loads((OUT/site/(window+'_coarse_review'+suffix)/'candidates.json').read_text(encoding='utf8'))['candidates']
    choices=[c for c in choices if c['kind']=='green']
    assert len(choices)<=40
    target=OUT/site/(window+'_native'+suffix);target.mkdir(exist_ok=False)
    proposals=[]
    for number,item in enumerate(choices):
        at=item['coarse_interval_s'][1]
        early=[r for r in coarse if at-5<=r['pts_s']<=at and state(r)=='green']
        first=early[0]['pts_s'];start=round(first-1,6)
        folder=target/f'green_{number:02d}'
        result=sample(site,start,start+2,folder,spacing_s=None,max_frames=70)
        rows=result['frames']
        onset=next((i for i,r in enumerate(rows) if state(r)=='green'),None)
        if onset is None or onset==0:
            proposals.append(dict(index=number,status='UNRESOLVED_NO_BRACKET',range_s=result['range_s']))
            continue
        old=[i for i in range(onset) if rows[i]['green_pixels']<=2 and rows[i]['red_pixels']>=20]
        if not old:
            proposals.append(dict(index=number,status='UNRESOLVED_NO_PRIOR_RED',range_s=result['range_s']))
            continue
        before=old[-1] if old else onset-1
        def frame(index):return dict(rows[index],file=f'green_{number:02d}/'+rows[index]['file'])
        proposals.append(dict(index=number,status='PROPOSAL_REQUIRES_VISUAL_REVIEW',
            before=frame(before),after=frame(onset),
            bracket_s=[rows[before]['pts_s'],rows[onset]['pts_s']],
            width_s=rows[onset]['pts_s']-rows[before]['pts_s'],
            mixed_frames=[frame(i) for i in range(before+1,onset)],
            later=[frame(i) for i in (min(len(rows)-1,onset+5),min(len(rows)-1,onset+15))]))
    save(target/'proposals.json',dict(site=site,window=window,main_green_onsets=proposals,
        prediction_data_read=False,clock_mapping_accepted=False,reviewed_truth=False))
    for offset in range(0,len(proposals),6):
        group=proposals[offset:offset+6]
        sheet=Image.new('RGB',(1440,270*len(group)),(24,29,37));draw=ImageDraw.Draw(sheet)
        for j,item in enumerate(group):
            if 'before' not in item:continue
            for column,frame in enumerate([item['before'],item['after'],*item['later']]):
                draw.text((column*360+4,j*270+4),f"{item['index']} {frame['pts_s']:.6f} G{frame['green_pixels']} R{frame['red_pixels']}",fill='white')
                with Image.open(target/frame['file']) as image:
                    sheet.paste(image.resize((360,240),Image.Resampling.NEAREST),(column*360,j*270+25))
        sheet.save(target/f'proposal_sheet_{offset//6}.png')
    print(json.dumps(dict(site=site,window=window,proposals=[{k:v for k,v in p.items() if k in ('index','status','bracket_s','width_s')} for p in proposals])),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('site');p.add_argument('window',choices=['calibration','validation'])
    p.add_argument('--variant',default='')
    a=p.parse_args();refine(a.site,a.window,a.variant)
