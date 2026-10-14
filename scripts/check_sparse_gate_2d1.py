"""Read-only feature readiness gate. Nonzero exit is a rejected experiment, not a CI unit test."""
import json
from pathlib import Path


def main():
    folder=Path(__file__).resolve().parents[1]/'evidence/stage2d1_sparse_review'
    report=json.loads((folder/'comparison.json').read_text())
    failed=[f"{r['case']}/seed{r['seed']}" for r in report['rows'] if not r['candidate_recovery_pass']]
    print('Sparse candidate recovery gate:',report['candidate_sparse_recovery_gate'])
    print('Failed predeclared cases:',', '.join(failed))
    print('Publishing/identifiability gate:',report['publication_identifiability_gate'])
    print('Real replay count:',report['real_replays'])
    return 0 if report['overall_gate']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
