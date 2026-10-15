"""Read exactly one chosen ZIP entry once; export a small unmodified-track sample."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from app.core.calibration_sample import select_raw_window


def prepare(archive,entry,start,end,out):
    if out.exists():raise ValueError('fresh output directory required')
    a,b=[datetime.fromisoformat(x) for x in (start,end)]
    if a.tzinfo is None or b.tzinfo is None:raise ValueError('explicit time zone required')
    begin,finish=[int(x.timestamp()*1000) for x in (a,b)]
    with ZipFile(archive) as z:
        info=z.getinfo(entry)
        if info.file_size>300*1024*1024:raise ValueError('chosen entry exceeds scan byte budget')
        inventory=[{'name':i.filename,'uncompressed_bytes':i.file_size,'compressed_bytes':i.compress_size,
                    'crc32':f'{i.CRC:08x}'} for i in z.infolist()]
        with z.open(info) as stream: tracks,report=select_raw_window(stream,begin,finish)
    out.mkdir(parents=True)
    sample=out/'calibration_tracks.json'
    sample.write_bytes((json.dumps(tracks,ensure_ascii=False,separators=(',',':'))+'\n').encode())
    report.update(archive={'path':str(archive.resolve()),'bytes':archive.stat().st_size,
        'inventory':inventory,'whole_archive_sha256':None,'entries_decoded':[entry]},
        source_entry=entry,source_entry_crc32=f'{info.CRC:08x}',source_entry_bytes=info.file_size,
        sample={'file':sample.name,'sha256':hashlib.sha256(sample.read_bytes()).hexdigest(),'bytes':sample.stat().st_size},
        clock_alignment='UNVERIFIED; JSON absolute timestamp assumptions require vehicle/video matching',
        role='calibration_candidate; no validation labels consumed')
    (out/'sample_manifest.json').write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
    print(json.dumps({k:report[k] for k in ('selected_tracks','input_bytes_read','runtime_s','recommended_preview_start_s','recommended_preview_duration_s','sample')},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',type=Path,required=True);p.add_argument('--entry',required=True)
    p.add_argument('--start',required=True);p.add_argument('--end',required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();prepare(a.archive,a.entry,a.start,a.end,a.out)
