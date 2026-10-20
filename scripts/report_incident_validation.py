"""Build a standalone, explicitly scoped comparison from immutable receipts."""
import json
from pathlib import Path
from scripts.check_incident_counterfactual import OUT,RUNTIME,GreenStretch
from app.core.intersection_project import read_json,digest
from scripts.corpus_validation import save


def main():
    p=read_json(OUT/'protocol.json');warp=GreenStretch(**p['warp']);truth=read_json(p['truth_path'])['rows']
    data={};results={}
    for name in ('baseline','extended'):
        result=read_json(OUT/(name+'_result.json'));results[name]=result
        lo=1740634500000;hi=1740634800000+(12000 if name=='extended' else 0)
        data[name]=[dict(t=r['timestamp_ms'],p=r['heads']['N']['main']['state'])
                    for r in map(json.loads,(RUNTIME/(name+'_issuance.jsonl')).open()) if lo<=r['timestamp_ms']<=hi]
        spans=[]
        for i in range(3):
            for a,b in [('GREEN','YELLOW'),('YELLOW','RED')]:
                x=next(r for r in truth if r['index']==i and r['color']==a)
                y=next(r for r in truth if r['index']==i and r['color']==b)
                start=x['clock_mapping']['json_bracket_fixed_clock_ms'][1]
                end=y['clock_mapping']['json_bracket_fixed_clock_ms'][0]
                spans.append(dict(a=warp.timestamp(start) if name=='extended' else start,
                                  b=warp.timestamp(end) if name=='extended' else end,c=a))
        results[name]['spans']=spans
    synthetic=[read_json(f) for f in sorted((OUT/'synthetic_paired').glob('*/result.json'))]
    payload=json.dumps(dict(data=data,results=results,synthetic=synthetic),ensure_ascii=False).replace('<','\\u003c')
    template='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Traffic Phase — продление и блокировка</title>
