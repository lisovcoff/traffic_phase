"""Full-byte audit: can exact-zero restart extraction change cached evidence?"""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
from pathlib import Path
import re
from scripts.corpus_validation import source_stream,save

SPEED=re.compile(rb'"speed"\s*:\s*([^,}]+)[,}]')
KEY=b'"speed"'


def audit(job,expected,out):
    dest=out/(job['id']+'.json')
    if dest.exists():return job['id'],'existing'
    present=False;conclusive=True;tail=b''
    with source_stream(job) as stream:
        while True:
            block=stream.read(4*1024*1024)
            if not block:break
            if present:continue
            buf=tail+block;last_end=0
            for match in SPEED.finditer(buf):
                last_end=match.end()
                try:present=float(match[1])==0.
                except ValueError:continue
                if present:break
            # Retain an unfinished speed key/value across arbitrary chunk or
            # whitespace boundaries. Complete source JSON validity is already
            # established by canonical baseline ingestion and full SHA equality.
            last_key=buf.rfind(KEY)
            tail=buf[last_key:] if last_key>=last_end else buf[-(len(KEY)-1):]
            if len(tail)>16*1024*1024:conclusive=False;tail=b''
        digest=stream.hash.hexdigest();size=stream.bytes
    assert digest==expected['sha256'] and size==expected['bytes_read'],'source changed since baseline'
    row=dict(job=job,sha256=digest,bytes_read=size,crc_checked=bool(job.get('member')),
        exact_zero_speed_present=present,absence_scan_conclusive=conclusive,
        evidence_cache_reusable_for_exact_zero_restart=conclusive and not present,
        semantics='speed numeric literals parsed as floats, including negative zero and underflow; absent numeric zero prevents the exact-zero restart branch')
    save(dest,row)
    return job['id'],'zero-present' if present else 'no-zero' if conclusive else 'reparse-required'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    jobs=json.loads((a.baseline/'inventory.json').read_text(encoding='utf8'))['jobs']
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures=[pool.submit(audit,j,json.loads((a.baseline/'results'/(j['id']+'.json')).read_text(encoding='utf8')),a.out) for j in jobs]
        for f in as_completed(futures):print(*f.result(),flush=True)


if __name__=='__main__':main()
