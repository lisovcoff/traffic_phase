"""Preserve reviewed waiting/turn evidence without accepting a new clock."""
import json
from scripts.cardinal_clock_link import ROOT,save,read,sha
from scripts.inspect_enthusiasts_turn_clock import OUT


def main():
    frames=read(OUT/'frames.json')['rows']
    for row in frames:assert sha(OUT/row['file'])==row['sha256']
    record=read(OUT/'source_track7.json')['record']
    samples=[dict(source_ms=d['millis'],old_provisional_relative_s=(d['millis']-1740300628994)/1000,
        x=d['centroid_x'],y=d['centroid_y'],reported_speed=d.get('speed')) for d in record['detections'][::5]]
    result=dict(status='USER_MANEUVER_SUPPORTED_CLOCK_NOT_ACCEPTED',
        video_car_user_confirmed_movement='E->_E',
        waiting_conflict_flow_user='W->_E',
        stop_is_not_red_evidence=True,
        observed_video_resumption_bracket_s=[29.,30.],
        visual_evidence='Silver car at left of crop remains near its waiting position at28/29s, clearly moving through turn at30/31/32/33s and exits lower-right at34/35s.',
        no_second_human_endpoint_review=True,
        source_speed_observation='Raw ID7 reports near-zero speed around old provisional t20..25s and increasing speed around26..29s. The old relative origin is hypothetical, not a calibrated camera clock.',
        samples=samples,
        interpretation='Consistent maneuver and waiting pattern support the candidate association; one turn and motion-dependent reported speed do not establish a uniform camera/detection clock.',
        movement_threshold_posthoc=True,
        clock_fit_calls=0,geometry_fit_calls=0,phase_fit_calls=0,
        accepted_clock_transform=None,paired_lamp_accuracy_computed=False,
        next_needed='At least another independently identified car/motion sequence at a distant source/video time, plus coordinate/preprocessing check before accepting a clock or drift model.')
    save(OUT/'review_result.json',result)
    table=''.join(f'<tr><td>{r["old_provisional_relative_s"]:.3f}</td><td>{r["source_ms"]}</td><td>{r["reported_speed"]}</td></tr>' for r in samples)
    page='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Энтузиастов — ожидание разворота</title><style>body{font:17px/1.5 system-ui;background:#111720;color:#edf4ff;max-width:1150px;margin:25px auto;padding:0 14px}a{color:#9ccdff}img{max-width:100%;height:auto}td,th{border:1px solid #66778c;padding:6px}table{border-collapse:collapse;font-size:13px}.scroll{overflow:auto}</style><h1>Энтузиастов: E→_E с ожиданием потока</h1><p>Пользователь подтвердил: машина в розовой рамке выполняет E→_E и ждёт поток W→_E. Поэтому её остановка не доказывает красный свет на E. Это наблюдение сохранено отдельно от назначения видимой головы E.</p><p>На новых соседних кадрах серебристая машина слева в вырезке сохраняет положение ожидания на PTS28/29с; на30–33с уже заметно завершает манёвр; на34–35с уезжает вниз вправо. Консервативная граница начала заметного движения29–30с не является известным моментом отпускания тормоза. Второй человек границу ещё не проверял.</p><img src="motion_sheet.png"><p>В JSON у кандидата7 тот же E→_E и характерное ожидание, затем ускорение. Однако совпадения одного манёвра недостаточно для принятия сдвига и скорости часов. Первоначальное начало относительной шкалы JSON было гипотезой; малые ошибки обучения геометрии уже не прошли независимый контроль. Новая подгонка не запускалась.</p><h2>Исходная скорость ID7</h2><p>Первая колонка — старая условная шкала относительно1740300628994мс, это не установленный PTS видео. Единицы и сглаживание скорости здесь не переинтерпретируются. Числа не используются как точное время физической остановки/старта.</p><div class="scroll"><table><tr><th>Условное время, с</th><th>detections.millis</th><th>Переданное speed</th></tr>'''+table+'''</table></div><p>Следующий независимый контроль — другая однозначно сопоставленная машина в удалённой части видео/JSON, затем проверка постоянства временной шкалы. Ошибка светофорного алгоритма на Энтузиастов пока не вычислена; по светофорным циклам часы не подгонялись.</p><p><a href="review_result.json">Машиночитаемый результат</a> · <a href="../cardinal_clock_link_20261018/enthusiasts_identity_review/index.html">Первоначальные кандидаты</a> · <a href="../cardinal_clock_link_20261018/visible_head_comparison.html">Готовая сверка Свердловского</a></p></html>'''
    with (OUT/'report.html').open('x',encoding='utf8',newline='\n') as f:f.write(page)
    files={p.relative_to(OUT).as_posix():dict(bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(OUT.rglob('*')) if p.is_file()}
    save(OUT/'manifest.json',dict(files=files,production_changed=False,clock_transform_accepted=False,
        source='user maneuver confirmation plus9 native video crops; no old evidence overwritten'))
    print('PASS: user replies, motion evidence and failed clock acceptance preserved')


if __name__=='__main__':main()
