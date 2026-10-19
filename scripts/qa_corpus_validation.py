"""Isolated Edge checks of the delivered corpus report and real-ZIP viewer."""
import argparse
import hashlib
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--output',default='browser',help='new evidence subdirectory; previous attempts remain intact')
    args=parser.parse_args();root=args.evidence.resolve()
    out=root/args.output;out.mkdir(exist_ok=False)
    rows=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        for name,file in [('report',root/'report.html'),
            ('actual_sverdlovsky_viewer',root/'application_checks/sverdlovsky/viewer.html')]:
            context=browser.new_context(viewport=dict(width=1440,height=1000))
            page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(file.as_uri(),wait_until='load')
            checks={}
            if name=='report':
                assert page.locator('#case option').count()==72
                assert page.locator('#sources tbody tr').count()==219
                page.locator('#case').select_option('k2_four_hours')
                page.locator('#time').evaluate("s=>{s.value=1200;s.dispatchEvent(new Event('input'))}")
                assert '1200–1800' in page.locator('#position').inner_text()
                page.locator('#filter').fill('17_2025_2_27_10.json')
                assert page.locator('#sources tbody tr:visible').count()==1
                page.locator('#filter').fill('')
                page.locator('#case').select_option('k2_asymmetric_real_uturn')
                assert '0–600' in page.locator('#position').inner_text()
                page.locator('#timeline').screenshot(path=str(out/'report_timeline.png'))
                page.evaluate('window.scrollTo(0,0)')
                page.screenshot(path=str(out/'report_overview.png'))
                checks.update(cases=72,sources=219,filter=True,case_selector=True,timeline_seek=True)
            else:
                page.wait_for_function('window.__V10_DEBUG__ !== undefined')
                assert page.locator('#error').inner_text()==''
                assert page.locator('#displayMode').input_value()=='signals'
                snapshots=page.evaluate('''() => SIGNAL_MODEL.segments.slice(0,18).map(r=>{
                    setCurrentTime((r[0]+r[1])/2+HISTORY_OFFSET_S);
                    return structuredClone(window.__V10_DEBUG__);
                })''')
                for snapshot in snapshots:
                    heads=snapshot['heads']
                    assert heads['W']['arrows']==heads['S']['arrows']==[]
                    assert len(heads['N']['arrows'])==len(heads['E']['arrows'])==1
                    assert snapshot['observed_physical_state']=='UNKNOWN'
                result=json.loads((file.parent/'result.json').read_text(encoding='utf8'))
                assert result['learned_phase']['reference_video_timing_bias_applied'] is False
                assert result['estimated_signals']['transition_timing']['phase_boundary_calibration'] is None
                # A one-second yellow boundary is narrower than one pixel on
                # an hour-long overview. Use a visible long segment for a real
                # pointer click; precise seeking has a separate time slider.
                index=page.locator('#phaseTimeline button').evaluate_all('''buttons => {
                    let best=0;
                    for(let i=1;i<buttons.length;i++)
                        if(buttons[i].getBoundingClientRect().width>buttons[best].getBoundingClientRect().width)best=i;
                    return best;
                }''')
                page.locator('#phaseTimeline button').nth(index).click()
                before=page.evaluate('window.__V10_DEBUG__.current_time_s')
                page.locator('#play').click()
                page.wait_for_function('window.__V10_DEBUG__.current_time_s > '+str(before+.2))
                page.locator('#pause').click()
                checks.update(playback=True,seek=True,hardware_N_E_arrows_only=True,
                    reference_video_bias=False,physical_observation='UNKNOWN',snapshots=snapshots)
            page.screenshot(path=str(out/(name+'_desktop.png')),full_page=True)
            page.set_viewport_size(dict(width=390,height=844))
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(out/(name+'_mobile.png')),full_page=True)
            assert errors==[],errors
            rows.append(dict(name=name,status='PASS',file_sha256=digest(file),
                checks=checks,mobile_no_overflow=True,javascript_errors=errors))
            context.close()
        browser.close()
    with (out/'receipt.json').open('x',encoding='utf8',newline='\n') as stream:
        json.dump(dict(browser='isolated headless msedge; no user profile',rows=rows),stream,ensure_ascii=False,indent=2)
    print(json.dumps({r['name']:r['status'] for r in rows}))


if __name__=='__main__':main()
