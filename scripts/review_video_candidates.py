"""Conservative color candidates and review sheets; predictions never loaded."""
import argparse
import json
from pathlib import Path
from PIL import Image,ImageDraw
from scripts.video_truth_inventory import save


def state(row):
    # Reject green reflections on a lit red signal, and blinking as a new onset.
    g,r=row['green_pixels'],row['red_pixels']
    if g>=8 and r<20:return 'green'
    if r>=20 and g<20:return 'red'
    return 'unknown'


def review(folder,out):
    data=json.loads((folder/'frames.json').read_text(encoding='utf8'));rows=data['frames']
    previous=None;found=[]
    for i,row in enumerate(rows):
        color=state(row)
        if color=='unknown':continue
        future=rows[i+1:i+4]
        persistent=sum(state(r)==color for r in future)>=2
        if persistent and previous is not None and previous!=color:
            found.append(dict(kind=color,coarse_interval_s=[rows[i-1]['pts_s'],row['pts_s']],
                row_index=i,requires_native_refinement=True,requires_visual_review=True))
        if persistent:previous=color
    out.mkdir(parents=True,exist_ok=False)
    save(out/'candidates.json',dict(site=data['site'],source_frames=folder.as_posix(),
        rule='green>=8px and red<20px; red>=20px and green<20px; 2/3 next frames; UNKNOWN does not change last color',
        candidates=found,video_only=True,reviewed_truth=False))
    for block in range(0,len(found),6):
        sheet=Image.new('RGB',(1080,6*270),(24,29,37));draw=ImageDraw.Draw(sheet)
        for j,item in enumerate(found[block:block+6]):
            i=item['row_index']
            for column,index in enumerate((max(0,i-1),i,min(len(rows)-1,i+3))):
                row=rows[index]
                draw.text((column*360+6,j*270+3),f"{block+j} {item['kind']} PTS {row['pts_s']:.6f} G{row['green_pixels']} R{row['red_pixels']}",fill='white')
                with Image.open(folder/row['file']) as im:
                    im=im.resize((360,240),Image.Resampling.NEAREST);sheet.paste(im,(column*360,j*270+25))
        sheet.save(out/f'review_{block//6}.png')
    print(json.dumps(dict(site=data['site'],candidates=found)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);p.add_argument('out',type=Path)
    args=p.parse_args();review(args.folder,args.out)
