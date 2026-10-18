"""Execute actual viewer JS: activity colors must not replace physical truth."""
import json
import re
import shutil
import subprocess

import pytest

from scripts.v9_spatial_visualizer import render_html


def prediction():
    return dict(schedule_base_timestamp_ms=6000, recording_start_timestamp_ms=1000,
        analysis_base_timestamp_ms=6000, recording_duration_s=35,
        schedule=dict(phase_count=2, phase_names=['A', 'B'], period_s=20,
            raw_hsmm_segments=[[0, 10, 0], [12, 20, 1]],
            baseline_segments=[[0, 10, 0], [10, 20, 1]],
            stream_activity_by_phase=[
                {'stream': 'N->S', 'event_probability_by_phase': {'A': .023, 'B': .01}},
                {'stream': 'E->W', 'event_probability_by_phase': {'A': .01, 'B': .015}},
                {'stream': 'N->E', 'event_probability_by_phase': {'A': .9, 'B': .8}},
                {'stream': 'S->N', 'event_probability_by_phase': {'A': .2, 'B': .2}},
                {'stream': 'W->E', 'event_probability_by_phase': {'A': .9}},
            ]))


def run_js(times):
    if not shutil.which('node'):
        pytest.skip('Node is required for actual JavaScript contract checks')
    page = render_html(prediction(), {}, [])
    script = re.search(r'<script>(.*?)</script>', page, re.S).group(1)
    # All pure functions above UI listeners, including the actual timebase lookup.
    script = script.split('window.addEventListener("resize",resizeCanvas);')[0]
    harness = '''
const vm=require('node:vm'),fs=require('node:fs'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const context={document:{getElementById:()=>({value:'model'})}};vm.createContext(context);
vm.runInContext(input.script,context);
const rows=input.times.map(t=>vm.runInContext(`(()=>{const s=signalSnapshot(${t});
  return {phase:s.phase,reason:s.abstention_reason,physical:s.heads,activity:phaseMovements(s.phase)};})()`,context));
process.stdout.write(JSON.stringify(rows));
'''
    result = subprocess.run([shutil.which('node'), '-e', harness],
        input=json.dumps(dict(script=script, times=times)), text=True, capture_output=True,
        encoding='utf-8', timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def states(row):
    return {item['movement']: item['state'] for items in row['activity'].values() for item in items}


def test_sparse_signatures_are_visible_and_follow_history_instead_of_periodic_wrap():
    first, second, outside = run_js([6, 18, 26])
    assert states(first)['N->S'] == 'ACTIVE'
    assert states(first)['E->W'] == 'INACTIVE'
    assert states(second)['N->S'] == 'INACTIVE'
    assert states(second)['E->W'] == 'ACTIVE'
    assert all(value == 'UNAVAILABLE' for value in states(outside).values())


def test_shared_movements_and_constant_scores_are_not_forced_to_a_single_phase():
    first, second = run_js([6, 18])
    assert states(first)['N->E'] == states(second)['N->E'] == 'ACTIVE'
    assert states(first)['S->N'] == states(second)['S->N'] == 'NONSELECTIVE'


def test_missing_score_is_unknown_not_zero_or_closed_permission():
    first, second = run_js([6, 18])
    assert states(first)['W->E'] == 'ACTIVE'
    assert states(second)['W->E'] == 'UNAVAILABLE'


def test_gap_and_missing_pre_anchor_phase_have_no_color_and_keep_lamps_unknown():
    for row in run_js([0, 15, 16, 25, 35]):
        assert row['phase'] is None
        assert all(value == 'UNAVAILABLE' for value in states(row).values())
        assert all(head['main']['state'] == 'UNKNOWN' for head in row['physical'].values())
    for row in run_js([6, 18]):
        assert all(head['main']['state'] == 'UNKNOWN' for head in row['physical'].values())
