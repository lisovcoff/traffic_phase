"""Whole-intersection archive ingestion and a persistent, trajectory-only model.

Sources/sessions retain separate clocks and track namespaces. Only phase
signatures and duration statistics are pooled; recordings are never concatenated.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import gzip
import hashlib
import io
import json
from pathlib import Path
import time
import zipfile

import numpy as np

from app.core.v9.source_scope import choose_source, ScopeChoiceRequired, input_sessions, choose_session, attach_input_scope
from app.core.temporal_evidence import EvidenceUnavailable

SCHEMA = 'traffic-intersection-model-v1'
MAX_ARCHIVE_BYTES = 16 * 1024**3
MAX_TOTAL_JSON_BYTES = 64 * 1024**3
MAX_SOURCE_JSON_BYTES = 4 * 1024**3
COMPASS = ('N', 'S', 'E', 'W')


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.writing')
    with temporary.open('w', encoding='utf8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    temporary.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4*1024**2), b''):
            value.update(chunk)
    return value.hexdigest()


def _compass(value):
    text = str(value or '').replace('_', '').strip().upper()
    return text if text in COMPASS else None


def _small_metadata(input_path, source):
    if source['uncompressed_bytes'] > 1024**2:
        return False
    try:
        if input_path.suffix.lower()=='.zip':
            with zipfile.ZipFile(input_path) as archive:
                value=json.loads(archive.read(source['source_member']))
        else:
            value=read_json(input_path)
        return isinstance(value,dict) and not any(key in value for key in ('detections','trajectories','vehicles','tracks'))
    except (ValueError,OSError,zipfile.BadZipFile):
        return False


def model_fingerprint(model):
    semantic={k:v for k,v in model.items() if k not in ('model_id','input_path_private','fingerprint')}
    return hashlib.sha256(json.dumps(semantic,sort_keys=True,separators=(',', ':'),allow_nan=False).encode()).hexdigest()


def read_model(folder):
    model=read_json(Path(folder)/'model.json')
    if model.get('schema')!=SCHEMA or model.get('fingerprint')!=model_fingerprint(model):
        raise ValueError('stored model checksum/schema mismatch')
    return model


def _signatures(result):
    schedule = result['schedule']; names = schedule['phase_names']
    values = {}
    for row in schedule['stream_activity_by_phase']:
        movement = row['stream']
        rates = np.array([row['event_probability_by_phase'][name] for name in names])
        excess = np.maximum(0., rates-rates.min())
        if float(excess.max()) > .01:
            values[movement] = excess/excess.max()
    return values


def operating_template(result):
    """Unique modeled head configurations, retaining the latent result separately.

    The original predicted history is never rewritten. Repeated visits to one
    configuration remain possible; K is not a requirement to visit each once.
    """
    original=result['schedule'];template=dict(schedule=deepcopy(original),state_basis='logical_movement_signatures')
    if not result.get('physical_signal_plan',{}).get('enabled'):
        return template
    from app.core.v10.estimated_signals import build_estimated_signals
    estimate=build_estimated_signals(result,profile_id='none',transitions=False)
    if not estimate['available']:
        return template
    names=original['phase_names'];mapping={z:estimate['phase_mapping'][name] for z,name in enumerate(names)}
    k=estimate['operating_phase_count'];new_names=[f'PHASE_{chr(65+z)}' for z in range(k)]
    def segments(rows):
        output=[]
        for a,b,z in rows:
            phase=mapping[int(z)]
            if output and output[-1][1]==a and output[-1][2]==phase:output[-1][1]=b
            else:output.append([a,b,phase])
        return output
    weights=Counter()
    for a,b,z in original['raw_hsmm_segments']:weights[int(z)]+=b-a
    rows=[]
    for row in original['stream_activity_by_phase']:
        values={}
        for z,name in enumerate(new_names):
            old=[q for q in range(len(names)) if mapping[q]==z]
            values[name]=float(np.average([row['event_probability_by_phase'][names[q]] for q in old],
                                          weights=[max(weights[q],1e-9) for q in old]))
        rows.append(dict(stream=row['stream'],event_probability_by_phase=values))
    template['schedule'].update(phase_count=k,phase_names=new_names,stream_activity_by_phase=rows,
        raw_hsmm_segments=segments(original['raw_hsmm_segments']),baseline_segments=segments(original.get('baseline_segments',[])))
    template.update(state_basis='automatic_estimated_head_configurations',
        phase_head_states=[deepcopy(s['heads']) for s in estimate['states']],
        signal_topology=deepcopy(estimate['topology']),latent_phase_count=original['phase_count'])
    return template


def _match(reference, candidate):
    """Conservative cyclic alignment; a new catalogue entry when ambiguous."""
    a, b = reference['schedule'], candidate['schedule']
    if a['phase_count'] != b['phase_count']:
        return None
    if reference.get('state_basis') != candidate.get('state_basis'):
        return None
    if abs(a['period_s']-b['period_s']) > .08*max(a['period_s'], b['period_s']):
        return None
    if reference.get('phase_head_states') and reference.get('signal_topology')==candidate.get('signal_topology'):
        signatures=lambda r:[json.dumps(h,sort_keys=True) for h in r['phase_head_states']]
        x,y=signatures(reference),signatures(candidate)
        if set(x)==set(y) and len(set(x))==len(x):
            return dict(distance=0.,mapping={z:x.index(value) for z,value in enumerate(y)})
    x, y = _signatures(reference), _signatures(candidate)
    common = sorted(x.keys() & y.keys())
    if len(common) < 2 or len(common)/max(1, len(x.keys() | y.keys())) < .7:
        return None
    k = a['phase_count']; costs = []
    for shift in range(k):
        cost = float(np.mean([abs(x[m][(z+shift)%k]-y[m][z]) for m in common for z in range(k)]))
        costs.append((cost, shift))
    costs.sort()
    if costs[0][0] > .22 or (len(costs)>1 and costs[1][0]-costs[0][0] < .03):
        return None
    return dict(distance=costs[0][0], mapping={z:(z+costs[0][1])%k for z in range(k)})


def build_catalogue(predictions):
    """Export a reusable offline model; no names/profiles/annotations consulted."""
    groups = []
    for session_id, result in predictions:
        matches = [(index, _match(group['reference'], result)) for index, group in enumerate(groups)]
        matches = [(index, match) for index, match in matches if match is not None]
        matches.sort(key=lambda row: row[1]['distance'])
        if matches and (len(matches)==1 or matches[1][1]['distance']-matches[0][1]['distance'] >= .03):
            group = groups[matches[0][0]]
            match = matches[0][1]
        else:
            group = dict(reference=result, members=[]); groups.append(group)
            match = dict(distance=0., mapping={z:z for z in range(result['schedule']['phase_count'])})
        group['members'].append((session_id, result, match))
    output = []
    for number, group in enumerate(groups, 1):
        reference = group['reference']; schedule = reference['schedule']; k = schedule['phase_count']
        probabilities = defaultdict(lambda: np.zeros(k)); weights = Counter(); durations = defaultdict(list)
        transitions=Counter()
        members = []
        for sid, result, match in group['members']:
            s = result['schedule']; mapping = match['mapping']
            segments = s['raw_hsmm_segments']
            weight = sum(b-a for a,b,z in segments)
            for row in s['stream_activity_by_phase']:
                for z,name in enumerate(s['phase_names']):
                    probabilities[row['stream']][mapping[z]] += weight*row['event_probability_by_phase'][name]
                weights[row['stream']] += weight
            for a,b,z in segments[1:-1]:
                durations[mapping[int(z)]].append(float(b-a))
            for previous,current in zip(segments,segments[1:]):
                if previous[1]==current[0] and mapping[int(previous[2])]!=mapping[int(current[2])]:
                    transitions[mapping[int(previous[2])],mapping[int(current[2])]]+=1
            members.append(dict(session_id=sid, phase_mapping={str(z):v for z,v in mapping.items()},
                                signature_distance=match['distance']))
        phase_names = [f'PHASE_{chr(65+z)}' for z in range(k)]
        output.append(dict(regime_id=f'regime_{number:03d}', phase_count=k, phase_names=phase_names,
            period_s=float(np.median([r['schedule']['period_s'] for _,r,_ in group['members']])),
            members=members, movement_probabilities={m:(v/weights[m]).tolist() for m,v in probabilities.items()},
            phase_durations={phase_names[z]:dict(samples=len(durations[z]),
                p10_s=float(np.quantile(durations[z],.1)) if durations[z] else None,
                median_s=float(np.median(durations[z])) if durations[z] else None,
                p90_s=float(np.quantile(durations[z],.9)) if durations[z] else None) for z in range(k)},
            reference_baseline=deepcopy(schedule.get('baseline_segments', [])),
            reference_period_s=schedule['period_s'],
            signal_topology=deepcopy(reference.get('signal_topology',{})),
            phase_head_states=deepcopy(reference.get('phase_head_states',[])),
            state_basis=reference.get('state_basis','logical_movement_signatures'),
            observed_transitions=[dict(source=a,target=b,observations=count) for (a,b),count in sorted(transitions.items())],
            grouping_semantics='heuristic recurring observed signatures; NOT certified controller programs',
            structure_source='offline_trajectory_only', online_structure_frozen=True))
    return output


def run_project(input_path, folder, *, on_progress=None, predictor=None, _source_loader=None):
    """Process every JSON and every session; publish explicit partial failures."""
    from app.core.v9.events import load_event_streams
    from app.core.recovery.motion import extract_motion_evidence
    from app.core.recovery.engine import discover_bundle
    input_path, folder = Path(input_path).resolve(), Path(folder).resolve()
    predictor = predictor or discover_bundle
    folder.mkdir(parents=True, exist_ok=True)
    if (folder/'model.json').exists():
        raise ValueError('project model already exists; create a new project')
    started = time.monotonic()
    prior = read_json(folder/'status.json') if (folder/'status.json').is_file() else {}
    display_name = prior.get('input_name',input_path.name)
    state = dict(status='RUNNING', stage='inventory', sources_total=0, sources_done=0,
                 sessions_done=0, input_name=display_name, sources=[], errors=[])
    def checkpoint():
        state['elapsed_s'] = round(time.monotonic()-started, 2)
        write_json(folder/'status.json', state)
        if on_progress:
            on_progress(deepcopy(state))
    checkpoint()
    try:
        if input_path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError('archive exceeds 16 GiB input budget')
        try:
            _, sources = choose_source(input_path, max_bytes=MAX_SOURCE_JSON_BYTES)
        except ScopeChoiceRequired as choice:
            sources = choice.choices
        if sum(row['uncompressed_bytes'] for row in sources) > MAX_TOTAL_JSON_BYTES:
            raise ValueError('JSON total exceeds 64 GiB budget')
        state['sources_total'] = len(sources)
        predictions, sessions, compass_counts, geometries = [], [], Counter(), {}
        from app.core.intersection_queue_observations import IntersectionQueueLearner
        queue_learner=IntersectionQueueLearner()
        for index, source in enumerate(sources):
            member = source['source_member']
            row = dict(**source, status='RUNNING', sessions=[])
            state['sources'].append(row); state.update(stage='extracting', current_source=member); checkpoint()
            try:
                # Recheck individual size/path/encryption/collisions before read.
                choose_source(input_path, member, max_bytes=MAX_SOURCE_JSON_BYTES)
                samples=defaultdict(list); counts=Counter()
                def extractor(track,**kwargs):
                    if isinstance(track,dict) and isinstance(track.get('detections'),list):
                        queue_learner.add(track)
                        counts['trajectory_records']+=1; counts['detections']+=len(track['detections'])
                        origin=_compass(track.get('zone_in'));ds=track['detections']
                        if origin and len(samples[origin])<48 and ds:
                            indices=sorted(set([0,len(ds)-1]+list(range(0,len(ds),max(1,len(ds)//16)))))
                            points=[{key:ds[i].get(key) for key in ('millis','centroid_x','centroid_y','zone')}
                                    for i in indices if isinstance(ds[i],dict)]
                            samples[origin].append(dict(zone_in=track.get('zone_in'),zone_out=track.get('zone_out'),detections=points))
                    return extract_motion_evidence(track,**kwargs)
                try:
                    if _source_loader is None:
                        bundle = load_event_streams(input_path, source_member=member,_event_extractor=extractor)
                    else:
                        # Explicit local validation adapter; HTTP jobs always read raw input.
                        # The adapter must verify source/cache hashes before returning data.
                        bundle, summary = _source_loader(input_path, source)
                        counts.update(summary['record_counts'])
                        samples.update(summary['samples'])
                except EvidenceUnavailable:
                    if not counts['trajectory_records']:
                        row.update(status='SKIPPED_NON_TRAJECTORY_JSON',record_counts=dict(counts))
                        continue
                    raise
                except ValueError:
                    if not counts['trajectory_records'] and _small_metadata(input_path,source):
                        row.update(status='SKIPPED_NON_TRAJECTORY_JSON',record_counts=dict(counts))
                        continue
                    raise
                row['record_counts']=dict(counts)
                if not bundle.temporal_events:
                    row.update(status='NO_USABLE_TRAJECTORIES', reason='No usable vehicle events in this JSON')
                    continue
                observed = Counter()
                for event in bundle.temporal_events:
                    for zone in event.movement.split('->'):
                        if _compass(zone): observed[_compass(zone)] += 1
                compass_counts.update(observed)
                from app.core.v9.spatial import build_spatial_projection
                geometries[member]=dict(projection=build_spatial_projection([t for rows in samples.values() for t in rows]),
                    scope='bounded geometric sample per observed incoming approach; schematic, not calibrated road geometry')
                choices = input_sessions(bundle, member)
                for session in choices:
                    state.update(stage='discovering', current_session=session.metadata['session_number']); checkpoint()
                    scoped, selected, all_sessions = choose_session(bundle, member, session.metadata['session_id'])
                    sid = hashlib.sha256((member+'\0'+selected['session_id']).encode()).hexdigest()[:24]
                    item = dict(session_id=sid, source_member=member, source_index=index,
                        observation_start_ms=selected['observation_start_ms'], observation_end_ms=selected['observation_end_ms'],
                        track_count=selected['track_count'], status='RUNNING')
                    row['sessions'].append(item)
                    try:
                        result = predictor(scoped, input_name='intersection trajectory archive', dt=1.)
                        attach_input_scope(result, member, selected, all_sessions, source_count=len(sources))
                        destination = folder/'sessions'/(sid+'.json.gz'); destination.parent.mkdir(exist_ok=True)
                        with destination.open('xb') as raw:
                            with gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as compressed:
                                with io.TextIOWrapper(compressed,encoding='utf8') as stream:
                                    json.dump(result, stream, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
                        template=operating_template(result)
                        item.update(status='READY', phase_count=template['schedule']['phase_count'],
                            latent_phase_count=result['schedule']['phase_count'],state_basis=template['state_basis'],
                            period_s=result['schedule']['period_s'], prediction=destination.relative_to(folder).as_posix(),
                            prediction_sha256=digest(destination))
                        predictions.append((sid,template))
                        sessions.append(item)
                        state['sessions_done'] += 1
                    except Exception as error:
                        item.update(status='FAILED', reason=type(error).__name__+': '+str(error)[:500])
                        state['errors'].append(dict(source_member=member, session_id=sid, reason=item['reason']))
                    checkpoint()
                row['status'] = 'READY' if row['sessions'] and all(s['status']=='READY' for s in row['sessions']) else 'PARTIAL'
            except Exception as error:
                row.update(status='FAILED', reason=type(error).__name__+': '+str(error)[:500])
                state['errors'].append(dict(source_member=member, reason=row['reason']))
            finally:
                state['sources_done'] += 1; checkpoint()
        if not predictions:
            if state['sources'] and all(row['status']=='SKIPPED_NON_TRAJECTORY_JSON' for row in state['sources']):
                state.update(reason_code='NON_TRAJECTORY_INPUT',
                    user_message='No vehicle trajectories were found. Upload the original vehicle JSON or ZIP, not a manifest or report.')
            raise ValueError('No session could produce an intersection model')
        state['stage'] = 'catalogue'; checkpoint()
        approaches = [a for a in COMPASS if compass_counts[a]]
        if len(approaches) in (3,4):
            from app.core.observed_topology import project_observed_topology
            predictions=[]
            for session in sessions:
                with gzip.open(folder/session['prediction'],'rt',encoding='utf8') as stream:
                    result=json.load(stream)
                template=operating_template(project_observed_topology(result,approaches,repair_missing_phases='selective'))
                session.update(phase_count=template['schedule']['phase_count'],state_basis=template['state_basis'])
                predictions.append((session['session_id'],template))
        catalogue = build_catalogue(predictions)
        regime_by_session = {m['session_id']:r['regime_id'] for r in catalogue for m in r['members']}
        for session in sessions:
            session['regime_id'] = regime_by_session[session['session_id']]
        complete = all(row['status'] in ('READY','SKIPPED_NON_TRAJECTORY_JSON') for row in state['sources'])
        model = dict(schema=SCHEMA, model_id=folder.name, algorithm='trajectory_recovery_v1',
            input=dict(name=display_name, sha256=digest(input_path), source_count=len(sources),
                       intersection_identity='declared_single_intersection; namespace consistency not independently certified'),
            completeness='COMPLETE' if complete else 'PARTIAL', sessions=sessions, regimes=catalogue,
            projection_version='observed-topology-v3',
            source_inventory=deepcopy(state['sources']),
            geometries=geometries,
            approaches=approaches, observed_approach_count=len(approaches),
            topology_semantics='observed origins/destinations; empty approaches may remain unseen; hardware inference not certified',
            known_hardware_profile_used=False, annotations_used=False, video_used=False,
            offline_structure_frozen=True, history_semantics='separate source/session histories; no continuity across gaps',
            calendar_timezone='UTC+05:00; source acquisition dates not independently certified',
            calendar_observations=[dict(session_id=s['session_id'],weekday=datetime.fromtimestamp(
                s['observation_start_ms']/1000, timezone(timedelta(hours=5))).weekday()) for s in sessions],
            regime_selection_semantics='signature catalogue; weekday programs not yet certified',
            input_path_private=str(input_path), errors=state['errors'])
        from app.core.intersection_age_prior import attach_age_priors
        attach_age_priors(model,folder)
        model['queue_observations']=queue_learner.finish(catalogue)
        model['queue_observations']['training']=dict(method='bounded_offline_reservoir',
            sample_limit_per_approach=queue_learner.capacity,
            straight_tracks=sum(queue_learner.counts.values()),lamp_labels_used=False)
        model['fingerprint'] = model_fingerprint(model)
        write_json(folder/'model.json', model)
        state.update(status='READY' if complete else 'PARTIAL', stage='finished', model_id=model['model_id'],
                     model_fingerprint=model['fingerprint'], regimes=len(catalogue)); checkpoint()
        return model
    except Exception as error:
        state.update(status='FAILED', stage='failed', reason=type(error).__name__+': '+str(error)[:600]); checkpoint()
        raise


def load_prediction(folder, session_id):
    folder = Path(folder); model = read_model(folder)
    session = next((s for s in model['sessions'] if s['session_id']==session_id), None)
    if session is None:
        raise KeyError('unknown session')
    path = folder/session['prediction']
    if digest(path) != session['prediction_sha256']:
        raise ValueError('stored prediction checksum mismatch')
    with gzip.open(path, 'rt', encoding='utf8') as stream:
        return model, session, json.load(stream)
