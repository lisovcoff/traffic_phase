"""Actual HTTP and local Edge checks of the counterfactual delivery."""
import itertools
import json
import site
import urllib.request
from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from app.core.intersection_project import read_json
from scripts.check_incident_counterfactual import OUT,RUNTIME,MODEL


def request(url,payload=None):
    data=json.dumps(payload).encode() if payload is not None else None
    r=urllib.request.Request(url,data=data,headers={'Content-Type':'application/json'},
                             method='POST' if payload is not None else 'GET')
    with urllib.request.urlopen(r,timeout=90) as response:return json.load(response)


def main():
    base=f'http://127.0.0.1:8017/api/v1/intersections/{MODEL}/online'
    stream=request(base,{})['stream_id'];endpoint=base+'/'+stream
    with (RUNTIME/'extended.jsonl').open() as packets,(RUNTIME/'extended_issuance.jsonl').open() as issued:
        for n,(line,expected) in enumerate(itertools.islice(zip(packets,issued),24),1):
            packet=json.loads(line);actual=request(endpoint+'/packets',packet);expected=json.loads(expected)
            assert actual['heads']==expected['heads'] and actual['phase_id']==expected['phase']
            if n==24:assert request(endpoint+'/packets',packet)==actual
    assert len(request(endpoint+'/history')['snapshots'])==24
    site.addsitedir(str(ROOT/'.web_runtime/model_phase_view_20261018/qa_venv/Lib/site-packages'))
    from playwright.sync_api import sync_playwright
    out=OUT/'browser';out.mkdir(exist_ok=False);errors=[];checked=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport=dict(width=1440,height=1000))
        page.on('pageerror',lambda e:errors.append(str(e)))
        try:
            page.goto((OUT/'report_paired.html').as_uri())
            assert page.locator('#sim tr').count()==6
            assert '147/165' in page.locator('#metric').inner_text()
            page.locator('#base').click();assert '147/153' in page.locator('#metric').inner_text()
            page.locator('#extra').click();page.locator('#seek').evaluate('e=>{e.value=72;e.dispatchEvent(new Event("input"))}')
            assert 'GREEN' in page.locator('#cursor').inner_text() and 'RED' in page.locator('#cursor').inner_text()
            page.screenshot(path=str(out/'comparison.png'),full_page=True)
            for name in ('baseline','extended'):
                result=read_json(OUT/(name+'_result.json'));page.goto(result['url'],wait_until='domcontentloaded')
                page.wait_for_function('document.getElementById("viewer").contentWindow.__V10_DEBUG__?.online===true',timeout=90000)
                frame=page.frame_locator('#viewer');target=1740634572000
                formatted=frame.locator('body').evaluate('(e,t)=>localSeekValue(t)',target).removesuffix('.000')
                frame.locator('#seekTime').fill(formatted);frame.locator('#seekGo').click()
                page.wait_for_function('t=>document.getElementById("viewer").contentWindow.__V10_DEBUG__?.historical===true && document.getElementById("viewer").contentWindow.__V10_DEBUG__?.timestamp_ms===t',arg=target,timeout=30000)
                debug=frame.locator('body').evaluate('()=>window.__V10_DEBUG__')
                expected=request(base+'/'+result['stream_id']+'/at?timestamp_ms='+str(target))['snapshot']
                assert debug['heads']==expected['heads']
                checked.append(dict(case=name,timestamp_ms=target,color=debug['heads']['N']['main']['state']))
                page.screenshot(path=str(out/(name+'_player.png')),full_page=True)
            assert not errors,errors
            save(out/'receipt.json',dict(status='PASS',ordinary_HTTP_exact_prefix=24,retry_idempotent=True,
                verification_stream_id=stream,comparison_report_controls=True,full_saved_players=checked,
                javascript_errors=errors,scope='UI and causal core parity; lamp accuracy failure remains'))
        except Exception as e:
            page.screenshot(path=str(out/'failed.png'),full_page=True)
            save(out/'failed.json',dict(error=str(e),javascript_errors=errors));raise
        finally:browser.close()
    print('INCIDENT HTTP / BROWSER PASS',flush=True)


if __name__=='__main__':main()
