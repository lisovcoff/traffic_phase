"""Published benchmark statistics must retain the source counts and scope."""
import hashlib
import json
from pathlib import Path


def test_readme_statistics_match_frozen_measurements_and_keep_short_colors_visible():
    root=Path(__file__).resolve().parents[1]
    source=root/'results/causal_v8.json'
    data=json.loads(source.read_text(encoding='utf8'))
    stats=json.loads((root/'results/statistics.json').read_text(encoding='utf8'))
    assert stats['source_sha256']==hashlib.sha256(source.read_bytes()).hexdigest()
    for key,label in [('baseline','v7'),('candidate','v8')]:
        summary=next(r for r in stats['overall'] if r['engine']==label)
        assert summary['total']==sum(r[key]['counts']['total'] for r in data['results'])
        assert summary['correct']==sum(r[key]['counts']['correct'] for r in data['results'])
        for color in ('RED','GREEN','YELLOW','RED_YELLOW'):
            row=next(r for r in stats['colors'] if r['engine']==label and r['color']==color)
            assert row['total']==sum(r[key]['counts'].get(color+'_total',0) for r in data['results'])
            assert row['correct']==sum(r[key]['counts'].get(color+'_correct',0) for r in data['results'])
    assert stats['strict_acceptance']==data['strict_acceptance']=='FAIL'
    assert not stats['all_six_real_archive_accuracy_established']
