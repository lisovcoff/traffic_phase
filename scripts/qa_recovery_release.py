"""Isolated Edge QA: real upload products, lamps, transitions and report controls."""
import argparse
import hashlib
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main(root, output='browser', only_report=False):
    root=Path(root).resolve();out=root/output;out.mkdir(exist_ok=False)
    rows=[]
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(channel='msedge',headless=True)
        files=[('report',root/'report_v2.html')]+([
            (site,root/'application_checks'/site/'viewer.html')
            for site in ('lenina_sverdlovsky','lenina_entuziastov','chicherina_40let')] if not only_report else [])
        for name,file in files:
            context=browser.new_context(viewport=dict(width=1440,height=1000))
            page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(file.as_uri(),wait_until='load');checks={}
            if name=='report':
                assert page.locator('#case option').count()==96
                assert page.locator('#sources tbody tr').count()==219
                page.locator('#case').select_option('k2_four_hours')
                page.locator('#time').evaluate("e=>{e.value=1200;e.dispatchEvent(new Event('input'))}")
                assert page.locator('#position').inner_text()=='1200–1500с'
                page.locator('#case').select_option('holdout_k5_nonzero_stops_1')
                assert 'K=5' in page.locator('#caseInfo').inner_text()
                page.locator('#filter').fill('17_2025_2_27_10.json')
                assert page.locator('#sources tbody tr').count()==1
                page.locator('#filter').fill('')
                page.locator('#timeline').screenshot(path=str(out/'report_timeline.png'))
                page.evaluate('window.scrollTo(0,0)')
                checks=dict(cases=96,sources=219,filter=True,timeline_seek=True)
            else:
                page.wait_for_function('window.__V10_DEBUG__ !== undefined')
                assert page.locator('#error').inner_text()==''
                assert page.locator('#displayMode').input_value()=='signals'
                assert page.evaluate('RESULT.recovery_model.version')=='trajectory_recovery_v1'
                assert page.evaluate('RESULT.recovery_model.reference_video_bias_applied') is False
                snapshots=page.evaluate('''() => ESTIMATED_SIGNALS.segments.slice(0,40).map(r=>{
                    setCurrentTime((r[0]+r[1])/2+HISTORY_OFFSET_S);
                    return structuredClone(window.__V10_DEBUG__);
                })''')
                colors={h['main'] for s in snapshots for h in s['heads'].values()}
                assert {'GREEN','YELLOW','RED'}<=colors,colors
                if name=='lenina_sverdlovsky':
                    for snapshot in snapshots:
                        heads=snapshot['heads']
                        assert heads['W']['arrows']==heads['S']['arrows']==[]
                        assert len(heads['N']['arrows'])==len(heads['E']['arrows'])==1
                for snapshot in snapshots:
                    assert snapshot['observed_physical_state']=='UNKNOWN'
                index=page.locator('#phaseTimeline button').evaluate_all('''buttons=>{
                    let best=0;for(let i=1;i<buttons.length;i++)
                        if(buttons[i].getBoundingClientRect().width>buttons[best].getBoundingClientRect().width)best=i;
                    return best;
                }''')
                page.locator('#phaseTimeline button').nth(index).click()
                page.locator('#slider').evaluate("e=>{e.value=120;e.dispatchEvent(new Event('input'))}")
                before=page.evaluate('window.__V10_DEBUG__.current_time_s')
                page.locator('#play').click()
                page.wait_for_function('window.__V10_DEBUG__.current_time_s>'+str(before+.2))
                page.locator('#pause').click()
                # Seek to an actual green estimate for the review screenshot.
                page.evaluate('''() => {let r=ESTIMATED_SIGNALS.segments.find(r=>{
                    let s=ESTIMATED_SIGNALS.states.find(s=>s.id===r[2]);
                    return s&&Object.values(s.heads).some(h=>h.main.state==='GREEN')&&(r[1]-r[0])>5;
                });if(r)setCurrentTime((r[0]+r[1])/2+HISTORY_OFFSET_S);}''')
                checks=dict(playback=True,timeline_click=True,slider_seek=True,
                    model_colors=sorted(colors),snapshots=snapshots,reference_video_bias=False)
            page.screenshot(path=str(out/(name+'_desktop.png')),full_page=True)
            page.set_viewport_size(dict(width=390,height=844))
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(out/(name+'_mobile.png')),full_page=True)
            assert not errors,errors
            rows.append(dict(name=name,status='PASS',file_sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
                mobile_no_overflow=True,javascript_errors=errors,checks=checks))
            context.close()
        browser.close()
    with (out/'receipt.json').open('x',encoding='utf8',newline='\n') as stream:
        json.dump(dict(browser='isolated headless msedge; no user profile',rows=rows),stream,ensure_ascii=False,indent=2)
    print(json.dumps({r['name']:r['status'] for r in rows}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--output',default='browser')
    parser.add_argument('--only-report',action='store_true')
    args=parser.parse_args();main(args.evidence,args.output,args.only_report)
