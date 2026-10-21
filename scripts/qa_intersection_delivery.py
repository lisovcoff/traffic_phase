"""Optional headless-browser acceptance of the real offline/online panel."""
import argparse
import json
from pathlib import Path
from scripts._environment import prepare_worker_environment


def check(base,project,packets,out,limit=120):
    prepare_worker_environment()
    from playwright.sync_api import sync_playwright
    from app.core.intersection_engine import VERSION
    out.mkdir(parents=True,exist_ok=False)
    rows=[]
    with packets.open(encoding='utf8') as source:
        for line in source:
            if line.strip():rows.append(json.loads(line))
            if len(rows)>=limit:break
    if len(rows)<12:raise ValueError('At least 12 packets required')
    feed=out/'input_prefix.jsonl'
    with feed.open('x',encoding='utf8',newline='\n') as handle:
        for row in rows:handle.write(json.dumps(row)+'\n')
    errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport=dict(width=1440,height=1000))
        page.on('pageerror',lambda e:errors.append(str(e)))
        try:
            page.goto(base+'/visualization?project='+project,wait_until='domcontentloaded')
            page.wait_for_selector('#result:visible',timeout=120000)
            sessions=page.locator('#session option').count()
            page.locator('#onlineMode').click()
            page.wait_for_function("document.getElementById('viewer').contentWindow.__V10_DEBUG__?.online===true",timeout=120000)
            page.locator('#liveSpeed').select_option('0')
            page.locator('#liveFile').set_input_files(str(feed.resolve()))
            page.wait_for_function("seq=>document.getElementById('viewer').contentWindow.__V10_DEBUG__?.sequence===seq",arg=rows[-1]['sequence'],timeout=180000)
            stream=page.evaluate('onlineStream')
            endpoint=base+f'/api/v1/intersections/{project}/online/{stream}'
            latest=page.request.get(endpoint).json()
            assert latest['engine']==VERSION and latest['snapshot']['schema']==VERSION
            assert latest['snapshot']['timestamp_ms']==rows[-1]['timestamp_ms']
            assert any(h['main']['state']!='UNKNOWN' for h in latest['snapshot']['heads'].values())
            page.screenshot(path=str(out/'online_desktop.png'),full_page=True)
            frame=page.frame_locator('#viewer')
            target=frame.locator('body').evaluate('(e,ms)=>localSeekValue(ms)',rows[10]['timestamp_ms']).removesuffix('.000')
            frame.locator('#seekTime').fill(target);frame.locator('#seekGo').click()
            page.wait_for_function("document.getElementById('viewer').contentWindow.__V10_DEBUG__?.historical===true")
            assert frame.locator('body').evaluate('()=>window.__V10_DEBUG__.sequence')==rows[10]['sequence']
            frame.locator('#liveResume').click()
            page.wait_for_function("seq=>document.getElementById('viewer').contentWindow.__V10_DEBUG__?.sequence===seq",arg=rows[-1]['sequence'])
            page.reload()
            page.wait_for_function("seq=>document.getElementById('viewer').contentWindow.__V10_DEBUG__?.sequence===seq",arg=rows[-1]['sequence'],timeout=120000)
            assert page.evaluate('onlineStream')==stream
            assert len(page.request.get(endpoint+'/history').json()['snapshots'])==len(rows)
            page.set_viewport_size(dict(width=390,height=844))
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(out/'online_mobile.png'),full_page=True)
            page.set_viewport_size(dict(width=1440,height=1000))
            page.locator('#archiveMode').click()
            frame.locator('#play').wait_for(timeout=120000)
            frame.locator('#slider').evaluate('e=>{e.value=123.4;e.dispatchEvent(new Event("input"))}')
            frame.locator('#play').click();page.wait_for_timeout(300);frame.locator('#pause').click()
            assert frame.locator('body').evaluate('()=>window.__V10_DEBUG__.current_time_s')>123.4
            page.screenshot(path=str(out/'offline_desktop.png'),full_page=True)
            assert not errors,errors
            receipt=dict(status='PASS',project=project,stream=stream,engine=VERSION,packets=len(rows),
                session_count=sessions,history_seek=True,resume=True,reload=True,
                offline_play_seek=True,mobile_no_overflow=True,javascript_errors=errors)
            (out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8',newline='\n')
            return receipt
        except Exception as error:
            page.screenshot(path=str(out/'failed.png'),full_page=True)
            (out/'failed.json').write_text(json.dumps(dict(error=str(error),javascript_errors=errors)),encoding='utf8')
            raise
        finally:browser.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',default='http://127.0.0.1:8018')
    parser.add_argument('--project',required=True)
    parser.add_argument('--packets',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--limit',default=120,type=int)
    args=parser.parse_args()
    print(json.dumps(check(args.base,args.project,args.packets,args.out,args.limit),indent=2))
