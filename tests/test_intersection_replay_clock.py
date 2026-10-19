"""Playback must track packet time, including when requests take real time."""
import json
import shutil
import subprocess

import pytest

from app.api.intersection_panel import PAGE


def test_replay_clock_compensates_network_processing_and_handles_speed_changes():
    node=shutil.which('node')
    if not node:
        pytest.skip('Node required for browser clock regression')
    clock=PAGE.split('class ReplayClock{',1)[1].split('// Follow the inner',1)[0]
    script='class ReplayClock{'+clock+'''
const clock=new ReplayClock();
const actual=[clock.delay(100000,1,0),clock.delay(101000,1,300),
 clock.delay(102000,1,1400),clock.delay(103000,1,3500),
 clock.delay(104000,10,3600),clock.delay(105000,0,3750),
 clock.delay(106000,1,3800),clock.delay(107000,1,5000)];
process.stdout.write(JSON.stringify(actual));
'''
    result=subprocess.run([node,'-e',script],capture_output=True,text=True,check=True)
    # Requests taking300/400ms consume the inter-packet wait. Slow requests
    # catch up without extra sleep; changing speed anchors a new interval.
    assert json.loads(result.stdout)==[0,700,600,0,100,0,1000,800]
