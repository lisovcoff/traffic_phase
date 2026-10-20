"""Transition labels explain uncertainty without changing the inferred signals."""
import json
import shutil
import subprocess

import pytest


def node_json(script):
    node=shutil.which('node')
    if not node:pytest.skip('Node required for browser logic regression')
    return json.loads(subprocess.run([node,'-e',script],capture_output=True,text=True,check=True,encoding='utf8').stdout)


def test_short_colors_are_annotated_without_changing_colors_or_support():
    from scripts.v9_spatial_visualizer import PAGE
    function='function transitionAnnotation(main){'+PAGE.split('function transitionAnnotation(main){',1)[1].split('function renderSignalList',1)[0]
    result=node_json(function+'''
const heads=['GREEN','RED','YELLOW','RED_YELLOW','UNKNOWN'].map(state=>({state,confidence:.37}));
const original=JSON.stringify(heads);
const notes=heads.map(transitionAnnotation);
process.stdout.write(JSON.stringify({unchanged:original===JSON.stringify(heads),annotated:notes.map(Boolean),notes}));
''')
    assert result['unchanged']
    assert result['annotated']==[False,False,True,True,False]
    assert all('37%' in result['notes'][i]['title'] for i in (2,3))


def test_model_and_stream_selection_replace_stale_bookmark_parameters():
    from app.api.intersection_panel import PAGE
    function='function rememberSelection(project,stream=null){'+PAGE.split('function rememberSelection(project,stream=null){',1)[1].split('function showLive',1)[0]
    result=node_json('''
global.location={href:'http://localhost/visualization?project=old&stream=previous&keep=value'};
const urls=[];global.history={replaceState:(a,b,url)=>{location.href=String(url);urls.push(location.href);}};
'''+function+'''
rememberSelection('new');rememberSelection('new','current');rememberSelection('new');
process.stdout.write(JSON.stringify(urls.map(u=>Object.fromEntries(new URL(u).searchParams))));
''')
    assert result==[dict(project='new',keep='value'),dict(project='new',keep='value',stream='current'),dict(project='new',keep='value')]
