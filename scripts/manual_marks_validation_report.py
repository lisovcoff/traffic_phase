"""Score sealed manual-marks runs without altering inference or fitting offsets."""
from copy import deepcopy
import hashlib
import html
import json
from pathlib import Path

from app.core.manual_delay_evaluation import evaluate_reaction_bound
from app.core.offline_benchmark import evaluate_prediction, validate_annotation
from app.core.v10.estimated_signals import build_estimated_signals

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'evidence/manual_marks_20261018'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_sealed(path, content):
    if path.exists():
        if path.read_text(encoding='utf-8') != content:
            raise ValueError(f'refusing to replace different artifact: {path}')
        return
    with path.open('x',encoding='utf-8') as stream:
        stream.write(content)


def resolved_prediction(prediction, profile):
    projection = build_estimated_signals(prediction, profile_id=profile)
    if not projection['available']:
        return None, projection
    result = deepcopy(prediction)
    schedule = result['schedule']
    names = schedule['phase_names']
    schedule['phase_count'] = projection['operating_phase_count']
    schedule['phase_names'] = [s['name'] for s in projection['states']]
    for field in ('raw_hsmm_segments','baseline_segments'):
        rows = []
        for a,b,z in prediction['schedule'][field]:
            state = projection['phase_mapping'][names[int(z)]]
            if rows and rows[-1][1] == a and rows[-1][2] == state:
                rows[-1][1] = b
            else:
                rows.append([a,b,state])
        schedule[field] = rows
    return result, projection


def evaluate(prediction, annotation):
    score = evaluate_prediction(prediction, validate_annotation(annotation))
    score['operator_delay_compatibility'] = {
        field:evaluate_reaction_bound(prediction, annotation, field=field)
        for field in ('raw_hsmm_segments','baseline_segments')}
    return score


def main():
    OUT.mkdir(exist_ok=True)
    baseline = ROOT/'benchmarks/manual_marks_20261018_baseline'
    candidate = ROOT/'benchmarks/manual_marks_20261018_channels'
    sealed = {r['file']:r['sha256'] for r in read(candidate/'predictions_sealed.json')}
    rows = []
    for source in read(baseline/'baseline_metrics.json')['rows']:
        annotation_path = Path(source['annotation_path'])
        assert sha(annotation_path) == source['annotation_sha256']
        annotation = read(annotation_path)
        name = source['source_name']
        filename = Path(name).stem+'_v9.json'
        row = dict(source=name, annotation_sha256=sha(annotation_path),
                   source_sha256=source['source_sha256'], variants={})
        for run,folder in (('baseline',baseline),('controlled_channels',candidate)):
            path = folder/'predictions'/filename
            digest = sha(path)
            assert digest == (sealed[filename] if run=='controlled_channels'
                              else source['prediction_sha256_before_evaluation'])
            prediction = read(path)
            row['variants'][run+'_latent'] = dict(prediction_sha256=digest,
                conditional_on_operator_catalog=False, metrics=evaluate(prediction,annotation))
            for profile in (['none','lenina_sverdlovsky'] if name.startswith('17_') else ['none']):
                resolved, projection = resolved_prediction(prediction,profile)
                row['variants'][run+'_'+profile] = dict(prediction_sha256=digest,
                    conditional_on_operator_catalog=profile!='none', projection=projection,
                    metrics=evaluate(resolved,annotation) if resolved else None)
            assert sha(path) == digest
        rows.append(row)
    report = dict(schema='manual-marks-sealed-comparison-v1', rows=rows,
        interpretation='development/regression, not independent physical lamp accuracy',
        timing='No time shift fitted; strict +/-2 seconds unchanged; reaction interval [mark-3s,mark] separate.',
        controlled_channels='Sverdlovsky known channels; other sites through-only diagnostic assumption.',
        operator_catalog='Known scheme is a conditional projection, not evidence of automatic K discovery.')
    write_sealed(OUT/'comparison.json',json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    table = []
    for row in rows:
        for variant,result in row['variants'].items():
            if not result['metrics']:
                continue
            metrics = result['metrics']
            raw = metrics['histories']['raw_hsmm_segments']
            b = raw['boundaries']['mae_s']
            reaction = metrics['operator_delay_compatibility']['raw_hsmm_segments']
            cells = [row['source'],variant,metrics['phase_count_match']['predicted'],
                metrics['phase_count_match']['annotation_distinct_labels'],
                f"{b['matched_boundaries']}/{b['truth_boundaries']}",b['predicted_boundaries'],
                round(b['value'],3) if b['value'] is not None else '—',
                f"{reaction['compatible_boundaries']}/{reaction['truth_boundaries']}",
                round(raw['phase_agreement_diagnostic']['value']*100,2)
                    if raw['phase_agreement_diagnostic']['value'] is not None else 'unavailable (K differs)']
            print(' | '.join(map(str,cells)))
            table.append('<tr>'+''.join('<td>'+html.escape(str(c))+'</td>' for c in cells)+'</tr>')
    headers=['JSON','Вариант','K оценки','K отметок','Совпадения ±2 с','Всего предсказано',
             'MAE только совпавших, с','Совместимо с реакцией 0–3 с','Согласие фаз, %*']
    page='''<!doctype html><html lang="ru"><meta charset="utf-8"><title>Проверка ручной разметки</title>
    <style>body{font:16px system-ui;margin:30px;background:#171c23;color:#eee}table{border-collapse:collapse}td,th{padding:10px;border:1px solid #556;text-align:left}th{background:#293444}p{max-width:1100px}a{color:#9cf}</style>
    <h1>Проверка всех трёх JSON с ручной разметкой</h1>
    <p>Ленина—Свердловский: 4 основных светофора, дополнительные секции только N и E. Цвета — оценка по транспортным потокам. Наблюдения ламп отсутствуют. Контрольные времена не подавались алгоритму.</p>
    <p>Строгая проверка ±2 с сохранена. Отдельно показана совместимость с заявленной задержкой оператора: предсказание должно лежать от 3 секунд до отметки включительно. Сдвиг времени не подбирался. Первая и последняя отметки исключены как границы окна.</p>
    <p>* Согласие фаз вычислено на секундной сетке с перестановкой анонимных меток; это не точность физических цветов. MAE относится только к совпавшим границам, пропуски отражены в соседних столбцах. Это знакомые данные разработки, а не независимая выборка.</p>
    <p>latent — исходные скрытые классы; none — состояния автоматического предложения схемы после объединения соседних одинаковых состояний; lenina_sverdlovsky — проекция на известную схему оператора (условный результат). controlled_channels — отдельный замороженный эксперимент, не включённый в приложение.</p>
    <table><thead><tr>'''+''.join('<th>'+h+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join(table)+'''</tbody></table>
    <p>Полные совпадения, пропуски, лишние переключения, односторонние ошибки и SHA-256: <a href="comparison.json">comparison.json</a>.</p></html>'''
    write_sealed(OUT/'comparison.html',page)


if __name__=='__main__':
    main()
