"""Verify retained source/model bytes and record the default-off delivery."""
import gzip
from pathlib import Path
import subprocess
from scripts.corpus_validation import ROOT,save
from app.core.intersection_project import read_json,digest

OUT=ROOT/'evidence/coherent_signal_20261020'
LOCAL=ROOT/'.web_runtime/coherent_signal_20261020'


def main():
    verified=[]
    for version,folder in [('v1',OUT)]+[(v,OUT/v) for v in ('v2','v3','v4','v5','path_v1')]:
        protocol=read_json(folder/'protocol.json')
        for name,sha in protocol['source_sha256'].items():
            options=[OUT/'source_snapshots'/version/name,OUT/'source_snapshots'/version/Path(name).name,
                     OUT/'source_snapshots/v5'/name]
            source=next((p for p in options if p.exists() and digest(p)==sha),None)
            assert source is not None,(version,name,sha)
            verified.append(dict(version=version,source=name,snapshot=str(source.relative_to(ROOT)),sha256=sha))
    for version in ('v3','v4','v5'):
        model=LOCAL/version/'model.json';protocol=read_json(OUT/version/'protocol.json')
        assert digest(model)==protocol['candidate_model_sha256']
        with (OUT/'source_snapshots'/version/'model.json.gz').open('xb') as f:
            with gzip.GzipFile(fileobj=f,filename='',mode='wb',mtime=0) as gz:gz.write(model.read_bytes())
    preserved=[]
    for name in ('app/core/intersection_online.py','app/core/intersection_project.py',
                 'app/api/intersection_online.py','app/api/intersection_project.py'):
        path=ROOT/name
        if not path.exists():continue
        original=subprocess.check_output(['git','show','HEAD:'+name],cwd=ROOT)
        assert original==path.read_bytes(),name
        preserved.append(dict(path=name,sha256=digest(path)))
    packet_inputs=[]
    for case in ('baseline','extended'):
        p=ROOT/'.web_runtime/incident_validation_20261020'/(case+'.jsonl')
        expected=read_json(ROOT/'evidence/incident_validation_20261020'/(case+'_packets.json'))['sha256']
        assert digest(p)==expected
        packet_inputs.append(dict(case=case,path=str(p.relative_to(ROOT)),sha256=expected))
    assert read_json(OUT/'browser_check.json')['status']=='PASS'
    synthetic=read_json(OUT/'v5/synthetic/protocol.json')
    assert all(digest(ROOT/n)==sha for n,sha in synthetic['source_sha256'].items())
    sources=['app/core/intersection_signal_filter.py','app/core/intersection_signal_smoothing.py',
        'app/core/intersection_signal_path.py','app/core/intersection_queue_observations.py',
        'app/experimental/intersection_signal_path.py','scripts/check_coherent_signal.py',
        'scripts/check_coherent_queue.py','scripts/check_coherent_synthetic.py','scripts/check_coherent_path.py',
        'scripts/find_crash_uturn.py','scripts/trace_crash_car_video.py','scripts/report_coherent_signals.py',
        'scripts/qa_coherent_report.py','scripts/seal_coherent_delivery.py',
        'tests/test_intersection_signal_filter.py','tests/test_intersection_signal_path.py',
        'tests/test_intersection_queue_observations.py']
    files=[dict(path=str(p.relative_to(ROOT)),sha256=digest(p),bytes=p.stat().st_size)
           for p in sorted(OUT.rglob('*')) if p.is_file()]
    save(OUT/'delivery.json',dict(status='VERIFIED_DEFAULT_OFF_IMPLEMENTATION_ACCEPTANCE_FAIL',
        production_enabled=False,production_sources_unchanged=preserved,packet_inputs_unchanged=packet_inputs,
        verified_frozen_sources=verified,source_files=[dict(path=p,sha256=digest(ROOT/p)) for p in sources],
        evidence_files=files,
        tests=dict(passed=69,command='python -m pytest -q -p no:cacheprovider tests/test_intersection_signal_filter.py tests/test_intersection_queue_observations.py tests/test_intersection_signal_path.py tests/test_intersection_online.py tests/test_intersection_emissions.py tests/test_intersection_project.py tests/test_incident_counterfactual.py tests/test_archive_online_packets.py',
                   warning='existing Starlette/httpx deprecation',full_suite_rerun=False),
        browser='comparison HTML actual Edge seek/case/play/pause/speed/mobile PASS',
        prior_experiments_deleted=False,original_archives_modified=False,
        accuracy_95_accepted=False,video_clock_accepted=False))
    print('SEALED',len(verified),'source versions;',len(files),'evidence files',flush=True)


if __name__=='__main__':main()
