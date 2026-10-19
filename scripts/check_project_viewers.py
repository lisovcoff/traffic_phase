"""Open every saved session through the product API without fitting again."""
import argparse
import json
from pathlib import Path
import re
import time
from unittest.mock import patch

from scripts.corpus_validation import ROOT,save,prepare_worker_environment
prepare_worker_environment()


def main(model_file,out):
    from fastapi.testclient import TestClient
    from app.main import app
    model=json.loads(Path(model_file).read_text(encoding='utf8'))
    identifier=model['model_id'];out=Path(out);out.mkdir(parents=True,exist_ok=False)
    rows=[];begin=time.monotonic()
    with TestClient(app) as client,patch('scripts.v9_spatial_visualizer.discover_path',side_effect=AssertionError('Unexpected refit')):
        for session in model['sessions']:
            started=time.monotonic()
            response=client.get(f"/api/v1/intersections/{identifier}/sessions/{session['session_id']}/viewer")
            assert response.status_code==200,response.text[:1000]
            estimate=json.loads(re.search(r'^const ESTIMATED_SIGNALS = (.*);$',response.text,re.M).group(1))
            result=json.loads(re.search(r'^const RESULT = (.*);$',response.text,re.M).group(1))
            assert result['input_scope']['selected_session']['source_member']==session['source_member']
            assert estimate['profile_id'] is None and not estimate['hardware_confirmed']
            assert estimate['available'],estimate.get('reason')
            assert estimate['operating_phase_count']==session['phase_count']
            row=dict(source_member=session['source_member'],session_id=session['session_id'],
                estimated_signals=True,working_k=estimate['operating_phase_count'],
                known_profile=False,refit=False,bytes=len(response.content),runtime_s=time.monotonic()-started)
            rows.append(row);print(row['source_member'],row['working_k'],round(row['runtime_s'],2),flush=True)
    save(out/'receipt.json',dict(status='PASS',model_id=identifier,sessions=rows,total_runtime_s=time.monotonic()-begin))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();main(args.model,args.out)
