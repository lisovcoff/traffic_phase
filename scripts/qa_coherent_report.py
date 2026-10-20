"""Headless verification of our standalone report, using a disposable Edge profile."""
import site
from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
site.addsitedir(str(ROOT/'.web_runtime/model_phase_view_20261018/qa_venv/Lib/site-packages'))
from playwright.sync_api import sync_playwright


def main():
    out=ROOT/'.web_runtime/coherent_signal_20261020/browser';out.mkdir(exist_ok=False)
    errors=[];checks={}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport=dict(width=1280,height=1000))
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto((ROOT/'evidence/coherent_signal_20261020/comparison.html').as_uri())
        page.wait_for_selector('#metrics tr')
        assert page.locator('#metrics').inner_text().count('12/12')==1
        assert page.locator('#synthetic tr').count()==12;checks['metrics_and_12_scenarios']=True
        difference=page.evaluate("""()=>{const c=data.cases.extended;const a=new Map(c.series.v7),b=new Map(c.series.joint);return c.truth.filter(v=>v[2]==='GREEN').flatMap(([start,end])=>c.series.joint.filter(([t,h])=>start<t&&t<end&&h.N==='GREEN'&&a.get(t).N==='RED').map(([t,h])=>t))[0]}""")
        assert difference is not None
        second=page.evaluate('(t)=>(t-active.start)/1000',difference)
        page.locator('#second').fill(str(second));page.locator('#second').dispatch_event('change')
        assert page.locator('#seek').input_value()==str(second)
        colors=page.locator('#heads .headrow').all_text_contents();assert 'К' in colors[0] and 'З' in colors[1]
        checks['seek_actual_premature_red_vs_extended_green']=True
        page.screenshot(path=str(out/'desktop.png'),full_page=True)
        page.locator('#case').select_option('baseline');assert '144/153' in page.locator('#metrics').inner_text()
        checks['original_case_switch']=True
        page.locator('#second').fill('20');page.locator('#second').dispatch_event('change')
        page.locator('#play').click();page.wait_for_timeout(1150);page.locator('#play').click()
        assert int(page.locator('#seek').input_value())>=25;checks['play_pause_speed']=True
        page.set_viewport_size(dict(width=390,height=844));page.screenshot(path=str(out/'mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth<=390');checks['mobile_no_body_overflow']=True
        assert not errors;browser.close()
    save(ROOT/'evidence/coherent_signal_20261020/browser_check.json',dict(status='PASS',checks=checks,
         page_errors=errors,report='comparison.html',browser='disposable headless Microsoft Edge',production_server_modified=False))
    print('BROWSER PASS',checks,flush=True)


if __name__=='__main__':main()
