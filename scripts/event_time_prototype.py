"""Isolated synthetic experiment: finite-grid feasible graph + MAP diagnostic.

Not imported by production. No truth, annotation, template or fitting inputs.
Intervals are exact projections of the complete feasible DAG on a 1s grid,
NOT continuous-time bounds, posterior intervals, or calibrated lamp estimates.
"""
import math
import time
import numpy as np


PRIORS = {
    'uniform': {'min_s': 2, 'max_s': 40, 'family': 'uniform'},
    'nominal10': {'min_s': 2, 'max_s': 40, 'family': 'discrete_laplace',
                  'center_s': 10, 'scale_s': 5},
}


def duration_mass(prior):
    ds = np.arange(prior['min_s'], prior['max_s']+1)
    weights = (np.ones(len(ds)) if prior['family'] == 'uniform' else
               np.exp(-np.abs(ds-prior['center_s'])/prior['scale_s']))
    return dict(zip(ds.tolist(), (weights/weights.sum()).tolist()))


def observations(events, mapping, order, windows, horizon, rates, resolution_ms=1):
    """Poisson count sufficient statistics at event times; empty observed != missing.

    All potential transitions on integer seconds. Rounded cells straddling a
    potential transition are rejected as numerical-resolution unavailable,
    rather than silently moved across structural zeros. For accepted cells,
    log(rate) is the point-process log density, up to constant log(cell width).
    Bin counts are NOT binary occupancy; window exposure is exact here.
    """
    if horizon <= 0 or int(horizon) != horizon or len(order) != len(rates):
        raise ValueError('integer positive horizon / phase rates required')
    if len(set(order)) != len(order) or set(mapping.values()) != set(order):
        raise ValueError('known exclusive mapping/order required')
    if any(not math.isfinite(r) or r <= 0 for r in rates):
        raise ValueError('positive supplied rates required')
    if not math.isfinite(resolution_ms) or not 0 < resolution_ms < 1000:
        raise ValueError('timestamp resolution must lie in (0,1000)ms')
    exposure = np.zeros(horizon)
    last = 0
    for a,b in windows:
        if not 0 <= a < b <= horizon or a < last or int(a)!=a or int(b)!=b:
            raise ValueError('ordered disjoint grid-aligned supplied windows required')
        exposure[int(a):int(b)] = 1
        last = b
    counts = np.zeros((horizon, len(order)), dtype=int)
    for event in events:
        t = event['timestamp_ms']/1000
        if not math.isfinite(t) or event['movement'] not in mapping or not 0 <= t < horizon:
            raise ValueError('invalid event')
        if not exposure[int(t)]:
            raise ValueError('event outside supplied observation windows')
        if abs(t-round(t)) <= resolution_ms/2000:
            raise ArithmeticError('ROUNDING_CELL_STRADDLES_GRID_BOUNDARY')
        counts[int(t), order.index(mapping[event['movement']])] += 1
    return counts, exposure


def interval_loglik(counts, exposure, rates, a, b, z):
    counts = np.asarray(counts)[a:b].sum(axis=0)
    if counts.sum() != counts[z]:
        return -math.inf
    return float(counts[z]*math.log(rates[z])-rates[z]*np.sum(exposure[a:b]))


