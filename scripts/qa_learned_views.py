"""Optional isolated Edge QA of the two actual archive outputs."""
import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT.parent/'deliverables/traffic_phase_learned_20261018'
OUT=ROOT/'evidence/learned_release_20261018/browser'


def main():
    OUT.mkdir(parents=True,exist_ok=False)
    rows=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        for site in ('lenina_sverdlovsky','lenina_entuziastov'):
            context=browser.new_context(viewport={'width':1400,'height':1050})
            page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            file=SOURCE/(site+'.html')
            page.goto(file.as_uri(),wait_until='load')
            page.wait_for_function('window.__V10_DEBUG__ !== undefined')
            assert page.locator('#error').inner_text()==''
            assert 'Обученная модель' in page.locator('body').inner_text()
            assert page.locator('#anomaly').inner_text()=='Не оценено'
            snapshots=page.evaluate('''() => {
                const points=SIGNAL_MODEL.segments.slice(0,12).map(r=>(r[0]+r[1])/2+HISTORY_OFFSET_S);
                return points.map(t=>{setCurrentTime(t);return structuredClone(window.__V10_DEBUG__);});
            }''')
            if site=='lenina_sverdlovsky':
                assert page.locator('#displayMode').input_value()=='signals'
                assert {s['phase'] for s in snapshots}=={'EW','NS','N_E_ARROW'}
                for s in snapshots:
                    assert s['heads']['W']['arrows']==s['heads']['S']['arrows']==[]
                    assert len(s['heads']['N']['arrows'])==len(s['heads']['E']['arrows'])==1
                    assert s['observed_physical_state']=='UNKNOWN'
                page.evaluate('''() => {const r=ESTIMATED_SIGNALS.segments.find(r=>ESTIMATED_SIGNALS.states[r[2]].name==='N_E_ARROW');setCurrentTime((r[0]+r[1])/2+HISTORY_OFFSET_S);}''')
            else:
                assert page.locator('#displayMode').input_value()=='model'
                assert len({s['phase'] for s in snapshots})==2
            page.screenshot(path=str(OUT/(site+'_desktop.png')),full_page=True)
            page.locator('#phaseTimeline button').nth(1).click()
            before=page.evaluate('window.__V10_DEBUG__.current_time_s')
            page.locator('#play').click()
            page.wait_for_function('window.__V10_DEBUG__.current_time_s > '+str(before+.2))
            page.locator('#pause').click()
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1')
            page.screenshot(path=str(OUT/(site+'_mobile.png')),full_page=True)
            assert errors==[],errors
            rows.append(dict(site=site,status='PASS',file_sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
                snapshots=snapshots,playback=True,seek=True,mobile_no_overflow=True,errors=errors))
            context.close()
        browser.close()
    with (OUT/'results.json').open('x',encoding='utf8',newline='\n') as stream:
        json.dump(rows,stream,ensure_ascii=False,indent=2)
    print(json.dumps({row['site']:row['status'] for row in rows}))


if __name__=='__main__':main()
