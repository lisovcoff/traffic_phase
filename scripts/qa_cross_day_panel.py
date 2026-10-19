"""Actual HTTP/Edge: all training days/regimes and the held-day online history."""
import argparse
import json
import site
import time
import urllib.request

from scripts.corpus_validation import ROOT,save,prepare_worker_environment
prepare_worker_environment()


def main(run_name='browser_v2'):
    site.addsitedir(str(ROOT/'.web_runtime/model_phase_view_20261018/qa_venv/Lib/site-packages'))
    from playwright.sync_api import sync_playwright
    parent=ROOT/'evidence/cross_day_sverdlovsky_20261019'
    if not run_name or '/' in run_name or '\\' in run_name:raise ValueError('run name must be one directory name')
    job=json.loads((parent/'online_job.json').read_text());out=parent/run_name;out.mkdir(exist_ok=False)
    base='http://127.0.0.1:8017';identifier=job['model_id'];errors=[];views=[]
    model=json.loads((ROOT/'logs/intersection_projects'/identifier/'model.json').read_text(encoding='utf8'))
    sessions={s['session_id']:s for s in model['sessions']};selected={}
    for regime in model['regimes']:
        sid=regime['members'][0]['session_id'];selected[sid]=sessions[sid]
    dates={s['source_member'].split('_')[3] for s in selected.values()}
    for s in model['sessions']:
        day=s['source_member'].split('_')[3]
        if day not in dates:selected[s['session_id']]=s;dates.add(day)
    assert len(dates)==7
    begin=time.monotonic()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport=dict(width=1440,height=1000))
        page.on('pageerror',lambda e:errors.append(str(e)))
        try:
            page.goto(base+'/visualization?project='+identifier,wait_until='domcontentloaded')
            page.wait_for_selector('#result:visible',timeout=60000)
            assert page.locator('#session option').count()==88
            frame=page.frame_locator('#viewer')
            for sid,session in selected.items():
                started=time.monotonic();page.locator('#session').select_option(sid)
                page.wait_for_function('member=>document.getElementById("viewer").contentDocument?.getElementById("input-scope")?.textContent.includes(member)',arg=session['source_member'],timeout=60000)
                frame.locator('#play').wait_for(timeout=60000)
                frame.locator('#slider').evaluate('e=>{e.value=123.4;e.dispatchEvent(new Event("input"))}')
                assert abs(frame.locator('body').evaluate('()=>window.__V10_DEBUG__.current_time_s')-123.4)<.01
                frame.locator('#play').click();page.wait_for_timeout(300);frame.locator('#pause').click()
                assert frame.locator('body').evaluate('()=>window.__V10_DEBUG__.current_time_s')>123.4
                assert frame.locator('#error').inner_text()==''
                views.append(dict(member=session['source_member'],regime=session['regime_id'],seconds=time.monotonic()-started))
                print('VIEW',session['source_member'],session['regime_id'],round(views[-1]['seconds'],1),flush=True)
            page.screenshot(path=str(out/'offline.png'),full_page=True)
            page.goto(job['view_url'],wait_until='domcontentloaded')
            page.wait_for_function('document.getElementById("viewer").contentWindow.__V10_DEBUG__?.online===true',timeout=60000)
            assert page.evaluate('onlineStream')==job['stream_id']
            with urllib.request.urlopen(base+'/api/v1/intersections/'+identifier+'/online/'+job['stream_id'],timeout=15) as response:latest=json.load(response)['snapshot']
            page.wait_for_function('seq=>document.getElementById("viewer").contentWindow.__V10_DEBUG__?.sequence===seq',arg=latest['sequence'])
            frame=page.frame_locator('#viewer')
            target=1740634516000
            formatted=frame.locator('body').evaluate('(e,ms)=>localSeekValue(ms)',target).removesuffix('.000')
            frame.locator('#seekTime').fill(formatted);frame.locator('#seekGo').click()
            page.wait_for_function('document.getElementById("viewer").contentWindow.__V10_DEBUG__?.historical===true')
            assert frame.locator('body').evaluate('()=>window.__V10_DEBUG__.timestamp_ms')<=target
            page.screenshot(path=str(out/'online_history.png'),full_page=True)
            frame.locator('#liveResume').click()
            page.wait_for_function('document.getElementById("viewer").contentWindow.__V10_DEBUG__?.historical===false')
            page.reload()
            page.wait_for_function('document.getElementById("viewer").contentWindow.__V10_DEBUG__?.online===true',timeout=60000)
            assert page.evaluate('onlineStream')==job['stream_id']
            page.set_viewport_size(dict(width=390,height=844));page.wait_for_timeout(200)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(out/'mobile.png'),full_page=True)
            assert not errors,errors
            save(out/'receipt.json',dict(status='PASS',model_id=identifier,stream_id=job['stream_id'],
                days=7,all_regimes=len(model['regimes']),recordings_in_selector=88,checked_views=views,
                online_url_selects_saved_stream=True,history_seek=True,resume=True,reload=True,mobile=True,
                latest_sequence=latest['sequence'],javascript_errors=errors,runtime_s=time.monotonic()-begin))
        except Exception as e:
            page.screenshot(path=str(out/'failed.png'),full_page=True)
            save(out/'failed_receipt.json',dict(status='FAIL',error=str(e),javascript_errors=errors,checked_views=views))
            raise
        finally:browser.close()
    print('CROSS-DAY PANEL PASS',len(views),'views',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-name',default='browser_v2')
    main(parser.parse_args().run_name)
