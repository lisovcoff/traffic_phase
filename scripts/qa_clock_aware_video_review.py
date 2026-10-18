"""Read the actual MP4 in isolated Edge and exercise clock-aware review."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/cardinal_clock_link_20261018'
VIDEO=Path('C:/Users/sheld/Downloads/len_sverdl 2025-02-27T10_00_00_2025-02-27T12_00_00.mp4')


def main():
    target=OUT/'browser';target.mkdir(exist_ok=False)
    errors=[];network=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1500})
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:network.append(r.url))
        page.goto((OUT/'visible_head_comparison.html').as_uri())
        assert page.evaluate('window.__VIDEO_REVIEW__.stateAt(2719.4,false)')=='RED'
        assert page.evaluate('window.__VIDEO_REVIEW__.stateAt(2719.4,true)')=='GREEN'
        assert page.evaluate('window.__VIDEO_REVIEW__.stateAt(2770.2,false)')=='GREEN'
        assert page.evaluate('window.__VIDEO_REVIEW__.stateAt(2770.2,true)')=='RED'
        assert abs(page.evaluate('window.__VIDEO_REVIEW__.DATA.clock_delta_s')-1.253838016213823)<1e-10
        page.locator('#file').set_input_files(str(VIDEO))
        page.wait_for_function('document.getElementById("video").readyState>=2',timeout=30000)
        page.evaluate('window.__VIDEO_REVIEW__.seek(2719.4)')
        page.wait_for_function('!document.getElementById("video").seeking && Math.abs(document.getElementById("video").currentTime-2719.4)<.1',timeout=30000)
        page.wait_for_function('document.getElementById("before").textContent==="RED" && document.getElementById("after").textContent==="GREEN"')
        page.screenshot(path=str(target/'actual_video.png'),full_page=False)
        page.locator('#forward').click()
        page.wait_for_function('!document.getElementById("video").seeking && Math.abs(document.getElementById("video").currentTime-2719.5)<.1')
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(target/'mobile.png'),full_page=False)
        page.goto((OUT/'report.html').as_uri())
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert page.locator('table').count()==1
        page.screenshot(path=str(target/'report_mobile.png'),full_page=False)
        assert not errors,errors
        assert not [r for r in network if r.startswith(('http:','https:'))]
        browser.close()
    with (target/'results.json').open('x',encoding='utf8',newline='\n') as f:
        json.dump(dict(status='PASS',actual_mp4_loaded=True,old_vs_corrected_green_and_red=True,
            positive_json_clock_offset_checked=True,seek=True,mobile_overflow=False,
            javascript_errors=errors,http_requests=0,video_uploaded=False),f,indent=2)
    print('PASS: actual video, corrected clock and colors, seek, mobile/report, no HTTP requests')


if __name__=='__main__':main()
