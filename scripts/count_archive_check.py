"""Two predefined raw archive integrations; hard worker budget, no label scoring."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from scripts.isolated_phase_check import ROOT,sha,save

OUT=ROOT/'evidence/count_archive_integration_20261018_v2'
ARCHIVES=['Ленина-Свердловский 27.02.25.zip','Ленина-Энтузиастов 05.10.24.zip']


def main():
    OUT.mkdir(exist_ok=False)
    save(OUT/'freeze.json',dict(archives=ARCHIVES,scope='lexicographically first member; first session',
        worker_timeout_s=120,maximum_workers=2,aligned=True,annotations_used=False,
        core_sha256=sha(ROOT/'app/core/count_phase.py'),alignment_sha256=sha(ROOT/'app/core/count_alignment.py')))
    rows=[]
    for index,name in enumerate(ARCHIVES):
        source=ROOT.parent/'data'/name
        print('Raw count archive',name,flush=True);started=time.monotonic()
        try:
            proc=subprocess.run([sys.executable,'-m','scripts.run_count_phase',str(source),
                '--output',str(OUT/f'archive_{index+1}'),'--aligned','--first-scope'],cwd=ROOT,
                timeout=120,capture_output=True,text=True,encoding='utf8',
                env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONHASHSEED':'0','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
            reason=None if proc.returncode==0 else proc.stderr[-2500:]
            output=(proc.stdout or '')[-5000:]
        except subprocess.TimeoutExpired:reason='TIMEOUT_120S';output=''
        rows.append(dict(archive=name,archive_sha256=sha(source),reason=reason,
            runtime_s=time.monotonic()-started,worker_output=output))
    save(OUT/'results.json',rows)
    print(json.dumps(rows,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
