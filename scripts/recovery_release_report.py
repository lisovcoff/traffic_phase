"""Auditable before/after summary and offline interactive phase-history report."""
from collections import Counter
import gzip
from html import escape
import json
from pathlib import Path

from scripts.corpus_validation import ROOT, prepare_worker_environment, save
prepare_worker_environment()
from scripts.accuracy_recovery import OUT, OLD, RUNTIME
from scripts.verify_recovery_release import MODE, prediction_path


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def zipped(path):
    with gzip.open(path, 'rt', encoding='utf8') as stream:
        return json.load(stream)


def aggregate(scores):
    duration = sum(s['evaluated_s'] for s in scores)
    heads = [h for s in scores for h in s['production_main_heads']['heads'].values()]
    head_seconds = sum(h['evaluated_s'] for h in heads)
    matched = sum(s['transition_metrics']['2']['matched'] for s in scores)
    expected = sum(s['transition_metrics']['2']['expected'] for s in scores)
    predicted = sum(s['transition_metrics']['2']['predicted'] for s in scores)
    return dict(cases=len(scores), k_correct=sum(s['k_correct'] for s in scores), hours=duration/3600,
        logical_state_error_fraction=sum(s['evaluated_s']*s['phase_state_error_fraction'] for s in scores)/duration,
        logical_coverage_fraction=sum(s['evaluated_s']*s['coverage_fraction'] for s in scores)/duration,
        main_head_color_error_fraction=sum(h['evaluated_s']*h['error_fraction'] for h in heads)/head_seconds,
        main_head_color_coverage_fraction=sum(h['evaluated_s']*h['coverage_fraction'] for h in heads)/head_seconds,
        mean_case_dominant_movement_accuracy=sum(s['movement_assignment_accuracy'] for s in scores)/len(scores),
        mean_case_complete_movement_membership_accuracy=sum(s['complete_movement_membership_accuracy'] for s in scores)/len(scores),
        transitions_at_2s=dict(matched=matched, expected=expected, predicted=predicted,
                               recall=matched/expected, precision=matched/predicted))


def aligned(result, truth, score):
    base=(result['analysis_base_timestamp_ms']-truth['base_ms'])/1000
    mapping=score['permutation_alignment']
    return [[a+base,b+base,mapping.get(str(int(z)),-1)] for a,b,z in result['schedule']['raw_hsmm_segments']]


def manual_rows():
    from app.core.offline_benchmark import evaluate_prediction, validate_annotation
    from app.core.manual_delay_evaluation import evaluate_reaction_bound
    jobs = read(ROOT/'evidence/all_archives_synthetic_20261019/inventory.json')['jobs']
    rows=[]
    for source in ('17_2025_2_19_10','19_2025_2_24_16','6_2025_2_14_20'):
        job=next(j for j in jobs if j['source_name']==source+'.json')
        original=read(ROOT/'benchmarks/learned_profile_20261018/heldout'/(source+'_v9.json'))
        annotation=dict(start_ms=original['start_ms'],marks=[dict(timestamp_ms=m['timestamp_ms'],kind=m['kind']) for m in original['marks']])
        current=zipped(prediction_path('real_'+job['id']))
        baseline=zipped(OLD/(job['id']+'_predictions.json.gz'))[0]['automatic']['result']
        modes={}
        for name,result in [('baseline',baseline),('current',current)]:
            modes[name]=dict(strict=evaluate_prediction(result,validate_annotation(annotation)),
                             reaction_0_3s=evaluate_reaction_bound(result,annotation))
        rows.append(dict(source=source, modes=modes))
    return rows


