"""Verify the new standalone comparison in a disposable browser profile."""
import site
from pathlib import Path
from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
site.addsitedir(str(ROOT/'.web_runtime/model_phase_view_20261018/qa_venv/Lib/site-packages'))
from playwright.sync_api import sync_playwright


def main():
    out=ROOT/'.web_runtime/local_observation_age_20261020/browser';out.mkdir(exist_ok=False)
    checks={};errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True);page=browser.new_page(viewport=dict(width=1280,height=1000))
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto((ROOT/'evidence/local_observation_age_20261020/comparison.html').as_uri());page.wait_for_selector('#metrics tr')
        assert page.locator('#synthetic tr').count()==12
        assert '155/165' in page.locator('#metrics').inner_text() and '12/12' in page.locator('#metrics').inner_text()
        assert '93.93%' in page.locator('#aggregate').inner_text()
        assert 'Обученные события' in page.locator('#aggregate').inner_text();checks['correct_variant_labels_and_counts']=True
        point=page.evaluate("""()=>{const c=data.cases.extended,a=new Map(c.series.v7);return c.series.joint.find(([t,h])=>h.N==='GREEN'&&a.get(t)?.N==='RED'&&c.truth.some(([x,y,color])=>x<t&&t<y&&color==='GREEN'))[0]}""")
        second=page.evaluate('(t)=>(t-active.start)/1000',point)
        page.locator('#second').fill(str(second));page.locator('#second').dispatch_event('change')
        assert page.locator('#seek').input_value()==str(second);checks['seek_to_measured_green_extension']=True
        page.screenshot(path=str(out/'desktop.png'),full_page=True)
        page.locator('#case').select_option('baseline');assert '145/153' in page.locator('#metrics').inner_text()
        page.locator('#second').fill('10');page.locator('#second').dispatch_event('change')
        page.locator('#play').click();page.wait_for_timeout(1150);page.locator('#play').click()
        assert int(page.locator('#seek').input_value())>=15;checks['original_case_play_pause_speed']=True
        links=page.locator('a[href]').evaluate_all('(links)=>links.map(a=>a.href)')
        from urllib.parse import unquote,urlparse
        for link in links:
            path=unquote(urlparse(link).path)
            if len(path)>3 and path[0]=='/' and path[2]==':':path=path[1:]
            assert Path(path).exists(),path
        checks['all_local_artifact_links']=True
        page.set_viewport_size(dict(width=390,height=844));page.screenshot(path=str(out/'mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth<=390');checks['mobile_no_body_overflow']=True
        assert not errors;browser.close()
    save(ROOT/'evidence/local_observation_age_20261020/browser_check.json',dict(status='PASS',checks=checks,page_errors=errors,
        browser='disposable headless Edge',production_application_modified=False))
    print('BROWSER PASS',checks,flush=True)


if __name__=='__main__':main()
