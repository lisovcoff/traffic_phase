"""Check metadata upload feedback through the real UI and isolated worker."""
import argparse
import site
from urllib.parse import urlsplit

from scripts.corpus_validation import ROOT, prepare_worker_environment, save
prepare_worker_environment()


def main(out):
    from app.main import app
    from fastapi.testclient import TestClient
    site.addsitedir(str(ROOT/'.web_runtime/model_phase_view_20261018/qa_venv/Lib/site-packages'))
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True,exist_ok=False)
    manifest=ROOT/'evidence/intersection_online_20261019/browser_v7/feed_manifest.json'
    errors=[]
    with TestClient(app) as client,sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport=dict(width=1200,height=850))
        page.on('pageerror',lambda e:errors.append(str(e)))
        def route(rr):
            r=rr.request;u=urlsplit(r.url)
            response=client.request(r.method,u.path+('?' + u.query if u.query else ''),content=r.post_data_buffer,
                headers={k:v for k,v in r.headers.items() if k.lower()=='content-type'})
            rr.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','application/json'))
        page.route('http://traffic.test/**',route)
        try:
            page.goto('http://traffic.test/visualization')
            # In-memory attachment keeps file bytes available to ASGI routing.
            page.locator('#file').set_input_files(dict(name=manifest.name,mimeType='application/json',buffer=manifest.read_bytes()))
            page.locator('#analyze').click()
            condition="document.getElementById('error').textContent.includes('real_packets.jsonl')"
            page.wait_for_function(condition,timeout=45000)
            identifier=page.evaluate('identifier')
            status=client.get('/api/v1/intersections/'+identifier).json()
            assert status['reason_code']=='NON_TRAJECTORY_INPUT',status
            assert status['sources'][0]['uncompressed_bytes']==manifest.stat().st_size
            message=page.locator('#error').inner_text()
            assert manifest.name in message and 'ValueError' not in message
            assert page.locator('#analyze').is_enabled() and page.locator('#file').is_enabled()
            assert page.locator('#result').is_hidden()
            page.screenshot(path=str(out/'desktop.png'),full_page=True)
            page.reload();page.wait_for_function(condition)
            page.set_viewport_size(dict(width=390,height=844))
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(out/'mobile.png'),full_page=True)
            assert not errors,errors
            save(out/'receipt.json',dict(status='PASS',worker_status=status,visible_message=message,
                reload=True,mobile_no_overflow=True,retry_enabled=True,javascript_errors=errors))
        except Exception as error:
            page.screenshot(path=str(out/'failed.png'),full_page=True)
            save(out/'failed_receipt.json',dict(status='FAIL',error=str(error),javascript_errors=errors))
            raise
        finally:
            browser.close()
    print('Manifest upload, real worker, friendly error, reload, mobile: PASS',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=lambda p:ROOT/p,required=True)
    main(parser.parse_args().out)
