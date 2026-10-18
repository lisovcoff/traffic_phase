"""Evaluate frozen transition recipe on sealed fresh video labels, once."""
import json
from app.core.v10.signal_timing import apply_signal_timing
from app.experimental.video_onset_bias import head_onsets,evaluate_bias
from scripts.yellow_video_review import OUT,ROOT
from scripts.cardinal_clock_link import read,save,sha


def state_error(estimate,truth,offset):
    # Only confidently interior windows: exclude endpoint brackets and all
    # uncertain red-yellow intervals before green. No dim boundary midpoint truth.
    by={c:sorted([r for r in truth if r['color']==c],key=lambda r:r['index']) for c in ['GREEN','YELLOW','RED']}
    intervals=[]
    for i in range(3):
        g,y,r=[by[c][i] for c in ['GREEN','YELLOW','RED']]
        intervals += [(g['bracket_s'][1],y['bracket_s'][0],'GREEN'),(y['bracket_s'][1],r['bracket_s'][0],'YELLOW')]
        end=by['GREEN'][i+1]['bracket_s'][0]-2 if i<2 else 3600
        intervals.append((r['bracket_s'][1],end,'RED'))
    ids={s['id']:s['heads']['N']['main']['state'] for s in estimate['states']}
    total=wrong=0.;per={}
    for a,b,color in intervals:
        total+=b-a;error=0.
        for lo,hi,sid in estimate['segments']:
            overlap=max(0,min(b,hi+offset)-max(a,lo+offset))
            if ids[sid]!=color:error+=overlap
        wrong+=error;per.setdefault(color,dict(seconds=0.,wrong_s=0.));per[color]['seconds']+=b-a;per[color]['wrong_s']+=error
    return dict(scored_seconds=total,wrong_seconds=wrong,correct_fraction=1-wrong/total,per_color=per,
        scope='confident interior intervals of three visible N-main cycles; uncertain brackets/RY excluded; green includes blinking',
        clock_uncertainty_in_scalar_metric=False)


def main():
    assert read(OUT/'clock3600/result.json')['status']=='PASS'
    truthpath=OUT/'sverdlovsky/fresh_truth_sealed.json';truth=read(truthpath)['rows']
    oldpath=ROOT/'evidence/learned_archive_integration_20261018/archive_1/result.json';old=read(oldpath)
    assert sha(oldpath)==read(ROOT/'evidence/cardinal_clock_link_20261018/clock_aware_calibration.json')['source_prediction_sha256']
    binary=old['estimated_signals'];recipe=read(OUT/'frozen_recipe.json')['calibration']['profiles'][0]['calibration']
    candidates={'original_binary':binary,'normative_only':apply_signal_timing(binary),
        'calibrated_with_transitions':apply_signal_timing(binary,boundary_calibration=recipe)}
    offset=(binary['schedule_base_timestamp_ms']-1740632395000)/1000-recipe['clock_delta_s']
    results={}
    for name,estimate in candidates.items():
        scores={}
        for color in ['GREEN','YELLOW','RED']:
            predicted=[t+offset for t in head_onsets(estimate,'N',color) if 3300<=t+offset<3600]
            scores[color]=evaluate_bias(predicted,[r for r in truth if r['color']==color])
        results[name]=dict(onsets=scores,state_error=state_error(estimate,truth,offset))
    durations={}
    for site in ['sverdlovsky','enthusiasts']:
        labels=read(OUT/site/'fresh_truth_sealed.json')['rows'];rows=[]
        for yellow in [r for r in labels if r['color']=='YELLOW']:
            red=next(r for r in labels if r['color']=='RED' and r['index']==yellow['index'])
            a,b=yellow['bracket_s'];c,d=red['bracket_s'];rows.append(dict(index=yellow['index'],
                appearance_duration_bounds_s=[c-b,d-a],normative3s_compatible=c-b<=3<=d-a))
        durations[site]=rows
    save(OUT/'evaluation.json',dict(fresh_window_video_pts_s=[3300,3600],calibration_video_pts_s=[900,1500],
        truth_sha256=sha(truthpath),source_prediction_sha256=sha(oldpath),results=results,
        yellow_duration_checks=durations,no_tuning_after_evaluation=True,
        enthusiasts_json_accuracy=None,enthusiasts_reason='independent camera/export clock mapping remains unresolved',
        red_yellow_onset_accuracy=None,red_yellow_reason='duration/presence modeled as explicit normative assumption, no sealed onset truth',
        universal_scope='same transition engine for any mapped head; numerical delays source-specific, not a universal road constant'))
    save(OUT/'comparison_models.json',dict(models=candidates,video_offset_s=offset))
    print(json.dumps({n:dict(state=r['state_error'],onsets={c:{k:v for k,v in q.items() if k!='pairs'} for c,q in r['onsets'].items()}) for n,r in results.items()}),flush=True)


if __name__=='__main__':main()
