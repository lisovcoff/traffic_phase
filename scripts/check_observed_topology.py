"""Queue-simulated T intersection, autonomous archive inference and browser QA.

This is a geometry/integration counterexample, not a new accuracy holdout.
The simulator truth is saved separately and never passed to the application.
"""
import argparse
import json
from pathlib import Path
import site
import time
import uuid
import zipfile
from urllib.parse import urlsplit

from scripts.corpus_validation import ROOT,save,prepare_worker_environment
prepare_worker_environment()


def main(out):
    from scripts import realistic_traffic_benchmark as simulator
    from app.core.intersection_project import run_project,read_json
    from app.api.intersection_projects import PROJECT_ROOT
    from app.main import app
    from fastapi.testclient import TestClient
    out=Path(out);out.mkdir(parents=True,exist_ok=False);begin=time.monotonic()
    config=dict(seed=2026101901,k=2,duration_s=1200,period_s=90,
        arrival_rate_s=.07,cycle_jitter=.01,realistic_turns=True)
    environment=read_json(ROOT/'evidence/all_archives_synthetic_20261019/simulation_environment.json')
    original=simulator.GROUPS[2]
    try:
        simulator.GROUPS[2]=[['N->_S','S->_N'],['E->_N','N->_E']]
        tracks,truth=simulator.generate(config,environment)
    finally:simulator.GROUPS[2]=original
    save(out/'truth_sealed.json',truth)
    identifier=uuid.uuid4().hex;folder=PROJECT_ROOT/identifier;folder.mkdir(parents=True)
    source=folder/'input.zip'
    with zipfile.ZipFile(source,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('anonymous.json',json.dumps(tracks,separators=(',',':')))
    model=run_project(source,folder)
    assert model['approaches']==['N','S','E'],model['approaches']
    assert model['completeness']=='COMPLETE'
    assert all(r['phase_count']==2 for r in model['regimes']),model['regimes']
    assert all(set(r['signal_topology'])=={'N','S','E'} for r in model['regimes'])
    assert all(r['signal_topology']['E']['main']=='E->N' for r in model['regimes'])
    save(out/'model.json',{k:v for k,v in model.items() if k!='input_path_private'})
    site.addsitedir(str(ROOT/'.web_runtime/model_phase_view_20261018/qa_venv/Lib/site-packages'))
    from playwright.sync_api import sync_playwright
    errors=[]
    with TestClient(app) as client,sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport=dict(width=1365,height=1000))
        page.on('pageerror',lambda error:errors.append(str(error)))
        def route(rr):
            req=rr.request;url=urlsplit(req.url)
            response=client.request(req.method,url.path+('?' + url.query if url.query else ''))
            rr.fulfill(status=response.status_code,body=response.content,
                content_type=response.headers.get('content-type','application/octet-stream'))
        page.route('http://traffic.test/**',route)
        try:
            page.goto('http://traffic.test/visualization?project='+identifier)
            frame=page.frame_locator('#viewer')
            frame.locator('#phaseTimeline button').first.wait_for(timeout=120000)
            active=frame.locator('body').evaluate('()=>ACTIVE_APPROACHES')
            assert active==['N','S','E'],active
            assert frame.locator('body').evaluate('()=>Object.keys(window.__V10_DEBUG__.heads)')==active
            assert frame.locator('body').evaluate('()=>Object.keys(ESTIMATED_SIGNALS.topology)')==active
            assert frame.locator('body').evaluate('()=>ESTIMATED_SIGNALS.profile_id') is None
            colors=frame.locator('body').evaluate("()=>ESTIMATED_SIGNALS.states.map(s=>s.heads.E.main.state)")
            assert {'GREEN','RED'}<=set(colors),colors
            frame.locator('#slider').evaluate("e=>{e.value=120;e.dispatchEvent(new Event('input'))}")
            assert 'W ←' not in frame.locator('#sceneBadge').inner_text()
            page.screenshot(path=str(out/'t_desktop.png'),full_page=True)
            page.set_viewport_size(dict(width=390,height=844))
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(out/'t_mobile.png'),full_page=True)
            assert not errors,errors
            save(out/'receipt.json',dict(status='PASS',model_id=identifier,approaches=active,
                tracks=len(tracks),detections=truth['counts']['detections'],
                working_k=[r['phase_count'] for r in model['regimes']],
                false_fourth_head=False,known_profile_used=False,truth_used_by_algorithm=False,
                browser_errors=errors,scope='integration/geometry; NOT independent timing validation',
                runtime_s=time.monotonic()-begin))
            print('T geometry and browser PASS',identifier,flush=True)
        except Exception as error:
            page.screenshot(path=str(out/'failed.png'),full_page=True)
            save(out/'failed_receipt.json',dict(status='FAIL',error=str(error),browser_errors=errors))
            raise
        finally:browser.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    main(parser.parse_args().out)
