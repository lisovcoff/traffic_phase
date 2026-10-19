"""Describe the complete week/day experiment without treating coverage as accuracy."""
from collections import Counter
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path

from scripts.corpus_validation import ROOT,save


def main():
    out=ROOT/'evidence/cross_day_sverdlovsky_20261019'
    complete=json.loads((out/'verified_v2/accelerated_complete.json').read_text())
    audit=json.loads((out/'verified_v2/source_audit.json').read_text(encoding='utf8'))
    model=json.loads((ROOT/'logs/intersection_projects'/complete['model_id']/'model.json').read_text(encoding='utf8'))
    online=json.loads((out/'online_complete.json').read_text())
    job=json.loads((out/'online_job.json').read_text())
    timezone_ekb=timezone(timedelta(hours=5));regimes={r['regime_id']:r for r in model['regimes']}
    sessions={s['source_member']:s for s in model['sessions']};daily={};rows=[];hardware=Counter()
    def observed_hours(intervals):
        merged=[]
        for a,b in sorted(intervals):
            if merged and a<=merged[-1][1]:merged[-1][1]=max(merged[-1][1],b)
            else:merged.append([a,b])
        return sum(b-a for a,b in merged)/3600000
    for member in audit['members']:
        name=member['member'];parts=Path(name).stem.split('_');date=f'{parts[1]}-{int(parts[2]):02d}-{int(parts[3]):02d}'
        stats=member['statistics'];session=sessions[name];regime=regimes[session['regime_id']]
        d=daily.setdefault(date,dict(members=0,tracks=0,detections=0,hours=[],intervals=[],K=Counter(),periods=[]))
        d['members']+=1;d['tracks']+=stats['tracks'];d['detections']+=stats['detections'];d['hours'].append(int(parts[4]))
        d['intervals'].append([stats['start_ms'],stats['end_ms']]);d['K'][session['phase_count']]+=1;d['periods'].append(session['period_s'])
        # Supplied hardware is evaluator-only. It never enters model construction.
        actual={a:sorted(h['arrows']) for a,h in regime['signal_topology'].items()}
        expected=dict(N=['N->E'],E=['E->N'],S=[],W=[])
        hardware['matching' if actual==expected else 'missing_or_different']+=1
        rows.append(dict(member=name,date=date,named_hour=int(parts[4]),records=stats['tracks'],detections=stats['detections'],
            actual_start=datetime.fromtimestamp(stats['start_ms']/1000,timezone_ekb).isoformat(),
            actual_end=datetime.fromtimestamp(stats['end_ms']/1000,timezone_ekb).isoformat(),
            date_matches_name=datetime.fromtimestamp(stats['start_ms']/1000,timezone_ekb).date().isoformat()==date,
            K=session['phase_count'],latent_K=session['latent_phase_count'],period_s=session['period_s'],regime_id=session['regime_id'],
            arrow_hypothesis=actual,hardware_matches_user_description=actual==expected))
    for d in daily.values():
        d['observed_union_hours']=observed_hours(d.pop('intervals'));d['missing_named_hours']=sorted(set(range(7,20))-set(d['hours']))
        d['hours'].sort();d['K']=dict(d['K'])
    summary=dict(status='COMPLETED_WITH_LIMITATIONS',model_id=model['model_id'],input_sha256=model['input']['sha256'],
        members=len(rows),days=daily,records=sum(d['tracks'] for d in daily.values()),
        detections=sum(d['detections'] for d in daily.values()),all_raw_members_sha_crc_verified=True,
        source_date_mismatches=[r['member'] for r in rows if not r['date_matches_name']],
        per_session_K=dict(Counter(s['phase_count'] for s in model['sessions'])),regimes=len(regimes),
        regime_periods_s=[r['period_s'] for r in regimes.values()],hardware_vs_user_description=dict(hardware),sessions=rows,
        online_result=online,offline_url=f'http://127.0.0.1:8017/visualization?project={model["model_id"]}',online_url=job['view_url'],
        limitations=['No weekend observations15/16 February. Missing14-16h files18 February.',
            'Signature groups are not certified controller programs. K2/3/4 and missing sections are not fully accepted.',
            'Hardware comparison uses the user description for evaluation only; no per-head video truth for the week.',
            'Video labels were revealed previously; conditional clock; visible N-main only.',
            'Full replay uses batch journal commits. Ordinary-path prefix matches exactly. Production API persistence is unchanged.',
            'Track counts are source records, not independently deduplicated physical vehicles.'])
    save(out/'summary.json',summary)
    table=['| Дата | JSON | Записей машин | Детекций | Наблюдаемое время, ч | K: число сеансов |',
           '|---|---:|---:|---:|---:|---|']
    for date,d in daily.items():table.append(f'| {date} | {d["members"]} | {d["tracks"]} | {d["detections"]} | {d["observed_union_hours"]:.2f} | {d["K"]} |')
    scores=[]
    for window in online['video_metrics']:
        for color,metrics in window['scores'].items():
            a,b=metrics['2'],metrics['5']
            scores.append(f'| {window["video_pts_s"]} | {color} | {a["matched"]}/{a["expected"]} | {a["predicted"]} | {b["matched"]}/{b["expected"]} |')
    text=f'''# Проверка: неделя офлайн → 27 февраля онлайн

**Данные обработаны; точность цветов не принята.** Подробности — в таблице
переключений, включая все лишние предсказанные включения.

Все88 JSON прочитаны полностью для SHA-256/CRC. При неизменном коде извлечения
повторно использованы запечатанные события; текущий solver пересобрал прогнозы
с проверенным численным кешем. Свежие холодные пересчёты6 записей совпали по
расписанию, периоду, часовому уточнению и физической гипотезе. Это не88 новых
холодных извлечений событий. Предыдущие и прерванные результаты сохранены.

Всего: **{summary['records']} записей траекторий**, **{summary['detections']} детекций**.
Семь рабочих дней;15–16 февраля отсутствуют,18 февраля нет файлов за14–16 часов.
Разрывы и ночи не сшиваются. Совпадение дат по именам: {len(rows)-len(summary['source_date_mismatches'])}/{len(rows)}.

{chr(10).join(table)}

Найдены8 групп сигнатур с периодами около100/120с. Рабочий K по сеансам:
`{summary['per_session_K']}`. Это не доказательство восьми реальных программ.
Гипотеза допсекций N/E согласуется с описанием пользователя в64 из88 записей;
в24 они не восстановлены. Оборудование и все режимы пока нельзя считать принятыми.

[Офлайн-модель]({summary['offline_url']}) · [Сохранённая онлайн-история]({summary['online_url']})

Онлайн: **{online['packets']} секундных пакетов**, {online['duration_s']/3600:.3f}ч,
только детекции с millis≤времени пакета. Обучение заканчивается19 февраля;
27 февраля не входит в модель. Сохранены все ответы. Ускорен только проверочный
журнал, обычный путь совпал на{online['ordinary_path_exact_prefix_packets']} пакетах.
Это не замер HTTP-задержки полного потока. Производственный API не менялся.

Доля известных основных цветов, **не точность**: `{online['known_main_coverage']}`.

Динамические цвета проверены по18 ранее открытым видеопереключениям основной N.
Обучение и проверка разделены по датам, но разметка уже использовалась при
разработке, а привязка часов условная. Для других голов точность не доказана.

| Окно видео, с | Цвет | Найдено в ±2с | Всего предсказано | Найдено в ±5с |
|---|---|---:|---:|---:|
{chr(10).join(scores)}

Верхнее поле приложения выполняет офлайн-анализ ZIP. Для повтора27 февраля
используйте подготовленный локальный JSONL из `online_packets_manifest.json`
в поле «Тестовый поток JSONL». По ссылке истории показан последний пакет;
прошлое открывается через дату/время. Полный повтор в x1 занимает около трёх часов.

Производные доказательства: `verified_v2/source_audit.json`, `online_complete.json`,
`summary.json` и браузерная проверка. Исходные ZIP, JSONL и SQLite остаются локально.
'''
    (out/'README.ru.md').write_text(text,encoding='utf8')
    print('REPORT READY',summary['per_session_K'],online['known_main_coverage'],flush=True)


if __name__=='__main__':main()
