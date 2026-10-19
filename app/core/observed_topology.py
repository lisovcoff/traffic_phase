"""Restrict a product projection to approaches observed across the whole archive.

Absence of observations is not proof of physical absence. The exported geometry
is explicitly a hypothesis; the untouched phase/history fit remains available.
"""
from copy import deepcopy

COMPASS=('N','S','E','W')


def project_observed_topology(result, approaches, *, repair_missing_phases=False):
    value=deepcopy(result)
    active=[a for a in COMPASS if a in approaches]
    value['intersection_geometry']=dict(approaches=active,approach_count=len(active),
        source='whole_archive_observed_origins_and_destinations',
        physical_absence_certified=False)
    plan=value.get('physical_signal_plan',{})
    if len(active)==4 and plan.get('enabled') and repair_missing_phases:
        _repair_inherited_turn_phase(value)
    if len(active)!=3 or not plan.get('enabled'):
        return value
    topology={a:deepcopy(h) for a,h in plan.get('topology',{}).items() if a in active}
    rows=value['schedule'].get('stream_activity_by_phase',[])
    def allowed(movement):
        parts=movement.replace('_','').split('->')
        return len(parts)==2 and all(a in active for a in parts)
    representatives={}
    for a,head in topology.items():
        head['arrows']=[m for m in head['arrows'] if allowed(m)]
        if not allowed(head['main']):
            candidates=[row for row in rows if row['stream'].startswith(a+'->') and allowed(row['stream'])]
            candidates.sort(key=lambda r:(-max(r['event_probability_by_phase'].values(),default=0),r['stream']))
            if not candidates:
                # An exit-only approach has no supported incoming main movement.
                head['main']=None
            else:
                head['main']=candidates[0]['stream']
                head['arrows']=[m for m in head['arrows'] if m!=head['main']]
                representatives[a]=head['main']
    plan['topology']=topology
    if any(h['main'] is None for h in topology.values()):
        plan.update(enabled=False,reason='NO_SUPPORTED_INCOMING_MOVEMENT_FOR_OBSERVED_APPROACH')
    def heads(green):
        return {a:dict(main='GREEN' if head['main'] in green else 'RED',
            arrows={m:'GREEN' for m in head['arrows'] if m in green}) for a,head in topology.items()}
    # The legacy four-leg proposal can inherit an unrelated through phase when
    # a T-leg turn is actually its main movement. Build an explicit T hypothesis
    # from discriminating observed signatures, preserving repeated latent states.
    # These are existing weak-evidence gates, not calibrated lamp probabilities.
    names=value['schedule']['phase_names']
    supported={name:[] for name in names}
    for row in rows:
        movement=row['stream']
        if not allowed(movement):continue
        rates=row['event_probability_by_phase'];peak=max(rates.values(),default=0);floor=min(rates.values(),default=0)
        if peak<.03 or peak<1.25*max(floor,.001) or peak-floor<.02:continue
        for name in names:
            if rates.get(name,0)>=max(.03,.75*peak):supported[name].append(movement)
    if all(supported.values()):
        for a,head in topology.items():
            head['arrows']=sorted({m for moves in supported.values() for m in moves
                if m.startswith(a+'->') and m!=head['main']})
        plan['phases']=[];plan['mapping']={}
        for i,name in enumerate(names):
            label='T_STATE_'+str(i);green=supported[name];plan['mapping'][name]=label
            plan['phases'].append(dict(name=label,green_movements=green,
                additional_movements=[m for m in green if m in topology[m.split('->')[0]]['arrows']],
                source_phase=name,heads=heads(green)))
        plan['stages']=[]
        for start,end,z in value['schedule'].get('baseline_segments',[]):
            if start>=value['schedule']['period_s']:break
            phase=plan['phases'][int(z)]
            plan['stages'].append(dict(stage_id=len(plan['stages'])+1,name=phase['name'],
                phase_start=start,phase_end=min(end,value['schedule']['period_s']),
                active_movements=phase['green_movements'],additional_movements=phase['additional_movements'],
                source_phase=names[int(z)],heads=heads(phase['green_movements'])))
    else:
        plan.update(enabled=False,reason='T_TOPOLOGY_HAS_UNRESOLVED_MOVEMENT_SIGNATURES')
    for phase in plan.get('phases',[]):
        phase['green_movements']=[m for m in phase['green_movements'] if allowed(m)]
        if 'additional_movements' in phase:
            phase['additional_movements']=[m for m in phase['additional_movements']
                if allowed(m) and m not in representatives.values()]
        if 'heads' in phase:
            phase['heads']=heads(phase['green_movements'])
    for stage in plan.get('stages',[]):
        stage['active_movements']=[m for m in stage.get('active_movements',[]) if allowed(m)]
        stage['additional_movements']=[m for m in stage.get('additional_movements',[])
            if allowed(m) and m not in representatives.values()]
        stage['heads']=heads(stage['active_movements'])
    plan['observed_topology_projection']=dict(approaches=active,main_representatives=representatives,
        semantics='dominant supported movement represents T-leg main; hardware arrangement remains ambiguous')
    # Any precomputed estimate belongs to the original, unrestricted projection.
    value.pop('estimated_signals',None)
    return value


def _repair_inherited_turn_phase(result):
    """Do not erase a reciprocal, selective turn phase by through-state inheritance.

    Restricted to explicitly inherited empty phases with no local support for
    their inherited greens. Other physical mapping decisions remain unchanged.
    """
    plan=result['physical_signal_plan'];rows=result['schedule']['stream_activity_by_phase']
    names=result['schedule']['phase_names'];by_name={g['name']:g for g in plan['phases']};repaired=[]
    for phase in plan.get('inference',{}).get('inherited_empty_phases',{}):
        old=by_name[plan['mapping'][phase]]
        if any(row['stream'] in old['green_movements'] and row['event_probability_by_phase'].get(phase,0)>=.03 for row in rows):continue
        candidates=[]
        for row in rows:
            rates=row['event_probability_by_phase'];p=rates.get(phase,0);other=max((v for n,v in rates.items() if n!=phase),default=0)
            if p>=.03 and p>=1.25*max(other,.001) and p-other>=.02:candidates.append(row['stream'])
        if not any('->'.join(reversed(m.split('->'))) in candidates for m in candidates):continue
        label='RECOVERED_'+phase;plan['mapping'][phase]=label
        for m in candidates:
            a=m.split('->')[0];head=plan['topology'][a]
            if m!=head['main'] and m not in head['arrows']:head['arrows'].append(m)
        heads={a:dict(main='GREEN' if h['main'] in candidates else 'RED',
            arrows={m:'GREEN' for m in h['arrows'] if m in candidates}) for a,h in plan['topology'].items()}
        group=dict(name=label,green_movements=candidates,additional_movements=[m for m in candidates
            if m in plan['topology'][m.split('->')[0]]['arrows']],source_phase=phase,heads=heads)
        plan['phases'].append(group);by_name[label]=group;repaired.append(phase)
    if repaired:
        plan['stages']=[]
        for a,b,z in result['schedule'].get('baseline_segments',[]):
            if a>=result['schedule']['period_s']:break
            name=names[int(z)];group=by_name[plan['mapping'][name]]
            plan['stages'].append(dict(stage_id=len(plan['stages'])+1,name=group['name'],source_phase=name,
                phase_start=a,phase_end=min(b,result['schedule']['period_s']),active_movements=group['green_movements'],
                additional_movements=group.get('additional_movements',[]),heads=deepcopy(group['heads'])))
        plan['projection_repair']=dict(resolved_inherited_phases=repaired,hardware_certified=False)
