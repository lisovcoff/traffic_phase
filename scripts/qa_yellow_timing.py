"""Real ZIP HTML and local MP4 browser QA in isolated Edge."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence/yellow_timing_20261019'
VIDEOS={'sverdlovsky':Path('C:/Users/sheld/Downloads/len_sverdl 2025-02-27T10_00_00_2025-02-27T12_00_00.mp4'),
    'enthusiasts':Path('C:/Users/sheld/Downloads/lenina_entuziastov.mp4')}


def main():
    target=OUT/'browser_v3';target.mkdir(exist_ok=False);errors=[];network=[];results=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1200})
        page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:network.append(r.url))
        for site,head in [('sverdlovsky','N'),('enthusiasts','E')]:
            page.goto((OUT/('integration_'+site)/'viewer.html').as_uri())
            page.wait_for_function('window.__V10_DEBUG__!==undefined')
            assert page.locator('#displayMode').input_value()=='signals'
            for color in ['YELLOW','RED_YELLOW','GREEN','RED']:
                snapshot=page.evaluate('''([head,color])=>{const r=ESTIMATED_SIGNALS.segments.find(r=>ESTIMATED_SIGNALS.states[r[2]].heads[head].main.state===color);if(!r)throw new Error('missing '+color);setCurrentTime((r[0]+r[1])/2+HISTORY_OFFSET_S);return structuredClone(window.__V10_DEBUG__)}''',[head,color])
                assert snapshot['heads'][head]['main']==color
                assert snapshot['observed_physical_state']=='UNKNOWN'
                if site=='enthusiasts':assert snapshot['heads']['W']['main']==color
                if color=='YELLOW':page.screenshot(path=str(target/(site+'_yellow.png')),full_page=False)
            page.locator('#play').click();before=page.evaluate('window.__V10_DEBUG__.current_time_s')
            page.wait_for_function('window.__V10_DEBUG__.current_time_s>'+str(before+.2));page.locator('#pause').click()
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(target/(site+'_mobile.png')),full_page=False)
            overflow=page.evaluate('Array.from(document.querySelectorAll("body *")).filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>({tag:e.tagName,id:e.id,cls:e.className,text:e.innerText?.slice(0,100),right:e.getBoundingClientRect().right})).slice(-20)')
            if page.evaluate('document.documentElement.scrollWidth>innerWidth+1'):
                with (target/'overflow.json').open('x',encoding='utf8') as f:json.dump(overflow,f,ensure_ascii=False,indent=2)
                raise AssertionError(overflow)
            page.set_viewport_size({'width':1440,'height':1200})
            results.append(dict(site=site,real_zip_viewer=True,all_four_colors=True,playback=True,mobile=True))
        page.goto((OUT/'video_comparison.html').as_uri())
        for site,t in [('sverdlovsky',3468.1),('enthusiasts',3468.3)]:
            page.locator('#site').select_option(site);page.locator('#file').set_input_files(str(VIDEOS[site]))
            page.wait_for_function('document.getElementById("video").readyState>=2',timeout=30000)
            page.evaluate('window.__YELLOW_REVIEW__.seek('+str(t)+')')
            page.wait_for_function('!document.getElementById("video").seeking && Math.abs(document.getElementById("video").currentTime-'+str(t)+')<.1',timeout=30000)
            expected='YELLOW' if site=='sverdlovsky' else 'UNKNOWN'
            page.wait_for_function('document.getElementById("new").textContent==="'+expected+'"')
            if site=='sverdlovsky':assert page.locator('#old').inner_text()=='GREEN'
            page.screenshot(path=str(target/(site+'_actual_mp4.png')),full_page=False)
        page.set_viewport_size({'width':390,'height':844});page.goto((OUT/'report.html').as_uri())
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(target/'report_mobile.png'),full_page=False)
        assert not errors,errors
        assert not [r for r in network if r.startswith(('http:','https:'))]
        browser.close()
    with (target/'results.json').open('x',encoding='utf8',newline='\n') as f:
        json.dump(dict(status='PASS',real_archives=results,both_actual_MP4s_loaded=True,
            sverd_visible_yellow_and_model_yellow=True,enth_unaccepted_clock_keeps_comparison_unknown=True,
            javascript_errors=errors,http_requests=0,source_videos_uploaded=False),f,indent=2)
    print('PASS: both real ZIP viewers/four colors/playback/mobile and both local MP4s; no HTTP requests')


if __name__=='__main__':main()
