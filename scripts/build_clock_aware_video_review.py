"""Export independently clock-linked N-main truth and fixed calibration review."""
from html import escape
import json
import re
from app.experimental.video_clock_mapping import map_bracket,source_bias
from app.experimental.video_onset_bias import evaluate_bias
from scripts.cardinal_clock_link import ROOT,OUT,read,save,sha

OLD=ROOT/'evidence/direct_video_truth_20261018'


def main():
    save(OUT/'user_head_corrections.json',dict(
        enthusiasts=dict(reply_verbatim='он обслуживает e(но они идентичные с w в данном случае)',
            visible_head_approach='E',main_E_W_same_per_user=True,
            W_independently_observed=False,clock_alignment_not_implied=True),
        sverdlovsky=dict(reply_verbatim='на видео n => e и в джсоне n =>e. ранее я перепутал',
            extra_section_movement='N->E',main_approach='N',
            old_relative_arrow_direction_superseded=True,
            global_E_W_swap_authorized=False,
            note='Latest user correction governs arrow assignment; retain earlier orientation as history, do not infer a global zone permutation.')))
    clock_path=OUT/'sverdlovsky_late_control/clock_validation.json';clock=read(clock_path)
    assert clock['status']=='PASS'
    delta=clock['fixed_delta_s'];bounds=clock['all_four_car_conditional_delta_intersection_s']
    assert len(bounds)==1
    bounds=bounds[0]
    old=read(OLD/'conditional_onset_calibration/frozen_candidates.json')
    origin=old['nominal_video_epoch_ms'];data=read(OLD/'comparison_data.json')
    pred_path=ROOT/'evidence/learned_archive_integration_20261018/archive_1/result.json'
    assert sha(pred_path)==old['source_prediction_sha256']
    candidates={};mapped=[];evaluation={}
    for color,file in [('green','video_only_truth_sealed.json'),('red','video_red_truth_sealed.json')]:
        path=OLD/'sverdlovsky'/file;assert sha(path)==old['truth_sha256'][color]
        bias=source_bias(old['candidates'][color]['bias_s'],delta)
        candidates[color]=dict(bias_s=bias,
            conditional_bias_range_s=[old['candidates'][color]['bias_s']-bounds[1],old['candidates'][color]['bias_s']-bounds[0]],
            rule='Same frozen calibration-only median rule, converted to independently supported JSON clock. No refit or new test optimization.',
            population='this session and visible N main only',production_enabled=False)
        for window in read(path)['windows']:
            for row in window['transitions']:
                mapped.append(dict(color=color.upper(),window=window['window'],index=row['index'],
                    head_approach='N',section='main',truth_source_sha256=sha(path),
                    **map_bracket(row['bracket_s'],origin_ms=origin,delta_s=delta,delta_bounds_s=bounds)))
        truth=next(w for w in read(path)['windows'] if w['window']=='validation')['transitions']
        onsets=[r['time']-delta for r in data['events'] if r['color']==color.upper() and 2700<=r['time']<3300]
        evaluation[color]=dict(before=evaluate_bias(onsets,truth),after=evaluate_bias(onsets,truth,bias),
            unresolved_cycles=6-len(truth))
    save(OUT/'mapped_main_truth.json',dict(rows=mapped,clock_formula='JSON_ms = 1740632395000 + 1000*(video_PTS_s + delta_s)',
        delta_s=delta,conditional_delta_bounds_s=bounds,clock_validation_sha256=sha(clock_path),
        empirical_four_car_link=True,clock_support_video_pts_s=[899.5,3300.5],
        constant_rate_assumed=True,clock_drift_fitted=False,physical_exposure_accuracy_calibrated=False,
        other_heads_independently_observed=False,original_video_labels_changed=False))
    save(OUT/'clock_aware_calibration.json',dict(candidates=candidates,source_prediction_sha256=sha(pred_path),
        previous_calibration_sha256=sha(OLD/'conditional_onset_calibration/frozen_candidates.json'),
        clock_delta_s=delta,clock_bounds_semantics=clock['bounds_semantics'],
        calibration_video_pts_s=[900,1500],validation_video_pts_s=[2700,3300],
        validation_previously_inspected=True,independent_new_holdout_claimed=False,
        complete_phase_plan_calibrated=False,observed_lamps_not_replaced=True,production_enabled=False))
    save(OUT/'evaluation.json',dict(results=evaluation,clock_support='four fresh moving cars; fixed H and delta; no phase-based alignment',
        clock_uncertainty_in_scalar_metrics=False,conditional_envelope_in_mapped_truth=True,
        physical_precision_claimed=False,unpaired_red='unresolved video cycle, not an established false positive'))
    events=[];timeline=[]
    for r in data['events']:
        b=candidates[r['color'].lower()]['bias_s']
        event=dict(time=r['time']-delta,color=r['color'],bias=b)
        assert abs((event['time']-event['bias'])-(r['time']-r['bias']))<1e-9
        events.append(event)
        timeline.append(dict(color=r['color'],original_json_timestamp_ms=origin+1000*r['time'],
            calibrated_json_timestamp_ms=origin+1000*(r['time']-b),
            video_pts_s=event['time']-b))
    payload=dict(data,events=events,model_range_s=[t-delta for t in data['model_range_s']],
        empirical_clock_link=True,clock_verified=False,clock_delta_s=delta,conditional_delta_bounds_s=bounds,
        clock_verified_semantics='absolute device clock accuracy not certified; empirical correspondence supported by four cars',
        calibration_biases=candidates)
    save(OUT/'comparison_data.json',payload)
    save(OUT/'calibrated_N_main_onsets.json',dict(events=timeline,site='sverdlovsky',approach='N',section='main',
        source='model estimates, calibrated to visible main only',production_enabled=False,
        scope='first JSON/hour, not all heads or whole recording',yellow_and_blinking_evaluated=False))
    page=(OLD/'visible_head_comparison.html').read_text(encoding='utf8')
    page,n=re.subn(r'const DATA=.*?;const video=',lambda _: 'const DATA='+json.dumps(payload,ensure_ascii=False).replace('</','<\\/')+';const video=',page,flags=re.S);assert n==1
    warning='Сверка часов по четырём новым движущимся машинам: JSON = начало камеры + PTS + 1,254 с. Геометрия и сдвиг не подбирались повторно. Допустимый диапазон 1,127–1,369 с условен относительно геометрии и допуска 50 пикселей; это не сертификат точности аппаратных часов. Назначение видимой головы N подтверждено пользователем. Поправка оценивает только основной сигнал; в основной алгоритм она пока не включена.'
    page,n=re.subn(r'<p class="warning">.*?</p>',lambda _: '<p class="warning">'+warning+'</p>',page,count=1,flags=re.S);assert n==1
    page=page.replace('Условная поправка','Поправка N основного')
    page=page.replace('Зелёный раньше на 3.898 с, красный — на 4.939 с.','Зелёный раньше на 2.644 с, красный — на 3.685 с.')
    page=page.replace(' (привязка предполагается)',' (часы камеры)')
    page=page.replace('Синхронизация часов остаётся предположением.','Привязка часов проверена по четырём машинам; ограничения — в отчёте.')
    page=page.replace('href="sverdlovsky/','href="../direct_video_truth_20261018/sverdlovsky/')
    with (OUT/'visible_head_comparison.html').open('x',encoding='utf8',newline='\n') as f:f.write(page)
    rows=''
    for color,metrics in evaluation.items():
        a,b=metrics['before'],metrics['after']
        rows+=f"<tr><td>{color}</td><td>{b['truth_onsets']}</td><td>{a['mean_absolute_midpoint_error_s']:.3f} → {b['mean_absolute_midpoint_error_s']:.3f} с</td><td>{b['mean_distance_to_truth_bracket_s']:.3f} с</td><td>{b['within_0_5s_of_bracket']}/{b['truth_onsets']}</td></tr>"
    report='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Сверка видео и JSON</title><style>body{font:17px/1.55 system-ui;background:#111720;color:#edf4ff;max-width:1100px;margin:30px auto;padding:0 16px}a{color:#9ccdff}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #586a84;padding:9px}.scroll{overflow:auto}img{max-width:100%}.note{background:#302917;padding:16px}</style><h1>Свердловский: часы и задержка разделены</h1><p>Независимая проверка четырёх новых машин на 15-й, 30-й, 45-й и 55-й минутах поддержала прежний сдвиг JSON относительно PTS: +1,253838 с. Ни геометрия, ни сдвиг не переобучались; состояния светофора не использовались для синхронизации.</p><p>Максимальные расхождения по машинам: 10,6 / 13,3 / 33,9 / 18,6 пикселя при заранее установленном допуске 50. Нулевой сдвиг не прошёл. Общий допустимый диапазон сдвига 1,127–1,369 с условен относительно фиксированной геометрии, ручного выбора точки автомобиля и его личности. Погрешность аппаратных часов и экспозиции не измерена.</p><p><a href="visible_head_comparison.html">Открыть видео с прогнозом до/после</a>. Выберите исходный MP4 Свердловского. Он остаётся на компьютере.</p><h2>Калибровка видимого основного N</h2><p>Поправка времени JSON: зелёный −2,644 с, красный −3,685 с. Прежние 3,898 /4,939 с включали сдвиг часов. Правило и значения настройки взяты с первого участка 900–1500 с и переведены в подтверждаемую шкалу JSON. Второй участок 2700–3300 с уже исследовался раньше; это повторная оценка прежней временной проверки, а не новый независимый тест.</p><div class="scroll"><table><tr><th>Включение</th><th>Метки</th><th>MAE середины до → после</th><th>Средняя дистанция до интервала после</th><th>В пределах 0,5 с от интервала</th></tr>'''+rows+'''</table></div><p class="note">Эти метрики рассчитаны при фиксированном сдвиге 1,253838 с. Неопределённость синхронизации записана отдельно в mapped_main_truth.json, а не скрыта внутри малых средних ошибок. Один зелёный интервал имеет ширину 2,467 с из-за мерцания LED; его середина не является известным моментом. Один лишний относительно разметки прогноз красного приходится на неразрешённый видеоцикл. Другие головы, стрелка, жёлтый и мигающий режим этим не проверены.</p><h2>Уточнения пользователя</h2><p>Свердловский: стрелка N→E и в видео, и в JSON; прежнее описание поворота пользователь исправил. Глобальная перестановка E/W из этого не следует. Энтузиастов: видимая голова обслуживает E; основные сигналы E/W совпадают по подтверждению пользователя. Это не два независимых видеонаблюдения.</p><h2>Энтузиастов: что ещё мешает</h2><p>Видео-only метки сохранены, но независимое совмещение машин и времени с JSON не установлено. Единственная дополнительная попытка пространственного совмещения не прошла проверку: максимум ошибки133,5 пикселя и пересечение проектного горизонта с дорогой. Неуспешная модель сохранена, её часы не приняты; точность в секундах по этой паре пока не посчитана.</p><p>Для продолжения полезна ручная проверка конкретных пар машина/track ID на кадрах или документированное преобразование координат поставщика. Дополнительные файлы не запрашиваются: используем переданные материалы. Основной алгоритм и три прежних профиля не менялись: отдельно экспортированы видеометки в шкале JSON и исправленные оценки основного N.</p><p><a href="mapped_main_truth.json">22 метки в шкале JSON с интервалами</a> · <a href="calibrated_N_main_onsets.json">Калиброванные оценки N</a> · <a href="clock_aware_calibration.json">Фиксированные поправки</a> · <a href="evaluation.json">Контрольные пары и метрики</a></p><details><summary>Независимые кадры машин</summary><img src="sverdlovsky_motion/native_motion_sheet.png"><img src="sverdlovsky_late_control/motion_sheet.png"></details><p><a href="../direct_video_truth_20261018/report.html">Исходные даты, все 9 JSON и предыдущий отчёт</a></p></html>'''
    with (OUT/'report.html').open('x',encoding='utf8',newline='\n') as f:f.write(report)
    print(json.dumps(dict(delta_s=delta,candidates=candidates,metrics={c:{k:v for k,v in m['after'].items() if k!='pairs'} for c,m in evaluation.items()})),flush=True)


if __name__=='__main__':main()
