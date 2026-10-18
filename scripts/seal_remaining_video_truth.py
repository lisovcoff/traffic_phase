"""Preserve reviewed dim-lamp brackets; no phase predictions or clock fitting."""
import hashlib
import json
from pathlib import Path
from PIL import Image,ImageDraw
from scripts.video_truth_inventory import OUT,LOCAL,save


def load(p):return json.loads(p.read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    site=OUT/'enthusiasts';windows=[]
    for window in ('calibration','validation'):
        folder=site/(window+'_native_reviewed');data=load(folder/'proposals.json')
        rows=[]
        for item in data['transitions']:
            index=item['index'];native=folder/f'green_{index:02d}';frames=load(native/'frames.json')['frames']
            if 'before' in item:
                before=dict(item['before'],path=folder/item['before']['file'])
                after=dict(item['after'],path=folder/item['after']['file'])
                confidence='HIGH'
            else:
                # These four proposals were inspected as native old/new crops.
                # Select their strongest visible green endpoint and a preceding
                # visible red. When LED alias hides all native old red frames,
                # use an earlier real coarse frame, preserving the wide gap.
                after=dict(max(frames[25:],key=lambda r:r['green_pixels']))
                after['path']=native/after['file']
                old=[dict(r,path=native/r['file']) for r in frames
                     if r['pts_s']<after['pts_s'] and r['red_pixels']>=20 and r['green_pixels']<20]
                if not old:
                    coarse=load(LOCAL/'enthusiasts'/(window+'_v2')/'frames.json')['frames']
                    old=[dict(r,path=LOCAL/'enthusiasts'/(window+'_v2')/r['file']) for r in coarse
                         if after['pts_s']-5<r['pts_s']<after['pts_s'] and r['red_pixels']>=20 and r['green_pixels']<20]
                if not old:raise ValueError('no reviewed preceding red endpoint')
                before=old[-1];confidence='MEDIUM_DIM_OR_LED_ALIAS'
            def endpoint(row,kind):
                p=Path(row['path']);assert sha(p)==row['sha256']
                # Retain the actual lossless pixels, including coarse endpoints.
                dest=site/'sealed_endpoints'/f'{window}_{index}_{kind}.png';dest.parent.mkdir(exist_ok=True)
                with dest.open('xb') as stream:stream.write(p.read_bytes())
                return dict(file=dest.relative_to(OUT).as_posix(),pts_s=row['pts_s'],pts_ticks=row['pts_ticks'],sha256=sha(dest))
            a,b=endpoint(before,'before'),endpoint(after,'after')
            rows.append(dict(index=index,head='E1',section='main',transition='GREEN_ON',before=a,after=b,
                bracket_s=[a['pts_s'],b['pts_s']],width_s=b['pts_s']-a['pts_s'],confidence=confidence,
                visual_review='Codex native crops reviewed; no second human reviewer',json_epoch_ms=None))
        windows.append(dict(window=window,transitions=rows))
    save(site/'video_only_truth_sealed.json',dict(windows=windows,reviewed_truth=True,predictions_read=False,
        movement_mapping='AWAITING_USER_CARDINALS',json_clock_mapping_accepted=False,
        semantics='decoded visible-lamp appearance intervals; physical exposure uncertainty not calibrated'))
    # Preserve ten clear red brackets; the unresolved/ambiguous cases are kept
    # as missing, rather than filled by a 100s-cycle assumption.
    red=[]
    for window in ('calibration','validation'):
        folder=OUT/'sverdlovsky'/(window+'_red_native');data=load(folder/'proposals.json')
        accepted=[];unresolved=[]
        for row in data['transitions']:
            if 'before' not in row or (window=='validation' and row['index']==5):
                unresolved.append(dict(index=row['index'],reason='no unambiguous old-amber/new-red bracket; last validation could be LED/timer ambiguity'))
                continue
            for key in ('before','after'):
                value=row[key];p=folder/value['file'];assert sha(p)==value['sha256']
                value['file']=p.relative_to(OUT).as_posix()
            row['status']='CODEX_NATIVE_ENDPOINT_REVIEWED_NO_SECOND_HUMAN_REVIEW';accepted.append(row)
        red.append(dict(window=window,transitions=accepted,unresolved=unresolved,expected_cycles=6))
    save(OUT/'sverdlovsky/video_red_truth_sealed.json',dict(windows=red,reviewed_truth=True,predictions_read=False,
        labels_selected_without_phase_model=True,physical_switch_accuracy_ms=None,json_clock_mapping_accepted=False))
    print('Enthusiasts video-only12 green appearances sealed; Sverd10 red brackets and2 unresolved retained')


if __name__=='__main__':main()
