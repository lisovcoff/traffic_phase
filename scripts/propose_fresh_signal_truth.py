"""Explicit, reviewable video endpoints before prediction evaluation."""
from PIL import Image,ImageDraw
from scripts.yellow_video_review import OUT
from scripts.cardinal_clock_link import read
from scripts.video_truth_inventory import save
from scripts.sample_video_truth import features


def main():
    for site in ['sverdlovsky','enthusiasts']:
        root=OUT/site;native=root/'validation_native';coarse=root/'validation/0';rows=[]
        def frame(folder,near):
            data=read(folder/'frames.json')['rows'];r=min(data,key=lambda r:abs(r['pts_s']-near))
            return dict(r,file=(folder/r['file']).relative_to(OUT).as_posix())
        def add(color,index,folder,before,after,confidence='HIGH'):
            a,b=frame(folder,before),frame(folder,after)
            assert a['pts_s']<b['pts_s'];rows.append(dict(color=color,index=index,
                before=a,after=b,bracket_s=[a['pts_s'],b['pts_s']],confidence=confidence))
        if site=='sverdlovsky':
            for i in range(3):
                folder=native/str(i);data=read(folder/'frames.json')['rows']
                on=next(j for j,r in enumerate(data) if (f:=features(folder/r['file'],site))['green_pixels']>=8 and f['red_pixels']<20)
                old=[r for r in data[:on] if features(folder/r['file'],site)['red_pixels']>=20]
                add('GREEN',i,folder,old[-1]['pts_s'],data[on]['pts_s'])
            for i,(lo,hi) in enumerate([(3366.967,3367.2),(3466.967,3467.2),(3567.067,3567.167)]):
                add('YELLOW',i,native/str(i+3),lo,hi)
            add('RED',0,coarse,3369.6,3370.6,'MEDIUM_LED_ALIAS')
            for i in [1,2]:
                folder=native/str(i+6);data=read(folder/'frames.json')['rows']
                on=next(j for j,r in enumerate(data) if features(folder/r['file'],site)['red_pixels']>=20)
                add('RED',i,folder,data[on-1]['pts_s'],data[on]['pts_s'])
            unresolved=[dict(color='RED_YELLOW',reason='countdown and mixed/LED exposures do not establish a reviewed onset;2s remains normative prior')]
        else:
            add('GREEN',0,coarse,3306.533,3315.033,'MEDIUM_DIM_WIDE_BRACKET')
            add('GREEN',1,coarse,3406.733,3408.733,'MEDIUM_DIM_WIDE_BRACKET')
            folder=native/'1';data=read(folder/'frames.json')['rows'];on=next(j for j,r in enumerate(data) if features(folder/r['file'],site)['green_pixels']>=20 and features(folder/r['file'],site)['red_pixels']<20)
            add('GREEN',2,folder,data[on-1]['pts_s'],data[on]['pts_s'])
            add('YELLOW',0,native/'2',3367.933,3368.033)
            add('YELLOW',1,native/'3',3467.833,3467.967)
            add('RED',0,coarse,3370.167,3374.167,'MEDIUM_DIM_WIDE_BRACKET')
            folder=native/'5';data=read(folder/'frames.json')['rows'];on=next(j for j,r in enumerate(data) if features(folder/r['file'],site)['red_pixels']>=20)
            add('RED',1,folder,data[on-1]['pts_s'],data[on]['pts_s'])
            add('RED',2,coarse,3570.533,3571.533,'MEDIUM_DIM_WIDE_BRACKET')
            unresolved=[dict(color='YELLOW',index=2,reason='LED dark phase prevents confident yellow endpoint'),dict(color='RED_YELLOW',reason='no independently reviewed onset;2s remains normative prior')]
        save(root/'fresh_truth_proposals.json',dict(rows=rows,unresolved=unresolved,predictions_read=False,final_visual_review=False))
        sheet=Image.new('RGB',(900,180*len(rows)),(20,25,35));draw=ImageDraw.Draw(sheet)
        box=(65,30,125,100) if site=='sverdlovsky' else (27,19,77,84)
        for j,row in enumerate(rows):
            draw.text((410,j*180+15),f"{row['color']} {row['index']} {row['confidence']}",fill='white')
            for i,key in enumerate(['before','after']):
                r=row[key];im=Image.open(OUT/r['file']).crop(box);im=im.resize((im.width*2,im.height*2),Image.Resampling.NEAREST)
                x=i*200;sheet.paste(im,(x,j*180+30));draw.text((x,j*180+5),f"{key} {r['pts_s']:.6f}",fill='white')
        sheet.save(root/'fresh_endpoints.png')
    print('Fresh endpoint proposals prepared; no predictions read')


if __name__=='__main__':main()
