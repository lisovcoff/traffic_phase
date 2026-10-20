"""Verify all timing experiment receipts and preserve reproducible model bytes."""
import gzip
from pathlib import Path
import subprocess
from scripts.corpus_validation import ROOT,save
from app.core.intersection_project import read_json,digest

OUT=ROOT/'evidence/local_observation_age_20261020'
LOCAL=ROOT/'.web_runtime/local_observation_age_20261020'


def main():
    protocols=[];source_names=set()
    for path in sorted(OUT.rglob('protocol.json')):
        p=read_json(path)
        for name,sha in p.get('source_sha256',{}).items():
            assert digest(ROOT/name)==sha,(str(path),name)
            source_names.add(name)
        protocols.append(dict(path=path.relative_to(ROOT).as_posix(),sha256=digest(path)))
    for k in range(2,6):
        assert (OUT/f'v1/fresh/k{k}_result.json').exists()
        for directory in ('v1/synthetic','v1/duration_v1/synthetic','v1/conditioned_v1/synthetic','sensor_delay/synthetic'):
            for case in ('normal','blocked_N','extended_12s'):assert (OUT/directory/f'k{k}_{case}.json').exists()
    assert digest(ROOT/'scripts/realistic_traffic_benchmark.py')==read_json(ROOT/'evidence/coherent_signal_20261020/v5/synthetic/protocol.json')['source_sha256']['scripts/realistic_traffic_benchmark.py']
    training=[]
    for i in range(8):
        t=read_json(OUT/f'v1/training_ram/train_{i}.json');manifest=t['packet_manifest']
        assert digest(Path(manifest['output']))==manifest['sha256']
        training.append(dict(source_member=t['source_member'],raw_sha256=t['raw_sha256'],
            packet_sha256=manifest['sha256'],packets=t['stats']['packets'],last_ms=t['stats']['last_ms']))
    target=read_json(ROOT/'evidence/incident_validation_20261020/baseline_packets.json')
    assert max(t['last_ms'] for t in training)<target['first_ms']
    models=OUT/'model_snapshots';models.mkdir(exist_ok=False)
    candidates=[LOCAL/'v1/model.json']+[LOCAL/f'v1/synthetic/k{k}_model.json' for k in range(2,6)]
    candidates+=[LOCAL/f'v1/duration_v1/synthetic/k{k}_model.json' for k in range(2,6)]
    model_rows=[]
    for i,path in enumerate(candidates):
        destination=models/f'model_{i}.json.gz'
        with destination.open('xb') as dst:
            with gzip.GzipFile(fileobj=dst,mode='wb',filename='',mtime=0) as gz:gz.write(path.read_bytes())
        model_rows.append(dict(runtime=path.relative_to(ROOT).as_posix(),snapshot=destination.relative_to(ROOT).as_posix(),
                               decompressed_sha256=digest(path)))
    unchanged=[]
    for name in ('app/core/intersection_online.py','app/core/intersection_project.py','app/core/intersection_signal_filter.py',
                 'app/core/intersection_queue_observations.py','app/core/intersection_signal_smoothing.py','app/api/intersection_online.py'):
        assert subprocess.check_output(['git','show','HEAD:'+name],cwd=ROOT)==(ROOT/name).read_bytes(),name
        unchanged.append(dict(path=name,sha256=digest(ROOT/name)))
    assert read_json(OUT/'browser_check.json')['status']=='PASS'
    extras=['scripts/train_local_age_fast.py','scripts/report_local_observation_age.py','scripts/qa_local_observation_age.py',
            'scripts/seal_local_age_delivery.py','scripts/realistic_traffic_benchmark.py',
            'tests/test_intersection_local_emissions.py','tests/test_intersection_conditioned_local.py',
            'tests/test_intersection_duration_learning.py','tests/test_intersection_sensor_delay.py','tests/test_local_age_spool.py']
    source_names.update(extras)
    evidence=[dict(path=p.relative_to(ROOT).as_posix(),sha256=digest(p),bytes=p.stat().st_size)
              for p in sorted(OUT.rglob('*')) if p.is_file()]
    save(OUT/'delivery.json',dict(status='VERIFIED_EXPERIMENTS_ACCEPTANCE_FAIL_DEFAULT_OFF',
        production='v7 unchanged',production_or_previous_core_unchanged=unchanged,
        verified_protocols=protocols,verified_training_inputs=training,models=model_rows,
        source_files=[dict(path=n,sha256=digest(ROOT/n)) for n in sorted(source_names)],evidence_files=evidence,
        verification=dict(affected_tests_passed=85,full_suite_rerun=False,syntax_checked=True,
            browser='actual standalone Edge comparison: seek/play/case/speed/mobile/link labels PASS'),
        distinct_synthetic_streams=16,distinct_simulated_hours=8,known_streams_repeated_across_variants=True,
        real_validation='previously revealed N GREEN/YELLOW; conditional clock, no all-head accuracy claim',
        failed_variants_preserved=True,abandoned_disk_spool_files_preserved=True,
        original_archives_modified=False,physical_reaction_delay_calibrated=False,
        accuracy_95_accepted=False,video_supplied_to_inference_or_training=False))
    print('SEALED',len(protocols),'protocols',len(source_names),'source files',len(evidence),'evidence files',flush=True)


if __name__=='__main__':main()
