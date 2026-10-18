"""Apply tested source-template CSS to newly built viewers; no model replay."""
from scripts.yellow_video_review import OUT
from scripts.cardinal_clock_link import save,sha
from scripts.v9_spatial_visualizer import PAGE


def main():
    css=PAGE.split('<style>',1)[1].split('</style>',1)[0];rows=[]
    for site in ['sverdlovsky','enthusiasts']:
        path=OUT/('integration_'+site)/'viewer.html'
        with (path.parent/'viewer_pre_layout_fix.html').open('xb') as f:f.write(path.read_bytes())
        old=sha(path);s=path.read_text(encoding='utf8')
        before,rest=s.split('<style>',1);_,after=rest.split('</style>',1)
        path.write_text(before+'<style>'+css+'</style>'+after,encoding='utf8',newline='\n')
        rows.append(dict(site=site,before_sha256=old,after_sha256=sha(path),model_replayed=False,change='CSS only'))
    save(OUT/'layout_fix_receipt.json',dict(rows=rows,reason='transition state names increased min-content width on390px viewport',original_failed_html_preserved=True))


if __name__=='__main__':main()
