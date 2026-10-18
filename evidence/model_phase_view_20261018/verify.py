"""Verify saved display evidence without phase inference or a browser launch."""
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
manifest = json.loads((OUT/'manifest.json').read_text(encoding='utf-8'))
for name, expected in manifest['files'].items():
    assert hashlib.sha256((OUT/name).read_bytes()).hexdigest() == expected, name
browser = json.loads((OUT/'browser_results.json').read_text(encoding='utf-8'))
assert len(browser['real']['phases']) == 3 and len(browser['synthetic']['phases']) == 2
for case in browser.values():
    assert case['status'] == 'PASS' and not case['browser_errors']
    assert case['lamps_remain_unknown'] and case['display_switch']
    assert case['timeline_click'] and case['playback'] and case['mobile_no_overflow']
assert '73 passed' in (OUT/'tests.log').read_text(encoding='utf-8')
assert manifest['real_phase_fits'] == 0 and not manifest['accuracy_gain_claimed']
print(json.dumps({'status': 'PASS', 'files': len(manifest['files']), 'targeted_tests': 73}))
