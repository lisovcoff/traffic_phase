"""Independent SUMO traffic fixtures; signal truth is never put in vehicle JSON.

Install eclipse-sumo==1.28.0 and run with --sumo-home pointing at its sumo folder.
This validates a controlled road scenario, not a calibrated replica of a real site.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

BASE_MS = 1_800_000_000_000
POSITIONS = {'N': (200, 400), 'E': (400, 200), 'S': (200, 0), 'W': (0, 200)}
TARGET = {'N': 'S', 'S': 'N', 'E': 'W', 'W': 'E'}


def xml(path, root):
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def conflicting_greens(network, states):
    """Use SUMO's geometric conflict matrix, not the intended phase grouping."""
    junction = network.find("./junction[@id='C']")
    internal = junction.get('intLanes').split()
    request_by_link = {int(c.get('linkIndex')): internal.index(c.get('via'))
                       for c in network.findall('connection') if c.get('tl') == 'C'}
    foes = {int(r.get('index')): r.get('foes')[::-1] for r in junction.findall('request')}
    conflicts = []
    for state in sorted(set(states)):
        active = [request_by_link[i] for i, color in enumerate(state) if color in 'Gg']
        for i in active:
            for j in active:
                if i < j and (foes[i][j] == '1' or foes[j][i] == '1'):
                    conflicts.append(dict(state=state, requests=[i, j]))
    return conflicts


