"""Actual browser UI over TestClient ASGI requests; no listening web server."""
import argparse
import json
from pathlib import Path
import site
import time
from urllib.parse import urlsplit

from scripts.corpus_validation import ROOT,save,prepare_worker_environment
prepare_worker_environment()
site.addsitedir(str(ROOT/'.web_runtime/model_phase_view_20261018/qa_venv/Lib/site-packages'))
from playwright.sync_api import sync_playwright
from fastapi.testclient import TestClient
from app.main import app


def main(job_file,out):
    identifier=json.loads(Path(job_file).read_text())['model_id'];out=Path(out)
    out.mkdir(parents=True,exist_ok=False);errors=[];requests=[];begin=time.monotonic()
    with TestClient(app) as client,sync_playwright() as playwright:
        browser=playwright.chromium.launch(channel='msedge',headless=True)
        context=browser.new_context(viewport=dict(width=1440,height=1000));page=context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        def route(request_route):
            request=request_route.request;url=urlsplit(request.url)
            path=url.path+('?' + url.query if url.query else '')
            response=client.request(request.method,path,content=request.post_data_buffer,
                headers={k:v for k,v in request.headers.items() if k.lower()=='content-type'})
            requests.append(dict(method=request.method,path=path,status=response.status_code))
            request_route.fulfill(status=response.status_code,body=response.content,
                content_type=response.headers.get('content-type','application/octet-stream'))
        page.route('http://traffic.test/**',route)
        try:
            page.goto('http://traffic.test/visualization?project='+identifier,wait_until='domcontentloaded')
            page.wait_for_selector('#result:visible',timeout=300000)
            assert page.locator('#session option').count()==3
            assert page.locator('#intersection-profile').count()==0
            assert page.evaluate('model.regimes.every(r=>r.phase_count===3)')
            frame=page.frame_locator('#viewer');frame.locator('#play').wait_for(timeout=120000)
            frame.locator('#phaseTimeline button').first.wait_for(timeout=120000)
            frame.locator('#slider').evaluate("e=>{e.value=120;e.dispatchEvent(new Event('input'))}")
            before=frame.locator('body').evaluate('()=>window.__V10_DEBUG__.current_time_s')
            frame.locator('#play').click();page.wait_for_timeout(500);frame.locator('#pause').click()
            assert frame.locator('body').evaluate('()=>window.__V10_DEBUG__.current_time_s')>before
            assert frame.locator('#displayMode').input_value()=='signals'
            assert frame.locator('body').evaluate('()=>ESTIMATED_SIGNALS.profile_id') is None
            target=frame.locator('body').evaluate('()=>localSeekValue(DISPLAY_BASE_MS+123400)')
            frame.locator('#seekTime').fill(target)
            frame.locator('#seekGo').click()
            assert abs(frame.locator('body').evaluate('()=>window.__V10_DEBUG__.current_time_s')-123.4)<.01
            page.screenshot(path=str(out/'real_desktop.png'),full_page=True)
            page.set_viewport_size(dict(width=390,height=844))
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(out/'real_mobile.png'),full_page=True)
            page.goto('http://traffic.test/visualization',wait_until='domcontentloaded')
            page.wait_for_selector('#result:visible',timeout=30000)
            assert page.evaluate('identifier')==identifier
            # Exercise the actual upload button and real background worker.
            source=ROOT/'.web_runtime/all_archives_synthetic_20261019/synthetic/k2_ordinary_0/input.zip'
            page.locator('#file').set_input_files(dict(name='anonymous.zip',mimeType='application/zip',buffer=source.read_bytes()))
            page.locator('#analyze').click()
            page.wait_for_selector('#result:visible',timeout=180000)
            assert page.locator('#session option').count()==1
            assert page.evaluate('model.input.name')=='anonymous.zip'
            assert page.evaluate('model.regimes[0].phase_count')==2
            assert not page.evaluate('model.known_hardware_profile_used')
            frame=page.frame_locator('#viewer');frame.locator('#play').wait_for(timeout=120000)
            page.screenshot(path=str(out/'upload_mobile.png'),full_page=True)
            assert not errors,errors
            save(out/'receipt.json',dict(status='PASS',browser='isolated headless Edge; ASGI routing, no user profile/server',
                actual_upload=True,real_archive_model=identifier,three_sessions=True,working_K=3,
                manual_profiles=False,playback=True,slider=True,mobile_no_overflow=True,
                persisted_restore=True,date_time_seek=True,anonymous_synthetic_K=2,new_model_id=page.evaluate('identifier'),
                javascript_errors=errors,requests=requests,runtime_s=time.monotonic()-begin))
            print('Browser full workflow PASS',flush=True)
        except Exception as error:
            page.screenshot(path=str(out/'failed.png'),full_page=True)
            save(out/'failed_receipt.json',dict(status='FAIL',error=str(error),javascript_errors=errors,requests=requests))
            raise
        finally:browser.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--job',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();main(args.job,args.out)
