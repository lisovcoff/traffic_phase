"""Isolated Edge QA with the actual local MP4, without a server or user profile."""
import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT=Path(__file__).resolve().parents[1]/'evidence/direct_video_truth_20261018'
SOURCES={'sverdlovsky':Path('C:/Users/sheld/Downloads/len_sverdl 2025-02-27T10_00_00_2025-02-27T12_00_00.mp4')}


def save(path,value):
    with path.open('x',encoding='utf8',newline='\n') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)


def main():
    target=OUT/'browser';target.mkdir(exist_ok=False)
    errors=[];requests=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1500})
        page.on('pageerror',lambda err:errors.append(str(err)))
        page.on('request',lambda request:requests.append(request.url))
        path=OUT/'visible_head_comparison.html';page.goto(path.as_uri())
        assert page.evaluate('window.__VIDEO_REVIEW__.stateAt(2719.4,false)')=='RED'
        assert page.evaluate('window.__VIDEO_REVIEW__.stateAt(2719.4,true)')=='GREEN'
        assert page.evaluate('window.__VIDEO_REVIEW__.stateAt(2770.2,false)')=='GREEN'
        assert page.evaluate('window.__VIDEO_REVIEW__.stateAt(2770.2,true)')=='RED'
        page.locator('#file').set_input_files(str(SOURCES['sverdlovsky']))
        page.wait_for_function('document.getElementById("video").readyState>=2',timeout=30000)
        duration=page.locator('#video').evaluate('(v)=>v.duration');assert 7216<duration<7217
        page.evaluate('window.__VIDEO_REVIEW__.seek(2719.4)')
        page.wait_for_function('Math.abs(document.getElementById("video").currentTime-2719.4)<.1 && !document.getElementById("video").seeking',timeout=30000)
        page.wait_for_function('document.getElementById("before").textContent==="RED" && document.getElementById("after").textContent==="GREEN"')
        page.screenshot(path=str(target/'sverdlovsky_actual_video_comparison.png'),full_page=False)
        shown_pts=page.locator('#pts').inner_text()
        page.locator('#cal').click()
        page.wait_for_function('!document.getElementById("video").seeking && Math.abs(document.getElementById("video").currentTime-900)<.1')
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(target/'comparison_mobile.png'),full_page=False)
        page.goto((OUT/'report.html').as_uri())
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert page.locator('table').count()==2
        page.screenshot(path=str(target/'report_mobile.png'),full_page=False)
        assert not errors,errors
        assert not any(url.startswith(('http:','https:')) for url in requests)
        browser.close()
    save(target/'results.json',dict(status='PASS',actual_source_mp4_loaded=True,video_duration_s=duration,
        shown_frame_pts=shown_pts,old_red_corrected_green_at_test_time=True,old_green_corrected_red=True,
        seek_to_calibration_pass=True,mobile_overflow=False,javascript_errors=errors,
        http_network_requests=0,source_video_uploaded=False,
        comparison_html_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    print('PASS: actual local MP4, native head zoom, before/after colors, seek, mobile and report; no HTTP requests')


if __name__=='__main__':main()