def run(config, out, sumo_home):
    out, sumo_home = Path(out).resolve(), Path(sumo_home).resolve()
    out.mkdir(parents=True, exist_ok=False)
    binary_suffix = '.exe' if (sumo_home/'bin/sumo.exe').exists() else ''
    def execute(name, args):
        command = [str(sumo_home/'bin'/(name+binary_suffix)), *map(str, args)]
        result = subprocess.run(command, capture_output=True, check=False,
                                env={**os.environ, 'SUMO_HOME':str(sumo_home)})
        (out/(name+'.stdout')).write_bytes(result.stdout)
        (out/(name+'.stderr')).write_bytes(result.stderr)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors='replace'))
        return command

    nodes = ET.Element('nodes')
    ET.SubElement(nodes, 'node', id='C', x='200', y='200', type='traffic_light')
    edges, connections, routes = ET.Element('edges'), ET.Element('connections'), ET.Element('routes')
    approaches = list(POSITIONS) if config.get('approaches', 4) == 4 else ['N','E','S']
    targets = dict(TARGET)
    if len(approaches) == 3:
        targets['E'] = 'N'
    for a in approaches:
        x, y = POSITIONS[a]
        ET.SubElement(nodes, 'node', id=a, x=str(x), y=str(y), type='priority')
        ET.SubElement(edges, 'edge', id=a+'_in', **{'from':a, 'to':'C'}, numLanes='1', speed='13.89')
        ET.SubElement(edges, 'edge', id=a+'_out', **{'from':'C', 'to':a}, numLanes='1', speed='13.89')
        ET.SubElement(connections, 'connection', **{'from':a+'_in', 'to':targets[a]+'_out'}, fromLane='0', toLane='0')
    for name, data in [('nodes',nodes),('edges',edges),('connections',connections)]:
        xml(out/(name+'.xml'), data)
    network_command = execute('netconvert', ['--node-files',out/'nodes.xml', '--edge-files',out/'edges.xml',
        '--connection-files',out/'connections.xml', '--output-file',out/'network.net.xml', '--no-turnarounds','true'])
    network = ET.parse(out/'network.net.xml').getroot()
    center = network.find("./junction[@id='C']")
    # netconvert normalizes the network origin; a T road has no western edge.
    # Use exported coordinates, not the pre-conversion (200, 200) node location.
    center_x, center_y = float(center.get('x')), float(center.get('y'))
    indices = {c.get('from').split('_')[0]:int(c.get('linkIndex'))
               for c in network.findall('connection') if c.get('tl') == 'C'}
    assert set(indices) == set(approaches)
    groups = {2:[['N','S'],['E','W']],3:[['N'],['S'],['E','W']],4:[['N'],['E'],['S'],['W']]}[config['k']]
    groups = [[a for a in g if a in approaches] for g in groups]
    if any(not g for g in groups):
        raise ValueError('Empty signal group')
    tls = network.find('tlLogic')
    for child in list(tls):
        tls.remove(child)
    # One explicit finite program, independent of vehicle generation and inference.
    # All-red clearance and red+yellow are distinct and do not authorize entry.
    cursor = 0.; schedule = []; cycle = 0; extension_used = False
    program_changes=sorted(config.get('program_changes',[]),key=lambda row:row['at_s'])
    while cursor < config['duration_s'] + config['period_s']:
        period = config['period_s'] * (1.15 if config.get('regime_change') and cursor >= config['duration_s']/2 else 1)
        for change in program_changes:
            if cursor>=change['at_s']:period=change['period_s']
        green = period / len(groups) - 7
        if green < 8:
            raise ValueError('Insufficient green duration')
        for group in groups:
            duration = green
            if config.get('extension_s') and not extension_used and cursor >= config['duration_s']/2 and group == groups[0]:
                duration += config['extension_s']; extension_used = True
            for color, seconds in [('u',2),('G',duration),('y',3),('r',2)]:
                state = ['r'] * len(indices)
                for a in group:
                    state[indices[a]] = color
                state = ''.join(state)
                ET.SubElement(tls,'phase',duration=str(seconds),state=state)
                schedule.append(dict(start_s=cursor,end_s=cursor+seconds,state=state,cycle=cycle))
                cursor += seconds
        cycle += 1
    xml(out/'network.net.xml', network)
    ET.SubElement(routes,'vType',id='car',vClass='passenger',length='4.5',minGap='2.5',
                  accel='2',decel='3',emergencyDecel='4.5',tau='1',sigma='0.5')
    # Independently seeded stochastic arrivals; SUMO delays insertion until space exists.
    for a in approaches:
        ET.SubElement(routes,'route',id=a,edges=a+'_in '+targets[a]+'_out')
        ET.SubElement(routes,'flow',id=a,type='car',route=a,begin='0',end=str(config['duration_s']),
                      period='exp('+str(config.get('arrival_rate_s',.16))+')',departLane='best',departSpeed='max')
    if config.get('downstream_stop_s'):
        blocker=ET.SubElement(routes,'vehicle',id='N.blocker',type='car',route='N',
                              depart=str(config['duration_s']/3),departSpeed='max')
        ET.SubElement(blocker,'stop',lane=targets['N']+'_out_0',endPos='12',
                      duration=str(config['downstream_stop_s']))
    xml(out/'routes.xml',routes)
    additional=ET.Element('additional')
    ET.SubElement(additional,'timedEvent',type='SaveTLSStates',source='C',dest=str(out/'tls.xml'))
    xml(out/'additional.xml',additional)
    command=execute('sumo',['--net-file',out/'network.net.xml','--route-files',out/'routes.xml',
        '--additional-files',out/'additional.xml','--end',config['duration_s'],'--step-length','.2',
        '--seed',config['seed'],'--fcd-output',out/'fcd.xml','--fcd-output.attributes','id,x,y,speed,lane,pos',
        '--collision.check-junctions','true','--collision.action','warn','--collision-output',out/'collisions.xml',
        '--time-to-teleport','-1','--no-step-log','true','--summary-output',out/'summary.xml'])

    records={}; previous={}; accelerations=[]; moving_red_entries=[]
    truth_by_time={float(e.get('time')):e.get('state') for _,e in ET.iterparse(out/'tls.xml') if e.tag=='tlsState'}
    gaps=[]; missing_tls_times=[]
    for _,step in ET.iterparse(out/'fcd.xml'):
        if step.tag!='timestep':continue
        t=float(step.get('time'))
        if t not in truth_by_time:
            missing_tls_times.append(t)
        lanes=defaultdict(list)
        for vehicle in step:
            ident=vehicle.get('id');a=ident.split('.')[0];target=targets[a]
            speed=float(vehicle.get('speed'));x=float(vehicle.get('x'))-center_x;y=float(vehicle.get('y'))-center_y
            lane=vehicle.get('lane');p=previous.get(ident)
            lanes[lane].append(float(vehicle.get('pos')))
            if p:
                accelerations.append((speed-p[1])/(t-p[0]))
                if p[2]==a+'_in_0' and lane!=p[2]:
                    # FCD is an end-step observation. Log the last pre-entry TLS state.
                    state=truth_by_time.get(round(p[0],2))
                    if state and state[indices[a]] in 'ru':
                        moving_red_entries.append(dict(vehicle=ident,time=t,previous_state=state))
            previous[ident]=(t,speed,lane)
            if abs(x)>100 or abs(y)>100:continue
            record=records.setdefault(ident,dict(id=len(records)+1,zone_in=a,zone_out=None,
                category_name='car',stay_duration_millis=0,detections=[]))
            zone=a if lane==a+'_in_0' or lane.startswith(':') else '_'+target
            record['detections'].append(dict(millis=BASE_MS+round(t*1000),zone=zone,speed=speed*3.6,
                lat=55+y/111000,lng=61+x/(111000*math.cos(math.radians(55))),
                centroid_x=.5+x/300,centroid_y=.5-y/300))
            if speed<.1:record['stay_duration_millis']+=200
            if zone.startswith('_'):record['zone_out']=zone
            record['millis']=BASE_MS+round(t*1000)
        for positions in lanes.values():
            positions.sort()
            gaps.extend(b-a-4.5 for a,b in zip(positions,positions[1:]))
        step.clear()
    records=[r for r in records.values() if len(r['detections'])>=3]
    raw=json.dumps(records,separators=(',',':')).encode()
    (out/'vehicles.json').write_bytes(raw)
    collisions=ET.parse(out/'collisions.xml').getroot().findall('collision')
    warnings=(out/'sumo.stderr').read_text(errors='replace')
    conflicts=conflicting_greens(network,truth_by_time.values())
    represented_approaches=sorted({r['zone_in'] for r in records})
    audit=dict(collision_count=len(collisions),teleport_warning='Teleport' in warnings,
        represented_approaches=represented_approaches,expected_approaches=sorted(approaches),
        min_acceleration_mps2=min(accelerations,default=0),max_acceleration_mps2=max(accelerations,default=0),
        minimum_same_lane_bumper_gap_m=min(gaps,default=None),
        conflicting_green_states=conflicts,missing_tls_times=missing_tls_times,
        red_entry_candidates=moving_red_entries,tracks=len(records),detections=sum(len(r['detections']) for r in records),
        physics_status='PASS' if records and not collisions and not moving_red_entries and not 'Teleport' in warnings
            and not conflicts and not missing_tls_times and min(gaps,default=2.5)>=2.48
            and represented_approaches==sorted(approaches)
            and min(accelerations,default=0)>=-4.6 and max(accelerations,default=0)<=2.1 else 'FAIL')
    truth=dict(schema='sumo-independent-signal-truth-v1',config=config,base_ms=BASE_MS,
        groups=groups,link_indices=indices,schedule=schedule,
        actual_tls_states=[dict(time_s=t,state=s) for t,s in truth_by_time.items()],
        scope='Controlled lane-based SUMO scenario, not a fitted replica of a real intersection',audit=audit,
        vehicle_input_sha256=hashlib.sha256(raw).hexdigest(),network_command=network_command,simulation_command=command)
    (out/'truth.json').write_text(json.dumps(truth,indent=2),encoding='utf8',newline='\n')
    print(json.dumps(audit),flush=True)
    return audit


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sumo-home',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--duration',type=int,default=900)
    parser.add_argument('--seed',type=int,default=20261020)
    parser.add_argument('--k',type=int,choices=[2,3,4],default=2)
    parser.add_argument('--approaches',type=int,choices=[3,4],default=4)
    parser.add_argument('--extension',type=float,default=0)
    parser.add_argument('--regime-change',action='store_true')
    args=parser.parse_args()
    run(dict(seed=args.seed,k=args.k,approaches=args.approaches,duration_s=args.duration,period_s=100,
             extension_s=args.extension,regime_change=args.regime_change),args.output,args.sumo_home)
