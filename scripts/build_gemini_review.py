"""Build a bounded independent-review ZIP with real evidence and portable scoring."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
MAX_BYTES=10_000_000


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT).decode('utf-8').strip()


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        stream.write('\n')


def copy(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as stream:
        stream.write(source.read_bytes())


def extract_sample(source,target,first_mark,window_s):
    from app.core.v9.events import _iter_json_records_from_path
    core=[first_mark,first_mark+window_s*1000]
    context=[core[0]-30_000,core[1]+30_000]
    sample,provenance=[],[]
    total=0
    for ordinal,track in enumerate(_iter_json_records_from_path(source)):
        total+=1
        detections=track.get('detections') or []
        valid=[d for d in detections if isinstance(d,dict) and isinstance(d.get('millis'),(int,float))]
        if not any(core[0]<=d['millis']<=core[1] for d in valid):
            continue
        kept=[d for d in valid if context[0]<=d['millis']<=context[1]]
        row=dict(track)
        row['detections']=kept
        sample.append(row)
        times=[d['millis'] for d in valid]
        provenance.append(dict(source_record_ordinal_zero_based=ordinal,track_id=track.get('id'),
            original_detection_count=len(detections),kept_detection_count=len(kept),
            original_range_ms=[min(times),max(times)],
            detections_clipped=len(kept)!=len(detections)))
    if not sample:
        raise ValueError(f'empty sample: {source}')
    save(target,sample)
    return dict(core_range_ms=core,context_range_ms=context,source_record_count=total,
        selected_tracks=len(sample),sample_sha256=sha(target),track_provenance=provenance,
        selection='all tracks with >=1 valid detection in first marked 120s (or explicit window_s); detections clipped to +/-30s context',
        raw_field_changes='only detections array clipped; all retained detection values and other track fields preserved',
        interpretation='raw inspection excerpt, NOT a full source or a prediction replay input; clipped track boundaries change evidence')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--sample-window-s',type=int,default=120)
    args=parser.parse_args()
    if args.sample_window_s<=0:
        raise ValueError('positive sample window required')
    if git('status','--porcelain'):
        raise ValueError('commit review source changes before packaging')
    stage=args.stage.resolve()
    stage.mkdir(parents=True,exist_ok=False)
    output=args.output.resolve()
    if output.exists():
        raise FileExistsError(output)
    tracked=git('ls-files','-z').split('\0')
    included,excluded=[],[]
    root_files={'README.md','ROADMAP.md','AGENTS.md','Dockerfile','requirements.txt',
        'requirements-tested-py312.txt','pytest.ini','START_WEB.cmd','START_ANNOTATION.cmd','INSTALL.cmd'}
    for name in tracked:
        if not name:
            continue
        source=ROOT/name
        selected=(name in root_files or name.startswith(('app/','scripts/','config/','docs/')) or
                  name.startswith('tests/') and source.stat().st_size<1_000_000 or
                  name.startswith(('benchmarks/manual_marks_20261018_baseline/',
                                   'benchmarks/manual_marks_20261018_channels/',
                                   'evidence/manual_marks_20261018/')))
        if selected:
            copy(source,stage/name)
            included.append(name)
        else:
            excluded.append(name)
    baseline=read(ROOT/'benchmarks/manual_marks_20261018_baseline/baseline_metrics.json')
    rows=[]
    for row in baseline['rows']:
        source=Path(row['source_path'])
        annotation=Path(row['annotation_path'])
        assert sha(source)==row['source_sha256']
        assert sha(annotation)==row['annotation_sha256']
        name=row['source_name']
        target=stage/'data/raw_samples'/name
        print('Extract raw inspection sample:',name,flush=True)
        sample=extract_sample(source,target,row['annotation_validation']['known_range_ms'][0],args.sample_window_s)
        annpath=Path('data/manual_marks')/annotation.name
        copy(annotation,stage/annpath)
        sample.update(source_name=name,source_bytes=source.stat().st_size,
            source_sha256=row['source_sha256'],annotation_sha256=row['annotation_sha256'],
            annotation=annpath.as_posix(),sample=target.relative_to(stage).as_posix(),
            prediction='benchmarks/manual_marks_20261018_baseline/'+row['prediction_file'])
        rows.append(sample)
        print('Sample tracks:',sample['selected_tracks'],'bytes:',target.stat().st_size,flush=True)
    for name in ('17_2025_2_12_7_review.json','19_2025_2_25_8_review.json','6_2025_2_14_6_review.json'):
        copy(ROOT.parent/'data'/name,stage/'data/operator_reviews'/name)
    save(stage/'data/review_sources.json',dict(rows=rows,sample_window_s=args.sample_window_s,
        full_source_trajectories_included=False,full_extracted_event_caches_included=True,
        sampling_used_marks_only_to_locate_review_excerpt=True,inference_uses_marks=False))
    copy(ROOT/'docs/GEMINI_REVIEW_BRIEF_20261018.md',stage/'01_PROMPT_FOR_GEMINI.md')
    readme='''# Review package: traffic_phase, 18.10.2026

Передай Gemini файл `01_PROMPT_FOR_GEMINI.md` как задание. Сначала попроси
подтвердить доступ к файлам, затем проверять причины реальных ошибок по коду.

- app/scripts/config: текущий код, включая default и явно выделенные эксперименты.
- tests: исходники тестов и небольшие fixtures. Полный pytest требует также
  больших исторических evidence/fixtures, исключённых из компактного пакета.
- benchmarks/manual_marks_20261018_baseline: все три полных извлечённых cache
  событий и сохранённые predictions, не только удачные фрагменты.
- benchmarks/manual_marks_20261018_channels: отклонённый кандидат с freeze.
- data/manual_marks и data/operator_reviews: оригинальные ручные файлы.
- data/raw_samples: по120с в размеченном участке с30с контекста с каждой стороны,
  все попавшие в окно машины; detections обрезаны. Данные не синтетические.
  Точные интервалы, исходные хэши и обрезки: data/review_sources.json.
- evidence/manual_marks_20261018: прежние оценки, пропуски, лишние границы,
  результаты и неудачи проверок, скриншоты.

Полные исходные trajectory JSON (~400МБ), видео, окружения, Git history,
старые большие evidence и lenina_video_sample_20mb.json не включены.
Сырые образцы не воспроизводят полный inference. Полные извлечённые события
позволяют проверить сегментацию/выбор K без нового чтения исходных trajectory.
Чтобы проверить extractor на всех исходных данных, потребуются сами большие JSON.
Файлы исходников не отредактированы для архива; сверяй REVIEW_MANIFEST.json.

## Проверить без сторонних пакетов

Из корня распакованного архива:

    python -m scripts.review_reproduce_manual_marks --verify-only

## Пересчитать оценки сохранённых predictions (без обучения)

Python3.12; зависимости — requirements-tested-py312.txt (либо requirements.txt).

    python -m pip install -r requirements-tested-py312.txt
    python -m scripts.review_reproduce_manual_marks --check-caches

Последняя команда проверяет byte hashes, эквивалентность полных event caches
и точно воспроизводит прежние оценки. Fitting не запускается.
Для дополнительных прогонов сначала зафиксируй гипотезу/параметры/бюджет,
новые файлы результатов и отдельную оценку, не меняй сохранённые predictions.

Факт плохой точности на двух записях не скрыт. Успешные tests/UI не равны
точности определения сигналов. Известная схема Свердловского — внешний ввод.
Все файлы, кроме самого REVIEW_MANIFEST.json, имеют SHA-256 в манифесте.
'''
    if args.sample_window_s!=120:
        readme=readme.replace('по120с',f'по{args.sample_window_s}с')
    (stage/'00_README_REVIEW.md').write_text(readme,encoding='utf-8',newline='\n')
    files={p.relative_to(stage).as_posix():dict(bytes=p.stat().st_size,sha256=sha(p))
        for p in sorted(stage.rglob('*')) if p.is_file()}
    save(stage/'REVIEW_MANIFEST.json',dict(schema=1,source_commit=git('rev-parse','HEAD'),
        source_branch=git('branch','--show-current'),max_archive_bytes=MAX_BYTES,
        files=files,included_tracked_files=included,excluded_tracked_files=excluded,
        original_source_trajectories_total_bytes=sum(r['source_bytes'] for r in rows),
        review_scope='independent code+real-data review; not a full delivery; no inference during packaging'))
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for path in sorted(stage.rglob('*')):
            if path.is_file():
                archive.write(path,path.relative_to(stage).as_posix())
    if output.stat().st_size>MAX_BYTES:
        raise ValueError(f'archive exceeds 10,000,000 bytes: {output.stat().st_size}; preserved, do not upload')
    with zipfile.ZipFile(output) as archive:
        names=archive.namelist()
        assert len(names)==len(set(names))
        assert all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts for n in names)
        assert archive.testzip() is None
        expected=read(stage/'REVIEW_MANIFEST.json')['files']
        assert set(names)==set(expected)|{'REVIEW_MANIFEST.json'}
        for name,entry in expected.items():
            value=archive.read(name)
            assert len(value)==entry['bytes'] and hashlib.sha256(value).hexdigest()==entry['sha256']
    print(json.dumps(dict(status='PASS',archive=str(output),bytes=output.stat().st_size,
        sha256=sha(output),files=len(files)+1),indent=2),flush=True)


if __name__=='__main__':
    main()
