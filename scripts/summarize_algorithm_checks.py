"""Publish all frozen candidate outcomes, including failures, without fitting."""
import html
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/algorithm_checks_20261018'
CASES=[('Отбор по машине','per_track_permission_20261018','Отклонён: ухудшение времени'),
       ('Равные ограничения длительности','isolated_equal_durations_20261018','Принят: контрпример исправлен, реальные результаты без изменений'),
       ('Только правдоподобие','isolated_likelihood_only_20261018','Отклонён: ухудшение'),
       ('Положительные фронты','observation_positive_onsets_20261018','Отклонён: лишняя фаза JSON19'),
       ('Цензурирование пустых секунд','observation_silent_censoring_20261018','Отклонён: ухудшение')]


def main():
    OUT.mkdir(parents=True,exist_ok=False)
    rows=[]
    for title,folder,decision in CASES:
        report=json.loads((ROOT/'benchmarks'/folder/'evaluation.json').read_text(encoding='utf8'))
        for source in report['rows']:
            metric=source['variants']['candidate_latent']
            boundary=metric['histories']['raw_hsmm_segments']['boundaries']['mae_s']
            rows.append(dict(candidate=title,file=source['file'],decision=decision,
                k=metric['phase_count_match']['predicted'],truth_k=metric['phase_count_match']['annotation_distinct_labels'],
                matched=boundary['matched_boundaries'],truth=boundary['truth_boundaries'],
                predicted=boundary['predicted_boundaries'],mae_matched_s=boundary['value'],
                reaction_compatible=metric['reaction_0_3s']['raw_hsmm_segments']['compatible_boundaries'],
                report=f'../../benchmarks/{folder}/evaluation.json'))
    with (OUT/'summary.json').open('x',encoding='utf8',newline='\n') as stream:
        json.dump(dict(rows=rows,candidate_runs=15,integration_runs=3,
            baseline_strict=[15,1,3],accepted_strict=[15,1,3],truth_boundaries=[17,8,9],
            interpretation='development data; NO measured real timing improvement',
            promoted='equal_durations_only',per_track_selector_default=False),stream,ensure_ascii=False,indent=2)
    headers=['Вариант','JSON','K оценки / меток','Совпало ±2с','Предсказано','MAE совпавших, с','Реакция 0–3с','Решение']
    body=[]
    for row in rows:
        cells=[row['candidate'],row['file'],f"{row['k']} / {row['truth_k']}",f"{row['matched']} / {row['truth']}",
            row['predicted'],round(row['mae_matched_s'],3) if row['mae_matched_s'] is not None else '—',
            f"{row['reaction_compatible']} / {row['truth']}",row['decision']]
        body.append('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in cells)+'</tr>')
    page='''<!doctype html><html lang="ru"><meta charset="utf-8"><title>Проверка исправлений алгоритма</title>
    <style>body{font:15px system-ui;margin:25px;background:#171c23;color:#eee}table{border-collapse:collapse}td,th{border:1px solid #556;padding:8px;text-align:left}th{background:#293444}p{max-width:1000px}a{color:#9cf}</style>
    <h1>Проверка пяти алгоритмических гипотез, 18.10.2026</h1>
    <p><b>Улучшения времени на реальных записях не подтверждены.</b> До и после принятого исправления:15/17,1/8,3/9 границ в ±2с. Принято только выравнивание допустимых длительностей K2/K3: оно исправляет независимый пример цикла20/80с, не ухудшая эти три записи.</p>
    <p>Отбор по машине реализован отдельно и проверен, но оставлен экспериментальным: прямое включение ухудшило результаты. Ещё три варианта отклонены. Ни один не выбирался отдельно для конкретного файла.</p>
    <p>Каждый вариант: один замороженный прогон трёх полных кешей событий, без ручных отметок во входе и подгонки сдвига. Все predictions сохранены до оценки. Первая и последняя отметки исключены как границы окна. MAE только по совпавшим границам, пропуски не скрыты.</p>
    <p>Реакция0–3с означает интервал[отметка−3с,отметка], отдельно от ±2с. Данные знакомые, не независимый holdout; ни одна цифра не является доказанной точностью физических цветов.</p>
    <table><tr>'''+''.join('<th>'+h+'</th>' for h in headers)+'</tr>'+''.join(body)+'''</table>
    <p>Структурированный отчёт: <a href="summary.json">summary.json</a>. Полные пары, пропуски и лишние границы — в evaluation.json каждого варианта.</p></html>'''
    with (OUT/'summary.html').open('x',encoding='utf8',newline='\n') as stream:
        stream.write(page)
    print('All five outcomes published:',OUT)


if __name__=='__main__':main()
