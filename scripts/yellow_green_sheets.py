from PIL import Image,ImageDraw
from scripts.yellow_video_review import OUT
from scripts.cardinal_clock_link import read


def main():
    for site in ['sverdlovsky','enthusiasts']:
        folder=OUT/site/'validation/0';rows=read(folder/'frames.json')['rows']
        groups=[(a,[r for r in rows if a<=r['pts_s']<a+25]) for a in [3300,3400,3500]]
        for a,group in groups:
            sheet=Image.new('RGB',(1200,((len(group)+7)//8)*170),(20,25,35));d=ImageDraw.Draw(sheet)
            box=(65,30,125,100) if site=='sverdlovsky' else (27,19,77,84)
            for i,r in enumerate(group):
                im=Image.open(folder/r['file']).crop(box);im=im.resize((im.width*2,im.height*2),Image.Resampling.NEAREST)
                x=i%8*150;y=i//8*170;sheet.paste(im,(x,y+24));d.text((x,y+4),f"{r['pts_s']:.3f}",fill='white')
            sheet.save(folder.parent/f'green_sheet_{a}.png')


if __name__=='__main__':main()
