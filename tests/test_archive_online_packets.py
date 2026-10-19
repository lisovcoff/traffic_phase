import json
import zipfile

from scripts.archive_online_packets import prepare


def test_archive_packets_merge_arrivals_without_future_fields_and_keep_namespaces(tmp_path):
    source=tmp_path/'input.zip'
    def track(origin,ds):return dict(id=1,zone_in=origin,zone_out='_S',future_summary='not available',detections=ds)
    with zipfile.ZipFile(source,'w') as archive:
        archive.writestr('first.json',json.dumps([track('N',[dict(millis=3999,zone='_S'),dict(millis=1001,zone='N')])]))
        archive.writestr('second.json',json.dumps([track('E',[dict(millis=1001,zone='E')])]))
    manifest=prepare(source,tmp_path/'spool.sqlite3',tmp_path/'packets.jsonl')
    packets=[json.loads(line) for line in (tmp_path/'packets.jsonl').read_text().splitlines()]
    assert manifest['packets']==3 and manifest['counts']['detections']==3
    assert [p['timestamp_ms'] for p in packets]==[2000,3000,4000]
    assert packets[1]['vehicles']==[]
    assert len({v['id'] for v in packets[0]['vehicles']})==2
    assert packets[2]['vehicles'][0]['id']==packets[0]['vehicles'][0]['id']
    for packet in packets:
        for vehicle in packet['vehicles']:
            assert set(vehicle)=={'id','zone_in','detections'}
            assert all(d['millis']<=packet['timestamp_ms'] for d in vehicle['detections'])
