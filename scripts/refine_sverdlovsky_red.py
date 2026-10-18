"""Independent video-only red-onsets to check whether a global shift is valid."""
import argparse
import json
from PIL import Image,ImageDraw
from scripts.sample_video_truth import sample
from scripts.video_truth_inventory import OUT,LOCAL,save


def main(window):
    site=OUT/'sverdlovsky'
    rows=json.loads((LOCAL/'sverdlovsky'/window/'frames.json').read_text(encoding='utf8'))['frames']
    candidates=json.loads((site/(window+'_coarse_review')/'candidates.json').read_text(encoding='utf8'))['candidates']
    candidates=[r for r in candidates if r['kind']=='red'];assert len(candidates)==6
    target=site/(window+'_red_native');target.mkdir(exist_ok=False)
    results=[]
    for index,item in enumerate(candidates):
        at=item['coarse_interval_s'][1]
        early=[r for r in rows if at-4<=r['pts_s']<=at and r['red_pixels']>=20 and r['green_pixels']<20]
        start=round(early[0]['pts_s']-1,6);folder=target/f'red_{index:02d}'
        sampled=sample('sverdlovsky',start,start+2,folder,spacing_s=None,max_frames=70)
        frames=sampled['frames']
        new=next((i for i,r in enumerate(frames) if r['red_pixels']>=20 and r['green_pixels']<20),None)
        old=[] if new is None else [i for i in range(new) if frames[i]['red_pixels']<=2 and frames[i]['amber_pixels']>=5]
        if new is None or not old:
            results.append(dict(index=index,status='UNRESOLVED_NO_AMBER_RED_BRACKET'));continue
        before=old[-1]
        def frame(i):return dict(frames[i],file=f'red_{index:02d}/'+frames[i]['file'])
        results.append(dict(index=index,transition='RED_ON',before=frame(before),after=frame(new),
            bracket_s=[frames[before]['pts_s'],frames[new]['pts_s']],
            width_s=frames[new]['pts_s']-frames[before]['pts_s'],status='PROPOSAL_REQUIRES_VISUAL_REVIEW'))
    save(target/'proposals.json',dict(window=window,transitions=results,predictions_read=False))
    sheet=Image.new('RGB',(960,270*len(results)),(24,29,37));draw=ImageDraw.Draw(sheet)
    for j,row in enumerate(results):
        if 'before' not in row:
            draw.text((5,j*270+5),str(row),fill='white');continue
        for col,key in enumerate(('before','after')):
            f=row[key];draw.text((col*360+5,j*270+3),f"{j} {key} {f['pts_s']:.6f}",fill='white')
            with Image.open(target/f['file']) as im:sheet.paste(im.resize((360,240),Image.Resampling.NEAREST),(col*360,j*270+25))
        draw.text((730,j*270+25),f"{row['width_s']*1000:.1f}ms",fill='white')
    sheet.save(target/'endpoints.png')
    print(json.dumps([{k:v for k,v in r.items() if k in ('index','status','bracket_s')} for r in results]),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('window',choices=['calibration','validation'])
    main(p.parse_args().window)