def infer(events, mapping, order, windows, horizon, rates, prior,
          max_seconds=3., max_edges=100000, max_states=5000, max_horizon=120,
          max_memory_bytes=16000000):
    started = time.process_time()
    base = {'interval_type': 'finite_grid_feasible_sets', 'grid_s': 1,
            'timestamp_resolution_ms': 1, 'physical_state': 'UNKNOWN',
            'cause': 'UNKNOWN', 'prior': prior, 'complete': False,
            'calibrated_probability': None, 'initial_phase': order[0],
            'initial_phase_start_s': 0, 'right_endpoint': 'censored',
            'assumptions': ['ideal exclusive marks', 'known observation windows',
                            'supplied stationary positive phase-specific Poisson rates',
                            'fixed cyclic order; integer boundaries; durations 2..40s']}

    def unavailable(reason):
        return dict(base, status='unavailable', reason=reason, diagnostic_segments=[],
                    boundary_sets=[], unknown_fraction=1., cpu_s=time.process_time()-started)

    if horizon > max_horizon or max_seconds <= 0:
        return unavailable('RESOURCE_LIMIT')
    # Conservative allocated-object allowance, not a measured RSS claim.
    if max_edges*128+max_states*512 > max_memory_bytes:
        return unavailable('DECLARED_MEMORY_ALLOWANCE_EXCEEDED')
    try:
        counts, exposure = observations(events, mapping, order, windows, horizon, rates)
    except ArithmeticError as exc:
        return unavailable(str(exc))
    mass = duration_mass(prior); k = len(order)
    min_d, max_d = min(mass), max(mass)
    cp = np.vstack([np.zeros(k, dtype=int), np.cumsum(counts,axis=0)])
    ep = np.r_[0,np.cumsum(exposure)]
    nodes = {(0,0): (0., None)}
    edges = []; terminals = []
    for t in range(horizon):
        for n in range(t//min_d+1):
            if (t,n) not in nodes:
                continue
            if time.process_time()-started > max_seconds:
                return unavailable('CPU_BUDGET_EXHAUSTED')
            z = n % k
            for u in range(t+1, min(horizon,t+max_d)+1):
                d = u-t; final = u == horizon
                if not final and d < min_d:
                    continue
                c = cp[u]-cp[t]
                if c.sum() != c[z]:
                    continue
                duration_p = sum(p for duration,p in mass.items() if duration >= d) if final else mass[d]
                if duration_p <= 0:
                    continue
                ll = float(c[z]*math.log(rates[z])-rates[z]*(ep[u]-ep[t]))
                score = nodes[(t,n)][0] + ll + math.log(duration_p)
                edges.append((t,n,u,final))
                if len(edges)>max_edges or len(nodes)>max_states:
                    return unavailable('GRAPH_BUDGET_EXHAUSTED')
                if final:
                    terminals.append((score,(t,n)))
                elif (u,n+1) not in nodes or score > nodes[(u,n+1)][0]:
                    nodes[(u,n+1)] = (score,(t,n))
    if not terminals:
        return unavailable('NO_FEASIBLE_PATH_UNDER_DECLARED_MODEL')
    live = {node for _,node in terminals}
    for t,n,u,final in reversed(edges):
        if final or (u,n+1) in live:
            live.add((t,n))
    feasible_edges = [e for e in edges if e[3] or (e[2],e[1]+1) in live]
    terminal_counts = sorted({n for _,(_,n) in terminals})
    boundary_sets = []
    for j in range(1,max(terminal_counts)+1):
        times = sorted({u for t,n,u,final in feasible_edges if not final and n+1==j})
        boundary_sets.append({'ordinal':j, 'from_phase':order[(j-1)%k], 'to_phase':order[j%k],
                              'times_s':times, 'exists_in_all_paths':min(terminal_counts)>=j,
                              'hull_s':[min(times),max(times)] if times else None})
    best_score, node = max(terminals, key=lambda x:x[0])
    segments = [[node[0],horizon,node[1]%k]]
    while node != (0,0):
        prev = nodes[node][1]
        segments.append([prev[0],node[0],prev[1]%k]); node=prev
    segments.reverse()
    # Marginal phase possibility sets, including paths with different cycle counts.
    possible = [set() for _ in range(horizon)]
    for t,n,u,_ in feasible_edges:
        for second in range(t,u):
            possible[second].add(order[n%k])
    unknown = [len(s)!=1 or exposure[i]==0 or not events for i,s in enumerate(possible)]
    return dict(base,status='complete_grid_search',complete=True,
                diagnostic_segments=segments, diagnostic_score=best_score,
                boundary_sets=boundary_sets, possible_transition_counts=terminal_counts,
                phase_possibilities=[sorted(s) for s in possible],
                feasible_graph=feasible_edges, event_count=len(events),
                observed_seconds=int(exposure.sum()), input_horizon_s=horizon,
                unknown_fraction=sum(unknown)/horizon,
                unknown_reasons=['MULTIPLE_FEASIBLE_PHASES','MISSING_INPUT'] + ([] if events else ['NO_EVENTS_NO_CAUSE_IDENTIFIED']),
                observation_support='event counts + supplied exposure; silence informs only under supplied rate model',
                point_support='Poisson likelihood + duration prior; diagnostic, not identified history',
                cpu_s=time.process_time()-started, reachable_states=len(nodes),edge_count=len(edges))
