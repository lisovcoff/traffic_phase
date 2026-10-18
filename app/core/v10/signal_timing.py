"""Shared head transition history; assumptions stay separate from lamp observations."""
from bisect import bisect_right
from copy import deepcopy
import json
import math


def apply_signal_timing(estimate, *, yellow_s=3., red_yellow_s=2., boundary_calibration=None):
    """Expand stable operating states, preserving gaps, arrows and joint boundaries.

    An optional clock-linked head calibrates JOINT operating-state boundaries.
    This prevents a one-head delay correction creating conflicting green states.
    Green continuing across an operating-state change has no lamp transition.
    """
    if not math.isfinite(yellow_s+red_yellow_s) or yellow_s<0 or not 0<=red_yellow_s<=2:
        raise ValueError('finite nonnegative yellow and red-yellow within0..2 required')
    result=deepcopy(estimate)
    if not result.get('available') or not result.get('segments'):return result
    if result.get('transition_timing'):raise ValueError('signal timing already applied')
    original=result['segments'];states={r['id']:r for r in result['states']}
    if any(not math.isfinite(a+b) or a>=b or sid not in states for a,b,sid in original):
        raise ValueError('valid finite nonempty operating intervals required')
    if any(a[1]>b[0] for a,b in zip(original,original[1:])):raise ValueError('overlapping history')
    adjusted=deepcopy(original);calibrated=[];issues=[]
    if boundary_calibration:
        approach=boundary_calibration['approach'];bias=boundary_calibration['onset_bias_s']
        if approach not in result['topology']:raise ValueError('calibration head absent')
        if any(not math.isfinite(float(v)) for v in bias.values()):raise ValueError('finite delays required')
        for i in range(1,len(original)):
            a,b=original[i-1],original[i]
            if a[1]!=b[0]:continue
            prev=states[a[2]]['heads'][approach]['main']['state'];nxt=states[b[2]]['heads'][approach]['main']['state']
            if prev!=nxt and nxt in bias:
                t=b[0]-float(bias[nxt]);adjusted[i-1][1]=t;adjusted[i][0]=t
                calibrated.append(dict(original_s=b[0],adjusted_s=t,anchor_approach=approach,onset=nxt))
        if any(a>=b for a,b,_ in adjusted) or any(a[1]>b[0] for a,b in zip(adjusted,adjusted[1:])):
            raise ValueError('calibration contradicts observed history ordering')
    # Work component-by-component: no implicit periodic neighbor or gap bridging.
    components=[]
    for row in adjusted:
        if not components or components[-1][-1][1]!=row[0]:components.append([])
        components[-1].append(row)
    output=[];catalog=[];signatures={}
    for rows in components:
        overlays={head:[] for head in result['topology']}
        for head in overlays:
            runs=[]
            for a,b,sid in rows:
                color=states[sid]['heads'][head]['main']['state']
                if runs and runs[-1][2]==color:runs[-1][1]=b
                else:runs.append([a,b,color])
            for i,(a,b,color) in enumerate(runs):
                # A boundary is required: no invented onset at the first frame.
                nxt=runs[i+1][2] if i+1<len(runs) else None
                duration=yellow_s if color=='GREEN' and nxt=='RED' else red_yellow_s if color=='RED' and nxt=='GREEN' else 0.
                if not duration:continue
                if b-a<duration:
                    overlays[head].append((a,b,'UNKNOWN'))
                    issues.append(dict(approach=head,range_s=[a,b],reason='RUN_TOO_SHORT_FOR_TRANSITION',required_s=duration))
                else:overlays[head].append((b-duration,b,'YELLOW' if color=='GREEN' else 'RED_YELLOW'))
        cuts=sorted({x for a,b,_ in rows for x in (a,b)}|{x for v in overlays.values() for a,b,_ in v for x in (a,b)})
        overlay_starts={head:[r[0] for r in intervals] for head,intervals in overlays.items()}
        starts=[r[0] for r in rows]
        for a,b in zip(cuts,cuts[1:]):
            old=states[rows[bisect_right(starts,a)-1][2]];heads=deepcopy(old['heads']);changed=[]
            for head,intervals in overlays.items():
                at=bisect_right(overlay_starts[head],a)-1
                active=intervals[at][2] if at>=0 and a<intervals[at][1] else None
                if active:
                    heads[head]['main'].update(state=active,source='NORMATIVE_TRANSITION_ESTIMATE' if active!='UNKNOWN' else 'INSUFFICIENT_TEMPORAL_SUPPORT')
                    changed.append(head+':'+active)
            signature=json.dumps([old['id'],heads],sort_keys=True)
            if signature not in signatures:
                sid=len(catalog);signatures[signature]=sid
                catalog.append(dict(id=sid,name=old['name']+(' · '+','.join(changed) if changed else ''),
                    heads=heads,green_movements=old.get('green_movements',[]),operating_state_id=old['id']))
            sid=signatures[signature]
            if output and output[-1][1]==a and output[-1][2]==sid:output[-1][1]=b
            else:output.append([a,b,sid])
    result.update(schema='estimated-operating-signals-v2',segments=output,states=catalog,
        operating_segments=deepcopy(original),operating_states=deepcopy(estimate['states']),
        transition_timing=dict(yellow_s=yellow_s,red_yellow_s=red_yellow_s,
            duration_source='GOST_R_52289_2019_7.5.2_assumption_NOT_observation',
            red_yellow_presence_assumed=red_yellow_s>0,
            phase_boundary_calibration=boundary_calibration,joint_boundary_adjustments=calibrated,
            unchanged_heads_share_calibrated_phase_boundary=bool(calibrated),
            green_blinking_inferred=False,additional_section_yellow_inferred=False,
            issues=issues,observed_physical_state='UNKNOWN'))
    return result
