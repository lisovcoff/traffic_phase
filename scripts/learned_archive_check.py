"""Two frozen calibrated-model archive integrations, no prediction-time labels."""
import json
import os
import subprocess
import sys
import time
from scripts.isolated_phase_check import ROOT,sha,save

OUT=ROOT/'evidence/learned_archive_integration_20261018'
ARCHIVES=[('Ленина-Свердловский 27.02.25.zip','lenina_sverdlovsky'),
          ('Ленина-Энтузиастов 05.10.24.zip','lenina_entuziastov')]


def main():
    OUT.mkdir(exist_ok=False)
    save(OUT/'freeze.json',dict(archives=ARCHIVES,timeout_per_worker_s=120,max_workers=2,
        selection='lexicographically first member, first observation session',
        model_hashes={site:sha(ROOT/'config/learned_profiles'/(site+'.json')) for name,site in ARCHIVES},
        core_sha256=sha(ROOT/'app/core/learned_phase.py'),annotations_in_inference=False))
    rows=[]
    for index,(name,site) in enumerate(ARCHIVES,1):
        path=ROOT.parent/'data'/name
        print('Learned raw archive',site,flush=True);started=time.monotonic()
        try:
            proc=subprocess.run([sys.executable,'-m','scripts.run_learned_phase',str(path),'--model',site,
                '--output',str(OUT/f'archive_{index}'),'--first-scope'],cwd=ROOT,timeout=120,
                capture_output=True,text=True,encoding='utf8',
                env={**os.environ,'PYTHONIOENCODING':'utf-8','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
            reason=None if proc.returncode==0 else proc.stderr[-2500:]
            output=proc.stdout[-5000:]
        except subprocess.TimeoutExpired:reason='TIMEOUT_120S';output=''
        rows.append(dict(archive=name,model=site,archive_sha256=sha(path),reason=reason,
            runtime_s=time.monotonic()-started,worker_output=output))
    save(OUT/'results.json',rows)
    print(json.dumps(rows,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
