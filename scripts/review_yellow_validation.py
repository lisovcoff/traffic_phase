"""Video-only fresh-window contact sheets; no prediction reads."""
from PIL import Image,ImageDraw
from scripts.yellow_video_review import OUT
from scripts.video_truth_inventory import save
from scripts.sample_video_truth import features,candidates
from scripts.cardinal_clock_link import read


def main():
    for site in ['sverdlovsky','enthusiasts']:
        folder=OUT/site/'validation/0';report=read(folder/'frames.json');rows=report['rows']
        for row in rows:row.update(features(folder/row['file'],site))
        choices=candidates(dict(frames=rows))
        save(folder.parent/'proposals.json',dict(candidates=choices,frames=rows,video_only=True,reviewed_truth=False))
        print(site,choices,flush=True)
        # Show every sampled frame around each proposed red transition. Include
        # enough earlier frames to see green blinking and yellow independently.
        for i,item in enumerate(c for c in choices if c['kind']=='red'):
            t=item['coarse_interval_s'][1];group=[r for r in rows if t-8<=r['pts_s']<=t+1]
            sheet=Image.new('RGB',(1200,((len(group)+7)//8)*170),(20,25,35));draw=ImageDraw.Draw(sheet)
            box=(65,30,125,100) if site=='sverdlovsky' else (27,19,77,84)
            for j,row in enumerate(group):
                im=Image.open(folder/row['file']).crop(box);im=im.resize((im.width*2,im.height*2),Image.Resampling.NEAREST)
                x=j%8*150;y=j//8*170;sheet.paste(im,(x,y+24));draw.text((x,y+3),f"{row['pts_s']:.3f}",fill='white')
            sheet.save(folder.parent/f'red_sheet_{i}.png')


if __name__=='__main__':main()
