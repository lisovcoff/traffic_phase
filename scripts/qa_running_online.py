"""Exercise replay and persistent completion against an actual running server."""
import argparse
import json
from pathlib import Path
import site
import time

from scripts.corpus_validation import ROOT, prepare_worker_environment, save
prepare_worker_environment()


def main(base,out,identifier='1eada5fee84648b389dd6bfded3ad153'):
    site.addsitedir(str(ROOT/'.web_runtime/model_phase_view_20261018/qa_venv/Lib/site-packages'))
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True,exist_ok=False)
    feed=ROOT/'evidence/intersection_online_20261019/browser_v7/real_packets.jsonl'
    packets=[json.loads(line) for line in feed.read_text(encoding='utf8').splitlines() if line.strip()]
    errors=[];requests=[];begin=time.monotonic()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport=dict(width=1440,height=1000))
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('requestfinished',lambda r:requests.append(dict(url=r.url,method=r.method,timing=r.timing)))
        try:
            page.goto(base+'/visualization?project='+identifier,wait_until='domcontentloaded')
            frame=page.frame_locator('#viewer');frame.locator('#play').wait_for(timeout=45000)
            page.locator('#liveSpeed').select_option('0')
            replay_begin=time.monotonic()
            page.locator('#liveFile').set_input_files(str(feed))
            page.wait_for_function("document.getElementById('viewer').contentWindow.__V10_DEBUG__?.sequence==="+str(packets[-1]['sequence']),timeout=90000)
            page.wait_for_function('replayActive===false')
            replay_s=time.monotonic()-replay_begin
            completed=page.locator('#liveReplayStatus').inner_text()
            assert str(len(packets)) in completed
            page.wait_for_timeout(2300)
            assert page.locator('#liveReplayStatus').inner_text()==completed,'poll overwrote EOF status'
            page.screenshot(path=str(out/'completed.png'),full_page=True)
            stream=page.evaluate('onlineStream')
            target=frame.locator('body').evaluate('(e,ms)=>localSeekValue(ms)',packets[10]['timestamp_ms'])
            frame.locator('#seekTime').fill(target.removesuffix('.000'));frame.locator('#seekGo').click()
            page.wait_for_function("document.getElementById('viewer').contentWindow.__V10_DEBUG__?.historical===true")
            assert frame.locator('body').evaluate('()=>window.__V10_DEBUG__.sequence')==packets[10]['sequence']
            frame.locator('#liveResume').click()
            page.wait_for_function("document.getElementById('viewer').contentWindow.__V10_DEBUG__?.sequence==="+str(packets[-1]['sequence']))
            page.reload()
            page.wait_for_function("document.getElementById('viewer').contentWindow.__V10_DEBUG__?.sequence==="+str(packets[-1]['sequence']),timeout=45000)
            assert page.evaluate('onlineStream')==stream
            # Real-time cadence with the actual first11 packets, no invented detections.
            page.locator('#liveSpeed').select_option('1')
            cadence_begin=time.monotonic()
            page.locator('#liveFile').set_input_files(dict(name='real_prefix.jsonl',mimeType='application/x-ndjson',
                buffer=('\n'.join(json.dumps(p) for p in packets[:11])+'\n').encode()))
            page.wait_for_function("document.getElementById('viewer').contentWindow.__V10_DEBUG__?.sequence===10 && replayActive===false",timeout=30000)
            cadence_s=time.monotonic()-cadence_begin
            assert 9<=cadence_s<16,dict(cadence_s=cadence_s)
            page.set_viewport_size(dict(width=390,height=844))
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(out/'mobile.png'),full_page=True)
            assert not errors,errors
            save(out/'receipt.json',dict(status='PASS',base_url=base,real_packets=len(packets),
                no_delay_replay_s=replay_s,x1_ten_second_prefix_s=cadence_s,completion_survives_polling=True,
                history_seek=True,live_resume=True,reload=True,mobile_no_overflow=True,javascript_errors=errors,
                requests=requests,runtime_s=time.monotonic()-begin))
            print('Running HTTP server replay PASS',round(replay_s,2),'s; x1 prefix',round(cadence_s,2),'s',flush=True)
        except Exception as error:
            page.screenshot(path=str(out/'failed.png'),full_page=True)
            save(out/'failed_receipt.json',dict(status='FAIL',error=str(error),javascript_errors=errors,requests=requests))
            raise
        finally:
            browser.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8017')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--project',default='1eada5fee84648b389dd6bfded3ad153')
    args=parser.parse_args();main(args.base_url.rstrip('/'),args.out,args.project)