<style>body{font:16px system-ui;background:#10151d;color:#e4eaf2;max-width:1100px;margin:30px auto;padding:0 20px}a{color:#81baff}h1{font-size:27px}p{line-height:1.5}button,input{font:inherit}button{padding:9px 14px;background:#23334a;color:white;border:1px solid #52647e;border-radius:7px;cursor:pointer}canvas{width:100%;height:210px;background:#172231;border-radius:8px}table{width:100%;border-collapse:collapse}td,th{padding:9px;text-align:left;border-bottom:1px solid #35445a}small{color:#bbc7d7}.card{padding:18px;border:1px solid #35445a;border-radius:10px;margin:18px 0}#cursor{font-weight:600}.warning{color:#ffd48c}input{width:100%}</style>
<style>table{display:block;overflow-x:auto}</style>
<h1>Продление зелёного: проверка на копии реального JSON</h1>
<p class="warning">95% для проекта не подтверждены. Производственный алгоритм остаётся v7. Здесь показаны измерения и найденный отказ.</p>
<p>Модель: 11–19 февраля. Вход: один JSON Свердловского 27 февраля. В копии один зелёный N продлён на 12 с; часы и скорости машин изменены согласованно. Сигналы, видео и тип «пожарная машина» алгоритму не передавались. Это контролируемый сценарий, а не реальный проезд спецтранспорта.</p>
<div class="card"><button id="base">Исходный JSON</button> <button id="extra">Зелёный +12 с</button><p id="metric"></p><canvas id="plot" aria-label="Сравнение N основной: эталон и онлайн"></canvas><input id="seek" aria-label="Время" type="range" min="0" step="1"><p id="cursor"></p><a id="player" target="_blank">Открыть полный плеер с машинами</a><p><small>Верхняя строка — подтверждённые интервалы GREEN/YELLOW видимой N; серая область не размечена. Нижняя — оценка онлайн. Красный и красно-жёлтый здесь не включены в процент: точные границы RED_YELLOW не размечены. Мигающий зелёный считается GREEN.</small></p></div>
<p><a href="../../.web_runtime/incident_validation_20261020/sverdlovsky_feb27_extended_green.zip">Изменённый ZIP — один JSON, около 80 МБ</a> · <a href="../../.web_runtime/incident_validation_20261020/extended.jsonl">Причинный JSONL для онлайн-повтора</a> · <a href="../../docs/INCIDENT_VALIDATION_RESULTS_20261020.md">Подробный отчёт</a></p>
<p>До изменения ответы совпали на 2178 пакетах. Оба потока обработаны причинно, будущий zone_out исключён. База: 3648 пакетов; продление: 3660.</p>
<h2>Новые физические симуляции</h2><p>Шесть получасовых сценариев, фиксированные ранее обученные модели. Блокировка только N на 35 м после стоп-линии: очередь растёт назад; лампы продолжают работать по прежнему плану. Все основные головы, все цвета, UNKNOWN считается ошибкой. Это симуляция, не дорожная ground truth.</p><table><thead><tr><th>K</th><th>Сценарий</th><th>Верно / секунд</th><th>Точность</th><th>N зелёный в окне блокировки</th></tr></thead><tbody id="sim"></tbody></table>
<h2>Видео Энтузиастов</h2><p>Просмотрены обзорные кадры 0–18000 с и участок 5100–5700 с. Часы видео начинаются с 05.10.2024 11:59:58. Надёжная связь PTS с millis архива пока не установлена; совпадение циклов для подгонки часов не использовалось. Посекундную точность этого архива пока считать нельзя. Видимая E/W не подтверждает остальные головы и другие даты.</p>
<p><a href="../../.web_runtime/incident_validation_20261020/video/full_video_context/contact_0.jpg">Видео 0–4800 с</a> · <a href="../../.web_runtime/incident_validation_20261020/video/full_video_context/contact_1.jpg">5400–10200 с</a> · <a href="../../.web_runtime/incident_validation_20261020/video/full_video_context/contact_2.jpg">10800–15600 с</a> · <a href="../../.web_runtime/incident_validation_20261020/video/full_video_context/contact_3.jpg">16200–18000 с</a></p>
<script>const report=__DATA__;let active='extended';const $=id=>document.getElementById(id),colors={GREEN:'#42d692',YELLOW:'#ffcb4a',RED:'#f16570',RED_YELLOW:'#e99a4f',UNKNOWN:'#6e8098'};const fmt=new Intl.DateTimeFormat('ru-RU',{timeZone:'Asia/Yekaterinburg',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
function draw(){const rows=report.data[active],r=report.results[active],canvas=$('plot'),ratio=devicePixelRatio||1,w=canvas.clientWidth;canvas.width=w*ratio;canvas.height=210*ratio;const c=canvas.getContext('2d');c.scale(ratio,ratio);let left=84,width=w-left-14,start=rows[0].t,end=rows.at(-1).t+1000;const x=t=>left+(t-start)/(end-start)*width;c.fillStyle='#172231';c.fillRect(0,0,w,210);c.font='14px system-ui';c.fillStyle='#e4eaf2';c.fillText('Эталон',8,60);c.fillText('Онлайн',8,125);c.fillStyle='#3a4758';c.fillRect(left,36,width,34);for(const s of r.spans){c.fillStyle=colors[s.c];c.fillRect(x(s.a),36,x(s.b)-x(s.a),34)}for(const row of rows){c.fillStyle=colors[row.p];c.fillRect(x(row.t),100,Math.max(1,width/rows.length),34)}c.fillStyle='#c3cede';for(let n=0;n<4;n++){let t=start+(end-start)*n/3;c.fillText(fmt.format(t),Math.min(w-70,x(t)),166)}const row=rows[Number($('seek').value)||0];c.strokeStyle='white';c.beginPath();c.moveTo(x(row.t),20);c.lineTo(x(row.t),144);c.stroke();const truth=r.spans.find(s=>s.a<row.t&&row.t<s.b);$('cursor').textContent=fmt.format(row.t)+' · эталон: '+(truth?.c||'не размечен')+' · онлайн: '+row.p;}
function select(name){active=name;let r=report.results[name],s=r.counts;$('metric').textContent=(name==='extended'?'С продлением':'Исходный')+': '+s.correct+'/'+s.total+' размеченных секунд ('+(100*r.accuracy_on_labelled_green_yellow).toFixed(1)+'%).'+(name==='extended'?' Добавленные 12 с зелёного: '+s.added_green_correct+'/12.':'');$('seek').max=report.data[name].length-1;$('seek').value=80;$('player').href=r.url;draw();}
for(const r of report.synthetic){const s=r.counts,tr=document.createElement('tr');for(const value of [r.k,{normal:'Обычный',blocked_N:'Блокировка N',extended_12s:'Продление +12 с'}[r.case],s.correct+'/'+s.total,(100*r.accuracy).toFixed(2)+'%',s.incident_N_green_correct+'/'+s.incident_N_green_total]){let td=document.createElement('td');td.textContent=value;tr.append(td)}$('sim').append(tr)}$('base').onclick=()=>select('baseline');$('extra').onclick=()=>select('extended');$('seek').oninput=draw;addEventListener('resize',draw);select('extended');</script></html>'''
    with (OUT/'report_paired.html').open('x',encoding='utf8',newline='\n') as f:f.write(template.replace('__DATA__',payload))
    save(OUT/'diagnostic_disposition_paired.json',dict(
        production_changes=False,production_version='causal-intersection-v7',
        first_diagnostic_invalid='v1 replay re-aggregated events and changed floating point order; superseded, retained',
        accepted_replay_check='baseline_forecast_diagnostic_v2.json:3660 exact head/confidence matches',
        rejected_candidates=['posterior_red','flow_guard','coupled_flow'],
        reasons=['improve some extended greens but retain false yellow/green reversals or miss yellow',
                 'not an accepted universal accuracy improvement; none deployed'],
        video_review=dict(overview_frames=31,detail_frames=9,confirmed_bus_incident=False,
                          clock_link_accepted=False,Gemini_contacted=False,
                          Gemini_unavailable_reason='Computer Use native pipe unavailable')))
    for name in ('full_video_context','emergency_context'):
        target=OUT/(name+'_frames.json');value=read_json(RUNTIME/'video'/name/'frames.json')
        if target.exists(): assert read_json(target)==value
        else: save(target,value)
    print(OUT/'report_paired.html')


if __name__=='__main__':main()
