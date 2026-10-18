"""Export frozen first-half models; add training-only display signatures."""
import json
from pathlib import Path
from scripts.isolated_phase_check import ROOT,sha

SITES={'17':'lenina_sverdlovsky','19':'chicherina_40let','6':'lenina_entuziastov'}


def main():
    from scripts.hsmm_recurrence_check import cached_bundle
    from app.core.learned_phase import training_movement_activity
    source=ROOT/'benchmarks/learned_profile_20261018'
    output=ROOT/'config/learned_profiles';output.mkdir(exist_ok=False)
    for path in sorted((source/'models').glob('*.json')):
        model=json.loads(path.read_text(encoding='utf8'))
        window=json.loads((source/'training'/path.name).read_text(encoding='utf8'))
        old,bundle=cached_bundle(ROOT/'benchmarks/manual_marks_20261018_baseline/predictions'/path.name)
        before=json.dumps(model,sort_keys=True)
        activity=training_movement_activity(bundle.temporal_events,window['marks'],
            start_ms=window['train_start_ms'],end_ms=window['train_end_ms'])
        assert json.dumps(model,sort_keys=True)==before
        site=SITES[path.name.split('_',1)[0]]
        model.update(site_id=site,trained_model_source_sha256=sha(path),
            movement_activity_by_label=activity,display_signature_source='training_half_only')
        with (output/(site+'.json')).open('x',encoding='utf8',newline='\n') as stream:
            json.dump(model,stream,ensure_ascii=False,indent=2)
        print('Exported',site,flush=True)


if __name__=='__main__':main()
