"""Actual local HTTP/Edge check of new models and original causal color history."""
import json
import site
import time
import urllib.request

from scripts.corpus_validation import ROOT,save,prepare_worker_environment
prepare_worker_environment()


def main(revision='v6',run_name=None):
    site.addsitedir(str(ROOT/'.web_runtime/model_phase_view_20261018/qa_venv/Lib/site-packages'))
    from playwright.sync_api import sync_playwright
    parent=ROOT/'evidence/cross_day_model_selection_20261019'
    job=json.loads((parent/('release_'+revision)/'release_job.json').read_text(encoding='utf8'))
    out=parent/(run_name or 'browser_'+revision);out.mkdir(exist_ok=False)
    base='http://127.0.0.1:8017';identifier=job['model_id'];errors=[];views=[];began=time.monotonic()
    model=json.loads((ROOT/'logs/intersection_projects'/identifier/'model.json').read_text(encoding='utf8'))
    selected={}
    for s in model['sessions']:selected.setdefault(s['phase_count'],s)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True);page=browser.new_page(viewport=dict(width=1440,height=1000))
        page.on('pageerror',lambda e:errors.append(str(e)))
        try:
            page.goto(base+'/visualization?project='+identifier,wait_until='domcontentloaded')
            page.wait_for_selector('#result:visible',timeout=90000)
            assert page.locator('#session option').count()==88
            frame=page.frame_locator('#viewer')
            for k,s in selected.items():
                page.locator('#session').select_option(s['session_id'])
                page.wait_for_function('m=>document.getElementById("viewer").contentDocument?.getElementById("input-scope")?.textContent.includes(m)',arg=s['source_member'],timeout=90000)
                frame.locator('#play').wait_for(timeout=90000)
                frame.locator('#slider').evaluate('e=>{e.value=123.4;e.dispatchEvent(new Event("input"))}')
                assert abs(frame.locator('body').evaluate('()=>window.__V10_DEBUG__.current_time_s')-123.4)<.01
                frame.locator('#play').click();page.wait_for_timeout(250);frame.locator('#pause').click()
                assert frame.locator('body').evaluate('()=>window.__V10_DEBUG__.current_time_s')>123.4
                views.append(dict(member=s['source_member'],K=k))
            page.screenshot(path=str(out/'offline.png'),full_page=True)
            page.goto(job['url'],wait_until='domcontentloaded')
            page.wait_for_function('document.getElementById("viewer").contentWindow.__V10_DEBUG__?.online===true',timeout=90000)
            frame=page.frame_locator('#viewer')
            assert page.evaluate('onlineStream')==job['stream_id']
            endpoint=base+'/api/v1/intersections/'+identifier+'/online/'+job['stream_id']
            with urllib.request.urlopen(endpoint,timeout=30) as r:latest=json.load(r)['snapshot']
            page.wait_for_function('n=>document.getElementById("viewer").contentWindow.__V10_DEBUG__?.sequence===n',arg=latest['sequence'])
            checked=[]
            for target in [1740634518000,1740634565000,1740634570000]:
                formatted=frame.locator('body').evaluate('(e,t)=>localSeekValue(t)',target).removesuffix('.000')
                frame.locator('#seekTime').fill(formatted);frame.locator('#seekGo').click()
                page.wait_for_function('t=>document.getElementById("viewer").contentWindow.__V10_DEBUG__?.historical===true && document.getElementById("viewer").contentWindow.__V10_DEBUG__?.timestamp_ms<=t && document.getElementById("viewer").contentWindow.__V10_DEBUG__?.timestamp_ms>t-1000',arg=target)
                debug=frame.locator('body').evaluate('()=>window.__V10_DEBUG__')
                with urllib.request.urlopen(endpoint+'/at?timestamp_ms='+str(target),timeout=30) as response:expected=json.load(response)['snapshot']
                assert debug['heads']==expected['heads']
                assert [a['movement'] for a in debug['heads']['N']['arrows']]==['N->E']
                assert [a['movement'] for a in debug['heads']['E']['arrows']]==['E->N']
                checked.append(dict(timestamp_ms=target,color=debug['heads']['N']['main']['state']))
            page.screenshot(path=str(out/'online_history.png'),full_page=True)
            frame.locator('#liveResume').click();page.wait_for_function('document.getElementById("viewer").contentWindow.__V10_DEBUG__?.historical===false')
            page.reload();page.wait_for_function('document.getElementById("viewer").contentWindow.__V10_DEBUG__?.online===true',timeout=90000)
            page.set_viewport_size(dict(width=390,height=844));assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(out/'mobile.png'),full_page=True)
            assert not errors,errors
            save(out/'receipt.json',dict(status='PASS',model_id=identifier,stream_id=job['stream_id'],offline_views=views,
                online_color_equality_with_journal=checked,reload=True,resume=True,mobile=True,javascript_errors=errors,runtime_s=time.monotonic()-began))
        except Exception as e:
            page.screenshot(path=str(out/'failed.png'),full_page=True)
            save(out/'failed_receipt.json',dict(status='FAIL',error=str(e),javascript_errors=errors))
            raise
        finally:browser.close()
    print('BROWSER',revision,'PASS',checked,flush=True)


if __name__=='__main__':
    import sys
    main(sys.argv[1] if len(sys.argv)>1 else 'v6',sys.argv[2] if len(sys.argv)>2 else None)
