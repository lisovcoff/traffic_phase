"""Run a frozen calibrated model on JSON/ZIP; no marks accepted during inference."""
import argparse
import json
from pathlib import Path
from app.core.learned_visualization import build_learned_visualization,SITES


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path);parser.add_argument('--model',choices=SITES,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--first-scope',action='store_true')
    parser.add_argument('--source-member');parser.add_argument('--session-id')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    built=build_learned_visualization(args.input,model_id=args.model,source_member=args.source_member,
        session_id=args.session_id,first_scope=args.first_scope)
    for name,value in [('result.json',built['result']),('projection.json',built['projection'])]:
        (args.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    (args.output/'viewer.html').write_text(built['html'],encoding='utf8')
    print(json.dumps(dict(status='PASS',model=args.model,tracks=built['rendered_trajectory_count'],
        scope=built['result']['input_scope'],count=built['result']['schedule']['phase_count'],
        inference_marks_received=False,html=str(args.output/'viewer.html')),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
