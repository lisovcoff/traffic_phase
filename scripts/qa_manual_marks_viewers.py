"""Optional isolated Edge QA for saved manual-marks viewers (requires Playwright)."""
import json
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
INPUT=ROOT/'.web_runtime/manual_marks_20261018/viewers'
OUT=ROOT/'evidence/manual_marks_20261018/browser_verified'


def main():
    global INPUT,OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=INPUT)
    parser.add_argument('--output',type=Path,default=OUT)
    args=parser.parse_args()
    INPUT,OUT=args.input.resolve(),args.output.resolve()
    OUT.mkdir(parents=True,exist_ok=False)
    results={}
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(channel='msedge',headless=True)
        for name in ('real','manual17','synthetic'):
            context=browser.new_context(viewport={'width':1400,'height':1050})
            page=context.new_page()
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto((INPUT/(name+'_viewer.html')).as_uri(),wait_until='load')
            page.wait_for_function('window.__V10_DEBUG__ !== undefined')
            assert page.locator('#error').inner_text()==''
            snapshots=[]
            if name!='synthetic':
                assert page.locator('#displayMode').input_value()=='signals'
                snapshots=page.evaluate('''() => ESTIMATED_SIGNALS.states.map(state=>{
                    const row=ESTIMATED_SIGNALS.segments.find(row=>row[2]===state.id);
                    setCurrentTime((row[0]+row[1])/2+HISTORY_OFFSET_S);
                    return structuredClone(window.__V10_DEBUG__);
                })''')
                assert {s['phase'] for s in snapshots}=={'EW','NS','N_E_ARROW'}
                for snapshot in snapshots:
                    assert snapshot['hardware_confirmed']
                    assert snapshot['observed_physical_state']=='UNKNOWN'
                    heads=snapshot['heads']
                    assert set(heads)=={'N','S','E','W'}
                    assert len(heads['N']['arrows'])==len(heads['E']['arrows'])==1
                    assert heads['W']['arrows']==heads['S']['arrows']==[]
                    green={'EW':{'E','W'},'NS':{'N','S'},'N_E_ARROW':{'N'}}[snapshot['phase']]
                    assert {a for a,h in heads.items() if h['main']=='GREEN'}==green
                    arrows=[arrow.split('=',1)[1] for a in ('N','E') for arrow in heads[a]['arrows']]
                    assert arrows==(['GREEN','GREEN'] if snapshot['phase']=='N_E_ARROW' else ['OFF','OFF'])
                page.evaluate('''() => {const row=ESTIMATED_SIGNALS.segments.find(row=>ESTIMATED_SIGNALS.states[row[2]].name==='N_E_ARROW');setCurrentTime((row[0]+row[1])/2+HISTORY_OFFSET_S);}''')
                page.screenshot(path=str(OUT/(name+'_arrows.png')),full_page=True)
                page.select_option('#displayMode','physical')
                assert all(h['main']=='UNKNOWN' for h in page.evaluate('window.__V10_DEBUG__.heads').values())
                assert len(page.evaluate('window.__V10_DEBUG__.heads.N.arrows'))==1
                page.select_option('#displayMode','signals')
            else:
                assert page.locator('#displayMode').input_value()=='model'
                assert page.locator('#modelLegend').is_visible()
                assert 'UNKNOWN' not in page.locator('#signalList').inner_text()
            page.locator('#phaseTimeline button').nth(1).click()
            before=page.evaluate('window.__V10_DEBUG__.current_time_s')
            page.locator('#play').click()
            page.wait_for_function('window.__V10_DEBUG__.current_time_s > '+str(before+.2))
            page.locator('#pause').click()
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1')
            page.screenshot(path=str(OUT/(name+'_mobile.png')),full_page=True)
            assert errors==[],errors
            results[name]=dict(status='PASS',snapshots=snapshots,playback=True,seek=True,mobile_no_overflow=True,errors=errors)
            context.close()
        browser.close()
    with (OUT/'results.json').open('x',encoding='utf-8') as stream:
        json.dump(results,stream,ensure_ascii=False,indent=2)
    print(json.dumps({k:v['status'] for k,v in results.items()}))


if __name__=='__main__':
    main()
