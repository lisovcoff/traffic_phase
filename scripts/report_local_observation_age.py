"""Review measured timing experiments without promoting failed candidates."""
import json
from collections import Counter
import re
from scripts.corpus_validation import ROOT,save
from app.core.intersection_project import read_json
from scripts.report_coherent_signals import TEMPLATE

OUT=ROOT/'evidence/local_observation_age_20261020'
LOCAL=ROOT/'.web_runtime/local_observation_age_20261020'


def main():
    old=read_json(ROOT/'evidence/coherent_signal_20261020/summary.json')
    variants={};rows_by_variant={}
    for name,folder in [('local','v1/synthetic'),('duration','v1/duration_v1/synthetic'),
                        ('conditioned','v1/conditioned_v1/synthetic'),('sensor','sensor_delay/synthetic')]:
        scores={n:Counter() for n in ('instant','history_10s')};rows=[]
        for f in sorted((OUT/folder).glob('k*_*.json')):
            r=read_json(f)
            if 'accuracy' not in r:continue
            rows.append(r)
            for n,c in r['counts'].items():scores[n].update(c)
        assert len(rows)==12,(name,len(rows))
        variants[name]={n:dict(counts=dict(c),accuracy=c['correct']/c['total']) for n,c in scores.items()}
        rows_by_variant[name]=rows
    fresh=[read_json(OUT/f'v1/fresh/k{k}_result.json') for k in range(2,6)]
    fresh_counts={name:Counter() for name in ('v7','local_instant','local_history_10s')}
    for r in fresh:
        for n,c in r['counts'].items():fresh_counts[n].update(c)
    data=dict(synthetic=[dict(k=r['k'],case=r['case'],accuracy={'v7_instant':r['previous']['v7_instant'],
        'joint_instant':r['accuracy']['instant'],'joint_history_10s':r['accuracy']['history_10s']}) for r in rows_by_variant['local']],
        aggregate={'v7_instant':old['synthetic_aggregate']['v7_instant'],
                   'joint_instant':variants['local']['instant'],'joint_history_10s':variants['local']['history_10s']},cases={})
    previous=ROOT/'evidence/accuracy_recovery_20261019/video_holdout/truth_sealed.json'
    truth=read_json(previous)['rows']
    from scripts.check_incident_counterfactual import GreenStretch
    warp=GreenStretch(**read_json(ROOT/'evidence/incident_validation_20261020/protocol.json')['warp'])
    for case in ('baseline','extended'):
        start=1740634505000;end=1740634782000+(12000 if case=='extended' else 0)
        files={'v7':ROOT/'.web_runtime/incident_validation_20261020'/(case+'_issuance.jsonl'),
               'joint':LOCAL/'sensor_delay/real'/(case+'_issuance.jsonl'),
               'profile':LOCAL/'v1/local_v1/real'/(case+'_issuance.jsonl')}
        series={};vehicles={}
        for name,path in files.items():
            direct=[];history=[]
            with path.open(encoding='utf8') as f:
                for line in f:
                    r=json.loads(line);now=r['timestamp_ms']
                    if not start<=now<=end+10000:continue
                    if now<=end:
                        direct.append([now,{a:h['main']['state'] for a,h in r['heads'].items()}])
                        if name=='joint':vehicles[str(now)]=[[v['x'],v['y'],v.get('angle',0)] for v in r['vehicles']]
                    for h in r.get('finalized_history',[]):
                        if start<=h['timestamp_ms']<=end:history.append([h['timestamp_ms'],{a:v['main']['state'] for a,v in h['heads'].items()}])
            if name!='profile':series[name]=direct
            if name!='v7':series['joint_history' if name=='joint' else 'path_history']=history
        spans=[]
        for i in range(3):
            for color,nxt in [('GREEN','YELLOW'),('YELLOW','RED')]:
                a=next(r for r in truth if r['color']==color and r['index']==i)['clock_mapping']['json_bracket_fixed_clock_ms'][1]
                b=next(r for r in truth if r['color']==nxt and r['index']==i)['clock_mapping']['json_bracket_fixed_clock_ms'][0]
                spans.append([warp.timestamp(a) if case=='extended' else a,warp.timestamp(b) if case=='extended' else b,color])
        measured=read_json(OUT/'sensor_delay/real'/(case+'_result.json'))
        data['cases'][case]=dict(start=start,end=end,series=series,vehicles=vehicles,truth=spans,
            metrics={n:measured[n] for n in ('counts','history_counts')},
            path_metrics=read_json(OUT/'v1/local_v1/real'/(case+'_result.json'))['history_counts'])
    def pct(n):return f'{100*n:.2f}%'
    table='<section><h2>Все проверенные варианты</h2><p>Те же12 потоков, без удаления неудачных результатов. Мгновенную оценку и историю через10с следует сравнивать отдельно.</p><table><tr><th>Вариант</th><th>Сейчас</th><th>История+10с</th></tr>'
    names={'local':'Возраст подтверждённых событий','duration':'Также более узкие длительности','conditioned':'Условие по наблюдаемому подходу','sensor':'Пересчёт по наблюдаемому началу старта'}
    for n,r in variants.items():table+=f'<tr><td>{names[n]}</td><td>{pct(r["instant"]["accuracy"])}</td><td>{pct(r["history_10s"]["accuracy"])}</td></tr>'
    table+='</table><h2>Четыре новых контроля после выбора local_v1</h2><p>Код и выбор варианта зафиксированы до просмотра этих результатов. Ниже все4 случая, включая слабый K3. После измерения это тоже становится известным материалом разработки.</p><table><tr><th>K / сценарий</th><th>v7</th><th>Сейчас</th><th>История+10с</th></tr>'
    for r in fresh:
        a=r['accuracy'];table+=f'<tr><td>{r["case"]["k"]} / {r["case"]["scenario"]}</td><td>{pct(a["v7"])}</td><td>{pct(a["local_instant"])}</td><td>{pct(a["local_history_10s"])}</td></tr>'
    table+='</table><p>'+', '.join(n+': '+pct(c['correct']/c['total']) for n,c in fresh_counts.items())+'</p></section>'
    html=TEMPLATE.replace('__DATA__',json.dumps(data,separators=(',',':')).replace('</','<\\/'))
    html=html.replace('Единая модель цветов и переменной длительности','Задержки наблюдений: результаты проверки')
    note='<p class="note"><strong>Приёмка не пройдена. В приложении остаётся v7.</strong><br>Обучение подтверждённых событий улучшило синтетическую историю, но ухудшило реальные цвета. Пересчёт по наблюдаемому старту сохранил12/12 добавленных секунд зелёного, но ухудшил K2. Ни один вариант не включён в приложение.</p>'
    html=re.sub(r'<p class="note">.*?</p>',lambda m:note,html,count=1,flags=re.S)
    html=html.replace("joint:'Единая сейчас'","joint:'По времени старта: сейчас'")
    html=html.replace("joint_history:'Единая: история +10с'","joint_history:'По времени старта: история +10с'")
    html=html.replace("path_history:'Путь: история +10с'","path_history:'Обученные события: история +10с'")
    html=html.replace("['Единая сейчас',active.metrics.counts]","['По времени старта: сейчас',active.metrics.counts]")
    html=html.replace("['Единая: история +10с',active.metrics.history_counts]","['По времени старта: история +10с',active.metrics.history_counts]")
    html=html.replace("['Путь: история +10с',active.path_metrics]","['Обученные события: история +10с',active.path_metrics]")
    html=html.replace("joint_instant:'Единая сейчас'","joint_instant:'Обученные события: сейчас'")
    html=html.replace("joint_history_10s:'Единая: история +10с'","joint_history_10s:'Обученные события: история +10с'")
    html=html.replace('<th>Единая сейчас</th>','<th>Обученные события: сейчас</th>').replace('<th>История +10с</th>','<th>Обученные события: история+10с</th>')
    html=html.replace('Новaя модель','Новая модель').replace('Новые парные физические сценарии','Обученные события:12 прежних парных сценариев')
    html=html.replace('12 потоков по30 минут:','12 известных потоков по30 минут:')
    html=html.replace('<section><h2>ДТП на Энтузиастов',table+'<section><h2>ДТП на Энтузиастов')
    html=html.replace('href="video_link/','href="../coherent_signal_20261020/video_link/')
    html=html.replace('href="v5/protocol.json"','href="sensor_delay/real/protocol.json"').replace('href="v5/synthetic/protocol.json"','href="v1/synthetic/protocol.json"')
    html=html.replace('<section><h2>Реальный JSON','<p>Реальные интервалы уже раскрыты при разработке; привязка часов условная. Это не новое независимое подтверждение95% точности. Кадры/метки видео не поступали в обучение или онлайн-фильтр.</p><section><h2>Реальный JSON')
    with (OUT/'comparison.html').open('x',encoding='utf8') as f:f.write(html)
    summary=dict(status='FAIL_NO_PRODUCTION_PROMOTION',production='v7',variants=variants,
        fresh={n:dict(counts=dict(c),accuracy=c['correct']/c['total']) for n,c in fresh_counts.items()},
        real_sensor={c:read_json(OUT/'sensor_delay/real'/(c+'_result.json')) for c in ('baseline','extended')},
        scope='logical phase timing/confirmation experiments; conditional known video clock; physical reaction delay not identified')
    save(OUT/'summary.json',summary);print('REPORT',json.dumps({n:dict(instant=r['instant']['accuracy'],history=r['history_10s']['accuracy']) for n,r in variants.items()}),flush=True)


if __name__=='__main__':main()
