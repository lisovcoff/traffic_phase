"""Retain byte hashes of source, compact evidence and local bulky inputs."""
from pathlib import Path
from scripts.corpus_validation import ROOT,save
from app.core.intersection_project import digest,read_json
from scripts.check_incident_counterfactual import OUT,RUNTIME,MODEL,CODE


def entry(path):
    return dict(path=path.relative_to(ROOT).as_posix(),bytes=path.stat().st_size,sha256=digest(path))


def main():
    protocol=read_json(OUT/'protocol.json')
    assert all(digest(ROOT/p)==sha for p,sha in protocol['code_sha256'].items())
    sources=list(CODE)+[
        'scripts/realistic_traffic_benchmark.py','scripts/check_incident_counterfactual.py',
        'scripts/check_incident_synthetic.py','scripts/diagnose_incident_forecast.py',
        'scripts/review_incident_video.py','scripts/report_incident_validation.py',
        'scripts/qa_incident_validation.py','scripts/find_enthusiasts_bus.py',
        'scripts/seal_incident_delivery.py','tests/test_incident_counterfactual.py',
        'docs/INCIDENT_VALIDATION_RESULTS_20261020.md']
    files=[entry(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='delivery_manifest.json']
    local=[entry(p) for p in sorted(RUNTIME.rglob('*')) if p.is_file() and not p.name.startswith('server.')]
    folder=ROOT/'logs/intersection_projects'/MODEL
    model=[entry(p) for p in sorted(folder.rglob('*')) if p.is_file() and 'online' not in p.relative_to(folder).parts]
    save(OUT/'delivery_manifest.json',dict(
        schema='incident-validation-delivery-v1',baseline_commit=protocol['baseline_commit'],
        production_code_unchanged=True,production_version='causal-intersection-v7',
        sources=[entry(ROOT/p) for p in sources],evidence_files=files,local_reproduction_files=local,
        offline_model_files=model,offline_model_id=MODEL,
        original_video_sha256='c574f9204abab0b2bd4dd88425e581da8d335c8e6be0cf4425c0ac7143bfa987',
        original_video_hash_scope='previous full-source hash, not a new read of 6.79GB',
        accuracy_acceptance='FAIL_95_PERCENT_NOT_ESTABLISHED',
        tests=dict(targeted_pass=29,warning='existing Starlette/httpx deprecation',
                   initial_new_test_failure='incorrect truth key; corrected and complete affected selection rerun'),
        actual_HTTP_Edge_receipt='browser/receipt.json',
        superseded=['report.html','synthetic/','*_forecast_diagnostic.json'],
        current_report='report_paired.html',current_synthetic='synthetic_paired/',
        limitations='known video windows, conditional clock, N GREEN/YELLOW only; synthetic not road truth'))
    print('SEALED',len(files),'evidence',len(local),'local',len(model),'model files',flush=True)


if __name__=='__main__':main()
