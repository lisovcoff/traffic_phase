"""Read only saved event queries; no trajectories, annotations or inference."""
import hashlib
import json
from pathlib import Path

from app.experimental.phase_observation_bridge import prepare_joint_observation

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/phase_observation_bridge_20261015'
SOURCE=ROOT/'evidence/restart_multicycle_validation_20261015/evidence_adapter_queries.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    target=OUT/'readiness.json'
    if target.exists():
        raise SystemExit('Saved output already exists; no repeat/overwrite')
    before=sha(SOURCE)
    queries=json.loads(SOURCE.read_text(encoding='utf-8'))['queries']
    results={name:prepare_joint_observation(view) for name,view in queries.items()}
    assert sha(SOURCE)==before
    for r in results.values():
        assert r['reason']=='OBSERVATION_MODEL_INPUTS_UNKNOWN'
        assert r['components'] is None
    output={'base_sha':'1981bdef6e94e5e691871bb30bdb3fef7b1e36ef',
        'source_path':SOURCE.relative_to(ROOT).as_posix(), 'source_sha256':before,
        'new_sequence_inference_calls':0, 'phase_annotations_read':False,
        'results':results}
    OUT.mkdir(exist_ok=True)
    target.write_text(json.dumps(output,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({k:{'events':v['event_count'],'vehicles':v['vehicle_group_count'],
        'reason':v['reason']} for k,v in results.items()},indent=2))


if __name__=='__main__':
    main()
