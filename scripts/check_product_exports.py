"""Export three saved development predictions; no discovery, fitting or replay."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT/'evidence/product_result_20261016'
    folder.mkdir(exist_ok=True)
    manifest = dict(base_sha='e6bf625023b05e20dd8357b513d599b72e8db8f5',
                    input_kind='saved_stage2c_predictions', new_fitting=False, real_replay=False,
                    large_trajectory_archive_video_files_read=0, runs=[])
    logs = []
    paths = sorted((ROOT/'benchmarks/stage2c_20261014/predictions').glob('*_v9.json'))
    if len(paths) != 3:
        raise ValueError('EXPECTED_THREE_SAVED_PREDICTIONS')
    for path in paths:
        raw = path.read_bytes()
        pred = json.loads(raw)
        segments = pred['schedule']['raw_hsmm_segments']
        destination = folder/(path.stem+'_product.json')
        command = [sys.executable, str(ROOT/'scripts/export_product_result.py'), str(path),
                   str(destination), '--time-s', '0', '--time-s', str(segments[-1][1])]
        start = time.perf_counter()
        run = subprocess.run(command, capture_output=True, text=True, timeout=30)
        elapsed = time.perf_counter()-start
        logs.extend(['> '+subprocess.list2cmdline(command),run.stdout,run.stderr,'exit_code='+str(run.returncode)])
        (folder/'exports.log').write_text('\n'.join(logs),encoding='utf-8')
        if run.returncode:
            raise RuntimeError(run.stderr)
        encoded = destination.read_bytes()
        out = json.loads(encoded)
        for key in ('schedule','phase_model_selection','period_inference'):
            assert out['invariant_payload'][key] == pred[key], key
        assert out['queries'][-1]['logical_phase']['estimated_state'] == 'UNKNOWN'
        assert all(q['physical_section']['estimated_state']=='UNKNOWN' for q in out['queries'])
        assert path.read_bytes() == raw
        manifest['runs'].append(dict(input=path.relative_to(ROOT).as_posix(),
            input_sha256=hashlib.sha256(raw).hexdigest(),output=destination.relative_to(ROOT).as_posix(),
            output_sha256=hashlib.sha256(encoded).hexdigest(),phase_count=out['phase_count'],
            period_s=out['period_s'],observed_origin_count=out['observed_origin_count'],
            covered_seconds=out['history']['covered_seconds'],local_observation_coverage='UNKNOWN',
            schedule_selection_period_exactly_preserved=True,invariant_sha256=out['invariant_sha256'],
            export_process_wall_s=elapsed,runtime_semantics='export_only_NOT_inference_or_benchmark'))
        print(path.name, out['phase_count'], 'invariants preserved')
    (folder/'invariants.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    main()
