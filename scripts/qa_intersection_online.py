"""Real trajectory JSONL → actual panel → causal journal → live shared renderer."""
import argparse
import json
from pathlib import Path
import site
import time
from urllib.parse import urlsplit

from scripts.corpus_validation import ROOT,save,prepare_worker_environment
prepare_worker_environment()


def main(out,model_id='402997a8e8ce4e989576e5764903ba39'):
    from app.core.intersection_project import read_model
    from scripts.v9_spatial_visualizer import load_tracks
    from scripts.online_packets import packets_from_tracks
    from app.main import app
    from fastapi.testclient import TestClient
    site.addsitedir(str(ROOT/'.web_runtime/model_phase_view_20261018/qa_venv/Lib/site-packages'))
    from playwright.sync_api import sync_playwright
    out=Path(out);out.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    identifier=model_id
    model=read_model(ROOT/'logs/intersection_projects'/identifier);session=model['sessions'][0]
    tracks=load_tracks(Path(model['input_path_private']),source_member=session['source_member'])
    begin=int(session['observation_start_ms']//1000*1000)+120000
    packets=list(packets_from_tracks(tracks,start_ms=begin,end_ms=begin+60000))
    feed=out/'real_packets.jsonl'
    with feed.open('x',encoding='utf8') as f:
        for packet in packets:f.write(json.dumps(packet,separators=(',',':'))+'\n')
    save(out/'feed_manifest.json',dict(source=model['input']['sha256'],member=session['source_member'],
        start_ms=begin,end_ms=begin+60000,packets=len(packets),future_fields=False))
    errors=[];requests=[]
    with TestClient(app) as client,sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport=dict(width=1440,height=1000))
        page.on('pageerror',lambda e:errors.append(str(e)))
        def route(rr):
            r=rr.request;u=urlsplit(r.url)
            response=client.request(r.method,u.path+('?' + u.query if u.query else ''),content=r.post_data_buffer,
                headers={k:v for k,v in r.headers.items() if k.lower()=='content-type'})
            requests.append(dict(method=r.method,path=u.path,status=response.status_code))
            rr.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','application/json'))
        page.route('http://traffic.test/**',route)
        try:
            page.goto('http://traffic.test/visualization?project='+identifier)
            page.wait_for_selector('#result:visible',timeout=120000)
            page.locator('#onlineMode').click()
            page.wait_for_function("document.getElementById('viewer').contentWindow.__V10_DEBUG__?.online===true",timeout=120000)
            page.locator('#liveSpeed').select_option('0')
            page.locator('#liveFile').set_input_files(str(feed.resolve()))
            page.wait_for_function("document.getElementById('viewer').contentWindow.__V10_DEBUG__?.sequence==="+str(packets[-1]['sequence']),timeout=180000)
            stream=page.evaluate('onlineStream');base=f'/api/v1/intersections/{identifier}/online/{stream}'
            latest=client.get(base).json()['snapshot']
            assert latest['timestamp_ms']==packets[-1]['timestamp_ms']
            assert latest['phase_count']==3 and latest['model_fingerprint']==model['fingerprint']
            assert not latest['video_used'] and not latest['annotations_used']
            assert set(latest['heads'])==set(model['approaches'])
            page.screenshot(path=str(out/'desktop.png'),full_page=True)
            page.set_viewport_size(dict(width=390,height=844));page.wait_for_timeout(200)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(out/'mobile.png'),full_page=True)
            count=len(client.get(base+'/history').json()['snapshots']);assert count==len(packets)
            frame=page.frame_locator('#viewer')
            target=frame.locator('body').evaluate('(element,ms)=>localSeekValue(ms)',packets[10]['timestamp_ms'])
            if target.endswith('.000'):target=target[:-4]
            frame.locator('#seekTime').fill(target);frame.locator('#seekGo').click()
            page.wait_for_function("document.getElementById('viewer').contentWindow.__V10_DEBUG__?.historical===true")
            assert frame.locator('body').evaluate('()=>window.__V10_DEBUG__.sequence')==10
            frame.locator('#liveResume').click()
            page.wait_for_function("document.getElementById('viewer').contentWindow.__V10_DEBUG__?.sequence==="+str(packets[-1]['sequence']))
            page.reload()
            page.wait_for_function("document.getElementById('viewer').contentWindow.__V10_DEBUG__?.sequence==="+str(packets[-1]['sequence']),timeout=120000)
            assert page.evaluate('onlineStream')==stream
            assert len(client.get(base+'/history').json()['snapshots'])==count
            page.locator('#archiveMode').click()
            page.frame_locator('#viewer').locator('#phaseTimeline button').first.wait_for(timeout=120000)
            page.locator('#onlineMode').click()
            page.wait_for_function("document.getElementById('viewer').contentWindow.__V10_DEBUG__?.sequence==="+str(packets[-1]['sequence']),timeout=120000)
            assert not errors,errors
            save(out/'receipt.json',dict(status='PASS',model_id=identifier,stream_id=stream,real_packets=len(packets),
                known_profile=False,video=False,future_track_metadata=False,offline_K_frozen=3,
                reload_restores=True,history_seek=True,live_resume=True,archive_online_switch=True,mobile_no_overflow=True,
                original_history_rows=count,javascript_errors=errors,requests=requests,runtime_s=time.monotonic()-start))
            print('Real causal panel and restore PASS',stream,flush=True)
        except Exception as e:
            page.screenshot(path=str(out/'failed.png'),full_page=True)
            save(out/'failed_receipt.json',dict(status='FAIL',error=str(e),javascript_errors=errors,requests=requests))
            raise
        finally:browser.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--model',default='402997a8e8ce4e989576e5764903ba39')
    args=parser.parse_args();main(args.out,args.model)
