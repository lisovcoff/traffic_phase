"""Seal visually reviewed fresh labels before joining model predictions."""
from scripts.yellow_video_review import OUT
from scripts.cardinal_clock_link import read,save,sha
from app.experimental.video_clock_mapping import map_bracket


def main():
    clock=read(OUT.parent/'cardinal_clock_link_20261018/mapped_main_truth.json')
    for site in ['sverdlovsky','enthusiasts']:
        data=read(OUT/site/'fresh_truth_proposals.json')
        if site=='enthusiasts':
            row=next(r for r in data['rows'] if r['color']=='YELLOW' and r['index']==0)
            folder=OUT/site/'validation_native/2';frames=read(folder/'frames.json')['rows']
            def endpoint(t):
                r=min(frames,key=lambda r:abs(r['pts_s']-t))
                return dict(r,file=(folder/r['file']).relative_to(OUT).as_posix())
            row.update(before=endpoint(3367.866667),after=endpoint(3367.933333),
                bracket_s=[endpoint(3367.866667)['pts_s'],endpoint(3367.933333)['pts_s']],
                review_correction='First proposed before already shows yellow; earlier actual native green endpoint used. No prediction data read.')
        for row in data['rows']:
            for key in ['before','after']:assert sha(OUT/row[key]['file'])==row[key]['sha256']
            row.update(approach='N' if site=='sverdlovsky' else 'E',section='main',
                visual_review='Codex inspected original native/coarse endpoint pixels; no second human review')
            if site=='sverdlovsky':
                row['clock_mapping']=map_bracket(row['bracket_s'],origin_ms=1740632395000,
                    delta_s=clock['delta_s'],delta_bounds_s=clock['conditional_delta_bounds_s'])
            else:row['json_clock_mapping']=None
        data.update(final_visual_review=True,prediction_data_read=False,
            selection_video_pts_s=[3300,3600],image_appearance_not_certified_physical_switch=True,
            time_quantization='native PTS preserved; broad dim/alias brackets deliberately retained')
        save(OUT/site/'fresh_truth_sealed.json',data)
    print('Sealed9 Sverd and8 Enth fresh video endpoints before prediction comparison')


if __name__=='__main__':main()
