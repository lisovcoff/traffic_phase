"""Collect existing frozen results and verified viewers; never fit or overwrite."""
import hashlib
from html import escape
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/learned_release_20261018'
VIEWS=ROOT.parent/'deliverables/traffic_phase_learned_20261018'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.write('\n')


def main():
    evaluation=json.loads((ROOT/'benchmarks/learned_clock_fixed_20261018/evaluation.json').read_text(encoding='utf8'))
    direct=json.loads((ROOT/'benchmarks/learned_clock_fixed_20261018/direct_label_diagnostics.json').read_text(encoding='utf8'))
    sealed=json.loads((ROOT/'benchmarks/learned_clock_fixed_20261018/predictions_sealed.json').read_text(encoding='utf8'))
    for item in sealed:
        assert sha(ROOT/'benchmarks/learned_clock_fixed_20261018/predictions'/item['file'])==item['sha256']
    rows=[]
    sites=['Ленина — Свердловский','Чичерина — 40 лет Победы','Ленина — Энтузиастов']
    for row,site in zip(evaluation['rows'],sites):
        variants={}
        for name in ('baseline','initial_learned','corrected_learned'):
            b=row['variants'][name]['histories']['raw_hsmm_segments']['boundaries']['mae_s']
            variants[name]={key:b[key] for key in ('matched_boundaries','truth_boundaries','predicted_boundaries')}
            variants[name]['matched_mae_s']=b['value']
        rows.append(dict(file=row['file'],site=site,variants=variants,
                         direct_labels=next(d for d in direct if d['file']==row['file'])))
    totals={name:{key:sum(r['variants'][name][key] for r in rows)
        for key in ('matched_boundaries','truth_boundaries','predicted_boundaries')}
        for name in ('baseline','corrected_learned')}
    assert totals['baseline']==dict(matched_boundaries=7,truth_boundaries=13,predicted_boundaries=17)
    assert totals['corrected_learned']==dict(matched_boundaries=11,truth_boundaries=13,predicted_boundaries=15)
    receipt=dict(status='PASS',scope='same-session chronological heldout half; training supplies K',
        tolerance_s=2,manual_marks_received_at_prediction=False,physical_lamp_accuracy_proven=False,
        universal_unsupervised_discovery_delivered=False,rows=rows,totals=totals,
        checks=dict(full_tests=1367,affected_tests_after_metadata_change=26,
                    browser_viewers=2,real_http_upload=True,raw_zip_integrations=2,
                    zip_scope='first lexicographic JSON and first observed session, not all members'))
    save(OUT/'summary.json',receipt)
    for entry in json.loads((VIEWS/'viewers.json').read_text(encoding='utf8')):
        source=VIEWS/entry['file'];assert sha(source)==entry['file_sha256']
        dest=OUT/'viewers'/source.name;dest.parent.mkdir(exist_ok=True)
        with dest.open('xb') as stream:stream.write(source.read_bytes())
    table=''
    for row in rows:
        old=row['variants']['baseline'];new=row['variants']['corrected_learned']
        table+=f"<tr><td>{escape(row['site'])}</td><td>{old['matched_boundaries']}/{old['truth_boundaries']}</td><td>{new['matched_boundaries']}/{new['truth_boundaries']}</td><td>{old['predicted_boundaries']} → {new['predicted_boundaries']}</td><td>{new['matched_mae_s']:.3f}</td></tr>"
    page='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Traffic Phase — проверка обученной модели</title><style>body{font:17px/1.55 system-ui;background:#10151d;color:#ecf1fa;max-width:1050px;margin:32px auto;padding:0 20px}a{color:#8ec8ff}table{border-collapse:collapse;width:100%;font-size:15px}th,td{padding:12px;text-align:left;border:1px solid #435063}.scroll{overflow-x:auto}.note{background:#263246;padding:18px;border-radius:10px}li{margin:10px 0}small{color:#b8c9dc}</style><h1>Обученная модель: 11/13 переключений</h1><p>На тех же контрольных окнах прежний алгоритм нашёл 7/13. Новая модель обучена по первой половине ручных отметок; вторая половина оставлена для контроля. При обработке нового файла разметка не загружается.</p><p class="note">Это проверка на продолжении знакомых записей. Количество фаз обучено. Универсальность на новых перекрёстках и точность физических ламп не доказаны. Полнота 84.6%; совпало 11 из 15 прогнозов (73.3%); пропущены 2 границы, 4 прогноза лишние.</p><h2>Открыть готовые результаты реальных ZIP</h2><ul><li><a href="viewers/lenina_sverdlovsky.html">Ленина — Свердловский: оценка сигналов и машины</a> — 4 основных светофора, допсекции только N/E.</li><li><a href="viewers/lenina_entuziastov.html">Ленина — Энтузиастов: фазы, движения и машины</a> — неизвестная конструкция светофоров не выдумывается.</li></ul><p>В каждом ZIP обработан первый JSON по имени и первый сеанс. Остальные источники не анализировались. Эти новые дни проверяют запуск и отображение, но без независимой разметки не дают новой оценки точности.</p><h2>Контроль ±2 секунды</h2><div class="scroll"><table><tr><th>Перекрёсток</th><th>Раньше</th><th>Теперь</th><th>Прогнозов</th><th>MAE совпавших, с</th></tr>'''+table+'''<tr><th>Всего</th><th>7/13</th><th>11/13</th><th>17 → 15</th><th>—</th></tr></table></div><p>Границы сопоставляются один к одному, без подбора сдвига. Первая и последняя отметки контрольного интервала цензурированы. MAE только по совпавшим не учитывает пропуски. Возможная задержка ручного нажатия до 3 с не превращает эти оценки в физическую точность переключения.</p><h2>Что проверено</h2><ul><li>1367 тестов полного набора и 26 соответствующих тестов после последних правок интерфейса.</li><li>Два реальных ZIP, реальный HTTP upload JSON 13.5 МБ, воспроизведение/пауза/перемотка и мобильный экран в изолированном Edge.</li><li>Все 11 совпавших границ ведут в правильную фазу по именам, установленным при обучении.</li></ul><h2>Что не сработало</h2><p>Два новых автоматических count-алгоритма проиграли прежнему и не включены по умолчанию. Первая обученная реализация дала 12/13, но независимый тест обнаружил ошибку её часов. После исправления сетки на тех же сохранённых моделях, без повторного обучения, результат 11/13. Исходный ошибочный результат сохранён, итогом считается исправленный.</p><h2>Новая загрузка</h2><p>Запустите START_WEB.cmd и откройте <a href="http://127.0.0.1:8017/visualization/learned">/visualization/learned</a>. Если сервер был запущен раньше обновления, остановите его Ctrl+C и запустите заново. Выберите перекрёсток, JSON/ZIP и нужный источник/сеанс.</p><p><a href="../../docs/LEARNED_PHASE_RESULTS_20261018.md">Подробный отчёт и ограничения</a> · <a href="summary.json">Числа JSON</a> · <a href="browser/results.json">Проверки браузера</a> · <a href="http/result.json">HTTP receipt</a></p><small>Исходные данные и старые результаты сохранены; main не изменён. Срок 20:00 Екатеринбург пропущен. Это результат проверки, а не обещание идеального алгоритма.</small></html>'''
    with (OUT/'summary.html').open('x',encoding='utf8',newline='\n') as stream:stream.write(page)
    logs=OUT/'logs';logs.mkdir(exist_ok=True)
    names=['learned_final_full_20261018.log','learned_final_targeted_20261018.log',
           'learned_browser_20261018.log','learned_http_check_20261018.log']
    for name in names:
        source=ROOT/'.web_runtime'/name
        if not source.exists():continue
        raw=source.read_bytes()
        decoded=raw.decode('utf-16') if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else raw.decode('utf8',errors='replace')
        with (logs/name).open('x',encoding='utf8',newline='\n') as stream:stream.write(decoded)
    files=[p for p in OUT.rglob('*') if p.is_file() and 'runs' not in p.relative_to(OUT).parts]
    save(OUT/'manifest.json',dict(format=1,scope='release evidence; HTTP raw uploads excluded and retained locally',
        files={str(p.relative_to(OUT)).replace('\\','/'):{'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(files)}))
    with (VIEWS/'report.html').open('x',encoding='utf8',newline='\n') as stream:
        copied=page.replace('href="viewers/','href="').replace('href="../../docs/',
            'href="../../audit_checkout/docs/')
        for target in ('summary.json','browser/results.json','http/result.json'):
            copied=copied.replace('href="'+target+'"',
                'href="../../audit_checkout/evidence/learned_release_20261018/'+target+'"')
        stream.write(copied)
    print(json.dumps(dict(status='PASS',totals=totals,manifest_files=len(files)),ensure_ascii=False))


if __name__=='__main__':main()