def main():
    development=read(OUT/'development_suite.json')['cases']
    reserved=read(OUT/'holdout/suite.json')['cases']
    inventory=read(ROOT/'evidence/all_archives_synthetic_20261019/inventory.json')
    suites={};cases=[]
    for name,configs in [('development',development),('reserved',reserved)]:
        before=[];after=[]
        for config in configs:
            key=config['id'];fresh=name=='reserved'
            parent=RUNTIME/'holdout'/key if fresh else OLD/'synthetic'/key
            baseline_receipt=read(OUT/'holdout/results'/(key+'.json') if fresh else
                ROOT/'evidence/all_archives_synthetic_20261019/synthetic/evaluation_v2'/(key+'.json'))
            baseline_score=baseline_receipt['scores'][0]
            current_receipt=read(OUT/'pilot'/MODE/(key+'.json'));assert current_receipt['status']=='predicted'
            current_score=current_receipt['score'];before.append(baseline_score);after.append(current_score)
            truth=zipped(parent/'truth.json.gz')
            baseline=zipped(parent/'predictions.json.gz')[0]['automatic']['result']
            current=zipped(prediction_path(key))
            cases.append(dict(id=key, suite=name, config=config, counts=baseline_receipt['counts'],
                baseline_score=baseline_score, current_score=current_score,
                truth=[[r['start_s'],r['end_s'],r['phase']] for r in truth['signal_plan']],
                baseline=aligned(baseline,truth,baseline_score), current=aligned(current,truth,current_score),
                input_zip=str((parent/'input.zip').relative_to(ROOT)).replace('\\','/')))
        suites[name]=dict(baseline=aggregate(before), current=aggregate(after))
    real=[];initial_failures=[]
    for job in inventory['jobs']:
        key='real_'+job['id'];path=OUT/'pilot'/MODE/(key+'.json');row=read(path)
        if row['status']!='predicted':
            initial_failures.append(dict(key=key,error=row['error'],receipt=str(path.relative_to(ROOT))))
            row=read(OUT/'pilot'/(MODE+'_retry')/(key+'.json'))
        assert row['status']=='predicted'
        parity=read(OUT/'production_parity'/(key+'.json'));assert parity['status']=='PASS'
        old=read(ROOT/'evidence/all_archives_synthetic_20261019/results'/(job['id']+'.json'))
        baseline_k=old['predictions'][0]['automatic']['phase_count']
        audit=read(OUT/'zero_speed_audit_v3'/(job['id']+'.json'))
        real.append(dict(id=job['id'],source_name=job['source_name'],path=job['path'],member=job['member'],
            baseline_k=baseline_k,current_k=row['k'],period_s=row['period'],sha256=old['sha256'],
            bytes=old['bytes_read'],sessions=parity['source_sessions'],exact_zero_speed=audit['exact_zero_speed_present'],
            execution='PASS', physical_accuracy='UNKNOWN_WITHOUT_INDEPENDENT_LAMP_TRUTH'))
    parities=[read(p) for p in (OUT/'production_parity').glob('*.json')]
    assert sum(r['status']=='PASS' and not r.get('cold') for r in parities)==315
    summary=dict(schema='trajectory-recovery-release-v1', candidate=read(OUT/'candidate_freeze_01.json'),
        suites=suites, cases=cases, real_sources=real, initial_failed_attempts=initial_failures,
        production_parity=dict(total=len(parities),statuses=dict(Counter(r['status'] for r in parities))),
        manual_development=manual_rows(), fresh_visible_N=read(OUT/'fresh_video_evaluation.json'),
        real_unique_sources=len({r['sha256'] for r in real}),
        limitations=['Reserved synthetic cases are new seeds of the same simulator, not unseen real intersections.',
            'Visible-lamp test is three cycles of N main from the same camera/day with a conditional car-based clock.',
            'Enthusiasts video/JSON clock unresolved; Chicherina video unavailable.',
            'Empty-flow controller phases and exact physical topology are not identifiable from arbitrary traffic alone.',
            'Local deviation acceptance 2D.1 remains FAIL/default-off; no universal maximum-accuracy claim.'])
    save(OUT/'release_summary.json',summary)
    write_report(summary)
    print(json.dumps(dict(suites=suites,real_sources=len(real),unique=summary['real_unique_sources'],
                          parity=summary['production_parity']),ensure_ascii=False),flush=True)


