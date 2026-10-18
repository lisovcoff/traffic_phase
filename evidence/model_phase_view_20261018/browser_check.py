import json
from pathlib import Path
from playwright.sync_api import sync_playwright

output = Path(__file__).resolve().parent
results = {}
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='msedge', headless=True)
    for name in ('synthetic', 'real'):
        context = browser.new_context(viewport={'width': 1400, 'height': 1050})
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto((output/(name+'_viewer.html')).as_uri(), wait_until='load')
        page.wait_for_function('window.__V10_DEBUG__ !== undefined')
        assert page.locator('#error').inner_text() == '', page.locator('#error').inner_text()
        assert page.locator('#displayMode').input_value() == 'model'
        assert page.locator('#modelLegend').is_visible()
        assert not page.locator('#physicalLegend').is_visible()
        snapshots = page.evaluate('''() => {
            const points=SIGNAL_MODEL.segments.slice(0,6).map(row=>(row[0]+row[1])/2+(HISTORY_OFFSET_S||0));
            return points.map(t=>{setCurrentTime(t);return window.__V10_DEBUG__;});
        }''')
        assert len({s['phase'] for s in snapshots}) >= 2
        assert all(any(item['state']=='ACTIVE' for items in s['model_movements'].values()
                       for item in items) for s in snapshots)
        assert all(all(h['main']=='UNKNOWN' for h in s['heads'].values()) for s in snapshots)
        page.evaluate('setCurrentTime('+('2992' if name=='real' else '35')+')')
        page.screenshot(path=str(output/(name+'_model.png')), full_page=True)
        page.select_option('#displayMode', 'physical')
        assert page.locator('#physicalLegend').is_visible()
        assert not page.locator('#modelLegend').is_visible()
        assert 'UNKNOWN' in page.locator('#signalList').inner_text()
        page.screenshot(path=str(output/(name+'_physical.png')), full_page=True)
        page.select_option('#displayMode', 'model')
        assert 'UNKNOWN' not in page.locator('#signalList').inner_text()
        page.locator('#phaseTimeline button').nth(1).click()
        before = page.evaluate('window.__V10_DEBUG__.current_time_s')
        page.locator('#play').click()
        page.wait_for_function('window.__V10_DEBUG__.current_time_s > '+str(before+.2))
        page.locator('#pause').click()
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth+1')
        page.screenshot(path=str(output/(name+'_mobile.png')), full_page=True)
        assert errors == [], errors
        assert page.locator('#error').inner_text() == ''
        results[name] = dict(status='PASS', phases=sorted({s['phase'] for s in snapshots}),
            colored_snapshots=len(snapshots), lamps_remain_unknown=True,
            display_switch=True, timeline_click=True, playback=True, mobile_no_overflow=True,
            browser_errors=errors)
        context.close()
    browser.close()
with (output/'browser_results.json').open('x', encoding='utf-8') as stream:
    json.dump(results, stream, indent=2)
print(json.dumps(results, indent=2))
