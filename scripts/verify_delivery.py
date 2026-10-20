"""Verify a running saved-model/player/online path; not a lamp-accuracy test."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.request


def verify(base,project,packets,*,limit=120):
    base=base.rstrip('/')
    def request(path,value=None,expected=200,text=False):
        body=None if value is None else json.dumps(value).encode('utf8')
        req=urllib.request.Request(base+path,data=body,headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=120) as response:
                status=response.status;raw=response.read()
        except urllib.error.HTTPError as error:status=error.code;raw=error.read()
        if status!=expected:raise RuntimeError(f'{path}: HTTP {status}; expected {expected}; {raw[:300]!r}')
        return raw.decode('utf8') if text else json.loads(raw)
    endpoint='/api/v1/intersections/'+project
    state=request(endpoint)
    if state['status'] not in ('READY','PARTIAL'):raise ValueError('Offline model is not ready')
    model=request(endpoint+'/model')
    page=request('/visualization?project='+project,text=True)
    if '<iframe' not in page:raise ValueError('Common panel missing')
    viewer=request(endpoint+'/sessions/'+model['sessions'][0]['session_id']+'/viewer',text=True)
    if '<canvas' not in viewer:raise ValueError('Offline vehicle player missing')
    stream=request(endpoint+'/online',{},expected=201)['stream_id'];online=endpoint+'/online/'+stream
    if 'traffic-online' not in request(online+'/viewer',text=True):raise ValueError('Online player missing')
    times=[];issued=[];last_packet=None;digest=hashlib.sha256();future_checked=False
    with Path(packets).open(encoding='utf8') as source:
        for line in source:
            if not line.strip():continue
            packet=json.loads(line);began=time.perf_counter();response=request(online+'/packets',packet)
            times.append(time.perf_counter()-began);issued.append(response);last_packet=packet
            digest.update(json.dumps(packet,sort_keys=True).encode())
            if response['timestamp_ms']!=packet['timestamp_ms']:raise ValueError('Wrong issuance timestamp')
            if set(response['heads'])!=set(model['approaches']):raise ValueError('Missing learned heads')
            if not future_checked and packet['vehicles']:
                bad=json.loads(json.dumps(packet));bad['sequence']+=1;bad['timestamp_ms']+=1000
                bad['vehicles'][0]['detections'][-1]['millis']=bad['timestamp_ms']+1
                request(online+'/packets',bad,expected=409);future_checked=True
            if len(issued)>=limit:break
    if not issued:raise ValueError('No packets supplied')
    if request(online+'/packets',last_packet)!=issued[-1]:raise ValueError('Duplicate packet changed result')
    bad=dict(last_packet,timestamp_ms=last_packet['timestamp_ms']+1)
    request(online+'/packets',bad,expected=409)
    if request(online)['snapshot']!=issued[-1]:raise ValueError('Latest response changed')
    middle=issued[len(issued)//2]
    if request(online+'/at?timestamp_ms='+str(middle['timestamp_ms']))['snapshot']!=middle:
        raise ValueError('Historical seek changed issuance')
    history=request(online+'/history?limit=1000')['snapshots']
    if history!=issued:raise ValueError('Journal history differs from issued prefix')
    return dict(status='PASS',scope='Functional HTTP checks, not physical signal accuracy',project_id=project,
        stream_id=stream,engine=issued[-1]['schema'],packets=len(issued),input_prefix_sha256=digest.hexdigest(),
        future_rejected=future_checked,duplicate_idempotent=True,conflict_rejected=True,history_seek_exact=True,
        tick_p95_s=sorted(times)[min(len(times)-1,int(len(times)*.95))],
        offline_url=base+'/visualization?project='+project,
        online_url=base+'/visualization?project='+project+'&stream='+stream)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',default='http://127.0.0.1:8017')
    p.add_argument('--project',required=True);p.add_argument('--packets',required=True,type=Path)
    p.add_argument('--limit',type=int,default=120);p.add_argument('--output',type=Path)
    a=p.parse_args()
    if not 1<=a.limit<=1000:p.error('--limit must be 1..1000')
    if a.output and a.output.exists():raise FileExistsError(a.output)
    result=verify(a.base,a.project,a.packets,limit=a.limit)
    if a.output:
        with a.output.open('x',encoding='utf8',newline='\n') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result,indent=2))