def percent(value):
    return f'{100*value:.2f}%'


def write_report(summary, filename='report_v2.html'):
    metrics=''
    for suite,label in [('development','72 сложных сценария · разработка'),('reserved','24 новых сценария · контроль')]:
        for mode,title in [('baseline','До'),('current','Сейчас')]:
            v=summary['suites'][suite][mode];t=v['transitions_at_2s']
            metrics+=f'<tr><td>{label}</td><td>{title}</td><td>{v["k_correct"]}/{v["cases"]}</td><td>{percent(v["logical_state_error_fraction"])}</td><td>{percent(v["main_head_color_error_fraction"])}</td><td>{t["matched"]}/{t["expected"]}</td><td>{t["matched"]}/{t["predicted"]}</td></tr>'
    manual=''
    for row in summary['manual_development']:
        for mode,title in [('baseline','До'),('current','Сейчас')]:
            v=row['modes'][mode];s=v['strict']['histories']['raw_hsmm_segments']['boundaries']['recall'];r=v['reaction_0_3s']
            manual+=f'<tr><td>{escape(row["source"])}</td><td>{title}</td><td>{s["matched_boundaries"]}/{s["truth_boundaries"]}</td><td>{s["predicted_boundaries"]}</td><td>{r["compatible_boundaries"]}/{r["truth_boundaries"]}</td></tr>'
    payload=json.dumps(summary,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    page='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Traffic Phase — проверенный алгоритм по траекториям</title>
<style>*{box-sizing:border-box}body{margin:0;background:#10151d;color:#edf2fa;font:16px/1.55 system-ui}main{max-width:1250px;margin:24px auto;padding:0 16px}h1{font-size:30px}h2{font-size:23px;margin-top:30px}a{color:#9ccaff}section{padding:18px;background:#18212d;border:1px solid #34465d;border-radius:12px;margin:18px 0}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #44566d;padding:9px;text-align:left}select,input,button{max-width:100%;padding:8px}input[type=range]{width:100%}canvas{width:100%;height:215px;background:#0a1018;border-radius:8px}.muted{color:#b5c6dc}.warning{border-left:4px solid #e9ad55;padding-left:14px}#caseInfo{overflow-wrap:anywhere}#sources td{overflow-wrap:anywhere}</style>
<main><h1>Traffic Phase: алгоритм подключён к приложению</h1>
<p>Рабочий вход — только траектории JSON/ZIP. Число фаз определяется автоматически, видео и ручные метки используются только при проверке.</p>
<p><a href="application_checks/lenina_sverdlovsky/viewer.html">Открыть Свердловский</a> · <a href="application_checks/lenina_entuziastov/viewer.html">Энтузиастов</a> · <a href="application_checks/chicherina_40let/viewer.html">Чичерина</a></p>
<p>Для нового анализа запустите START_WEB.cmd в audit_checkout и откройте <a href="http://127.0.0.1:8017/visualization">приложение</a>. Если оно уже работало, перезапустите сервер.</p>
<section><h2>Синтетика: до → сейчас</h2><p>72 прежних сценария /62 часа использованы для разработки. 24 новых сценария /9 часов зафиксированы до оценки. Полная история, включая непокрытые интервалы; ошибки не исключены из знаменателя.</p>
<div class="scroll"><table><tr><th>Набор</th><th>Версия</th><th>Верное K</th><th>Ошибка фаз</th><th>Ошибка цветов основных голов</th><th>Границы ±2с: найдено/истина</th><th>Границы ±2с: верно/прогноз</th></tr>__METRICS__</table></div>
<p class="muted">Цвета — автоматическая физическая проекция приложения, UNKNOWN считается ошибкой. Схема оборудования и жёлтый переход заданы симулятором. Новые случайные реализации того же симулятора не заменяют проверку на новых реальных перекрёстках.</p></section>
<section><h2>Посмотреть каждый сценарий</h2><label>Сценарий <select id="case"></select></label><p id="caseInfo"></p><canvas id="timeline" aria-label="Истинная история и прогнозы до и после"></canvas><label>Начало окна <input id="time" type="range" min="0" step="1" value="0"></label><p id="position"></p><p><a id="inputZip">Входной ZIP с траекториями, без истинных фаз</a></p><p class="muted">Одинаковые цвета обозначают одинаковую фазу после допустимого сопоставления анонимных меток. Серый — лишняя или неопределённая фаза. Длина окна300с.</p></section>
<section><h2>Новый фрагмент видимого светофора</h2><p>Свердловский, основной N, видео2100–2400с: до3/9 переключений в ±2с, сейчас8/9. Средняя абсолютная ошибка зелёного1,47с, жёлтого0,45с, красного0,46с. Одно включение зелёного осталось за пределами2с.</p>
<p>Алгоритм зафиксирован до просмотра результата на этих девяти переключениях. Это три цикла одной камеры/даты с условной привязкой часов по отдельным машинам. Нет поправки по имени архива или по видео в рабочем прогнозе.</p>
<p><a href="video_holdout/truth_sealed.json">Интервалы и исходные кадры</a> · <a href="fresh_video_evaluation.json">Все ошибки и пары переключений</a></p><details><summary>Кадры включений</summary><img style="max-width:100%" src="video_holdout/GREEN_native_sheet.png"><img style="max-width:100%" src="video_holdout/YELLOW_native_sheet.png"><img style="max-width:100%" src="video_holdout/RED_native_sheet.png"></details></section>
<section><h2>Ручные метки: повторная проверка разработки</h2><p>Эти данные уже использовались ранее и не являются новым независимым контролем. Реакция разметчика может запаздывать на0–3с.</p><div class="scroll"><table><tr><th>Запись</th><th>Версия</th><th>Строго ±2с</th><th>Прогнозов</th><th>Совместимо с реакцией0–3с</th></tr>__MANUAL__</table></div></section>
<section><h2>Все реальные источники</h2><p>219/219 источников,216 уникальных JSON,134,6млн детекций исходного корпуса. Получены результаты и подтверждено совпадение промышленного кода с зафиксированным вариантом. Это проверка выполнения, а не219 доказательств точности: независимой разметки ламп для большинства записей нет.</p>
<label>Поиск <input id="filter" placeholder="Имя JSON или номер"></label><p id="sourceCount"></p><div class="scroll"><table id="sources"><thead><tr><th>ID</th><th>JSON</th><th>K до</th><th>K сейчас</th><th>Период,с</th></tr></thead><tbody></tbody></table></div></section>
<section class="warning"><h2>Практические границы результата</h2><p>Из72 сложных сценариев остались четыре ошибки числа фаз: два редких потока и два сценария с почти отсутствующим потоком отдельной фазы. Скрытые фазы без машин, состав оборудования и фактические лампы нельзя однозначно восстановить из произвольных траекторий.</p><p>Для Свердловского задана подтверждённая схема: N/E с дополнительными секциями, W/S обычные. Цвета в приложении — оценка. Жёлтый3с и красно-жёлтый до2с являются настраиваемой моделью переходов. Продления/сокращения и смена режима не прошли отдельную приёмку2D.1. Связь часов Энтузиастов пока не установлена; видео Чичерина недоступно.</p><p>39 технически прерванных попыток при интеграции сохранены и повторены. Во всех315 случаях (219реальных+96синтетических) отдельно проверено совпадение производственного кода с замороженным кандидатом. Повторно использовались только численные fits и проверенные события; холодные HTTP-проверки трёх реальных ZIP выполнены отдельно.</p>
<p><a href="release_summary.json">Полная сводка</a> · <a href="candidate_freeze_01.json">Фиксация алгоритма</a> · <a href="cache_reuse_receipt.json">Проверка повторного использования событий</a></p></section></main>
<script id="data" type="application/json">__DATA__</script><script>
const DATA=JSON.parse(document.querySelector('#data').textContent),choice=document.querySelector('#case'),slider=document.querySelector('#time'),canvas=document.querySelector('#timeline');
const palette=['#4ad5b0','#789cff','#f2bb5f','#dd82d9','#79d4ec','#adb76a'];
for(const c of DATA.cases){let o=document.createElement('option');o.value=c.id;o.textContent=(c.suite==='reserved'?'Контроль · ':'Разработка · ')+c.id+(c.current_score.k_correct?'':' · ошибка K');choice.append(o);}
function draw(){const c=DATA.cases.find(c=>c.id===choice.value),a=+slider.value,b=Math.min(c.config.duration_s,a+300),ctx=canvas.getContext('2d');canvas.width=Math.round(canvas.clientWidth*devicePixelRatio);canvas.height=215*devicePixelRatio;ctx.scale(devicePixelRatio,devicePixelRatio);let w=canvas.clientWidth;ctx.font='13px system-ui';let left=Math.min(90,w*.27),right=w-12,scale=(right-left)/Math.max(1,b-a);[['Истина',c.truth],['До',c.baseline],['Сейчас',c.current]].forEach(([name,rows],i)=>{let y=30+i*57;ctx.fillStyle='#edf2fa';ctx.fillText(name,5,y+20);ctx.fillStyle='#263343';ctx.fillRect(left,y,right-left,30);for(const [s,e,z] of rows){let u=Math.max(a,s),v=Math.min(b,e);if(v<=u)continue;ctx.fillStyle=z<0?'#697587':palette[z%palette.length];ctx.fillRect(left+(u-a)*scale,y,(v-u)*scale,30);}});ctx.fillStyle='#b5c6dc';ctx.fillText(a+'с',left,208);ctx.textAlign='right';ctx.fillText(b+'с',right,208);ctx.textAlign='left';document.querySelector('#position').textContent=a+'–'+b+'с';}
function selected(){let c=DATA.cases.find(c=>c.id===choice.value);slider.max=Math.max(0,c.config.duration_s-300);slider.value=0;document.querySelector('#caseInfo').textContent='Истинное K='+c.config.k+'; до='+c.baseline_score.predicted_k+', сейчас='+c.current_score.predicted_k+'. Ошибка фаз: '+(100*c.baseline_score.phase_state_error_fraction).toFixed(2)+'% → '+(100*c.current_score.phase_state_error_fraction).toFixed(2)+'%. Машин: '+c.counts.tracks;document.querySelector('#inputZip').href='../../'+c.input_zip;draw();}
function sources(){let q=document.querySelector('#filter').value.toLowerCase(),rows=DATA.real_sources.filter(r=>(r.id+' '+r.source_name).toLowerCase().includes(q)),body=document.querySelector('#sources tbody');body.replaceChildren();for(const r of rows){let tr=document.createElement('tr');for(const value of [r.id,r.source_name,r.baseline_k,r.current_k,r.period_s.toFixed(3)]){let td=document.createElement('td');td.textContent=value;tr.append(td);}body.append(tr);}document.querySelector('#sourceCount').textContent=rows.length+' /219';}
choice.onchange=selected;slider.oninput=draw;window.onresize=draw;document.querySelector('#filter').oninput=sources;selected();sources();
</script></html>'''
    page=page.replace('39 технически прерванных',str(len(summary['initial_failed_attempts']))+' технически прерванных')
    page=page.replace('__METRICS__',metrics).replace('__MANUAL__',manual).replace('__DATA__',payload)
    with (OUT/filename).open('x',encoding='utf8',newline='\n') as stream:
        stream.write(page)


if __name__=='__main__':
    main()
