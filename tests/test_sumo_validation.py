"""Optional independent-simulator contract checks, not production dependencies."""
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from scripts.sumo_validation import conflicting_greens, run


def test_geometric_conflict_gate_does_not_trust_intended_groups():
    network = ET.fromstring('''<net>
      <junction id="C" intLanes="a b c">
        <request index="0" foes="010"/>
        <request index="1" foes="001"/>
        <request index="2" foes="000"/>
      </junction>
      <connection tl="C" linkIndex="0" via="c"/>
      <connection tl="C" linkIndex="1" via="a"/>
      <connection tl="C" linkIndex="2" via="b"/>
    </net>''')
    assert not conflicting_greens(network, ['GGr', 'rrG'])
    assert conflicting_greens(network, ['rGG']) == [dict(state='rGG', requests=[0,1])]


@pytest.mark.parametrize('approaches', [3, 4])
def test_native_simulation_export_and_physics(tmp_path, approaches):
    home = os.environ.get('TRAFFIC_TEST_SUMO_HOME')
    if not home:
        pytest.skip('Optional SUMO integration: set TRAFFIC_TEST_SUMO_HOME')
    target = tmp_path/'case'
    audit = run(dict(seed=101, k=3, approaches=approaches, duration_s=220,
                     period_s=100), target, Path(home))
    assert audit['physics_status'] == 'PASS'
    assert len(audit['represented_approaches']) == approaches
    records = json.loads((target/'vehicles.json').read_text())
    assert {r['zone_in'] for r in records} == ({'N','E','S'} if approaches == 3 else {'N','E','S','W'})
    for record in records:
        assert not {'signal', 'phase', 'color', 'k', 'truth'}.intersection(record)
        assert all(.16 < d['centroid_x'] < .84 and .16 < d['centroid_y'] < .84
                   for d in record['detections'])
        times = [d['millis'] for d in record['detections']]
        assert times == sorted(set(times))
    # Existing artifacts must not be silently overwritten.
    with pytest.raises(FileExistsError):
        run(dict(), target, Path(home))
