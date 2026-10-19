"""Learn restart age densities from offline fitted histories, without lamp labels."""
from bisect import bisect_right
from collections import defaultdict
import gzip
import json
import numpy as np


def attach_age_priors(model,folder):
    from app.core.intersection_project import operating_template
    from app.core.observed_topology import project_observed_topology
    sessions={s['session_id']:s for s in model['sessions']}
    for regime in model['regimes']:
        counts=defaultdict(lambda:np.zeros((regime['phase_count'],16)))
        for member in regime['members']:
            session=sessions[member['session_id']]
            with gzip.open(folder/session['prediction'],'rt',encoding='utf8') as stream:result=json.load(stream)
            projected=project_observed_topology(result,model['approaches'],repair_missing_phases=model.get('projection_version')=='observed-topology-v2')
            template=operating_template(projected);segments=template['schedule']['raw_hsmm_segments']
            starts=[s[0] for s in segments];base=result.get('schedule_base_timestamp_ms',result.get('analysis_base_timestamp_ms',0))
            for event in result.get('event_extraction',{}).get('temporal_events',[]):
                if event['event_type']!='RELEASE':continue
                second=(event['timestamp_ms']-base)/1000;index=bisect_right(starts,second)-1
                if index<0:continue
                a,b,z=segments[index]
                if not a<=second<b:continue
                phase=member['phase_mapping'][str(int(z))]
                counts[event['movement']][phase,min(15,int(16*(second-a)/(b-a)))]+=1
        regime['restart_age_histograms']={};regime['restart_age_samples']={}
        for movement,rows in counts.items():
            result=[]
            for row in rows:
                # Broad pseudocount/smoothing; sparse marks provide no age claim.
                smoothed=np.convolve(np.pad(row,(1,1),mode='edge'),np.ones(3)/3,mode='valid')+2
                smoothed=smoothed/smoothed.mean() if row.sum()>=8 else np.ones(16)
                result.append(smoothed.tolist())
            regime['restart_age_histograms'][movement]=result
            regime['restart_age_samples'][movement]=rows.sum(axis=1).astype(int).tolist()
    model['event_age_prior_version']='offline-restart-age-v1'
    model['event_age_prior_semantics']='fitted trajectory phase ages; no video; NOT calibrated lamp/reaction delays'
    return model
