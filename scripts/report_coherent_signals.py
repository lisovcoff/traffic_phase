"""Standalone review of measured joint-state candidates; never a production player."""
import json
from collections import Counter
from pathlib import Path
import shutil
from scripts.corpus_validation import ROOT,save
from app.core.intersection_project import read_json,digest

OUT=ROOT/'evidence/coherent_signal_20261020'
LOCAL=ROOT/'.web_runtime/coherent_signal_20261020'


def main():
    results=[];totals={n:Counter() for n in ('v7_instant','joint_instant','joint_history_10s')}
    for path in sorted((OUT/'v5/synthetic').glob('k*/result.json')):
        row=read_json(path);results.append(row)
        for n,c in row['counts'].items():totals[n].update(c)
    assert len(results)==12
    aggregate={n:dict(counts=dict(c),accuracy=c['correct']/c['total']) for n,c in totals.items()}
    data=dict(synthetic=[dict(k=r['k'],case=r['case'],accuracy=r['accuracy']) for r in results],
              aggregate=aggregate,cases={},production='v7',acceptance='FAIL_NO_PROMOTION')
    truth=read_json(ROOT/'evidence/accuracy_recovery_20261019/video_holdout/truth_sealed.json')['rows']
    from scripts.check_incident_counterfactual import GreenStretch
    warp=GreenStretch(**read_json(ROOT/'evidence/incident_validation_20261020/protocol.json')['warp'])
    for case in ('baseline','extended'):
        start=1740634505000;end=1740634782000+(12000 if case=='extended' else 0)
        series={};vehicles={}
        files={'v7':ROOT/'.web_runtime/incident_validation_20261020'/(case+'_issuance.jsonl'),
               'joint':LOCAL/'v5'/(case+'_issuance.jsonl'),'path':LOCAL/'path_v1'/(case+'_issuance.jsonl')}
        for name,path in files.items():
            rows=[];historical=[]
            with path.open(encoding='utf8') as f:
                for line in f:
                    r=json.loads(line);now=r['timestamp_ms']
                    if not start<=now<=end:continue
                    values={a:h['main']['state'] for a,h in r['heads'].items()}
                    rows.append([now,values])
                    if 'vehicles' in r:
                        cars=[[v['x'],v['y'],v.get('angle',0)] for v in r['vehicles']]
                        if name=='joint':vehicles[str(now)]=cars
                        elif name=='path':assert vehicles[str(now)]==cars,'shared motion/rendering changed'
                    for h in r.get('finalized_history',[]):
                        if start<=h['timestamp_ms']<=end:historical.append([h['timestamp_ms'],{a:v['main']['state'] for a,v in h['heads'].items()}])
            if name!='path':series[name]=rows
            if name!='v7':series[name+'_history']=historical
        spans=[]
        for i in range(3):
            for color,nxt in [('GREEN','YELLOW'),('YELLOW','RED')]:
                a=next(r for r in truth if r['color']==color and r['index']==i)['clock_mapping']['json_bracket_fixed_clock_ms'][1]
                b=next(r for r in truth if r['color']==nxt and r['index']==i)['clock_mapping']['json_bracket_fixed_clock_ms'][0]
                spans.append([warp.timestamp(a) if case=='extended' else a,warp.timestamp(b) if case=='extended' else b,color])
        data['cases'][case]=dict(start=start,end=end,series=series,vehicles=vehicles,truth=spans,
            metrics={n:read_json(OUT/'v5'/(case+'_result.json'))[n] for n in ('counts','history_counts')},
            path_metrics=read_json(OUT/'path_v1'/(case+'_result.json'))['history_counts'])
    save(OUT/'summary.json',dict(status='FAIL_NO_PROMOTION',production_enabled=False,
        synthetic_cases=len(results),synthetic_aggregate=aggregate,
        source_snapshots='source_snapshots/: exact frozen code for v1..v5 and path_v1',
        path_adapter_followup='current adapter additionally suppresses history colors without any evidence; path_v1 metrics belong to frozen earlier adapter',
        real_scope='previously revealed N GREEN/YELLOW brackets with conditional fixed clock; no RED or all-head accuracy claim',
        video_link='user identifies W->_W; all6 source JSON read again,23 such metadata candidates; no accepted identity/clock',
        acceptance_failures=['ordinary real labelled seconds/yellow regress','K2/K3 synthetic regression','95% universal accuracy not established']))
    html=TEMPLATE.replace('__DATA__',json.dumps(data,separators=(',',':')).replace('</','<\\/'))
    with (OUT/'comparison.html').open('x',encoding='utf8') as f:f.write(html)
    review=OUT/'video_link';review.mkdir(exist_ok=True)
    for name in ('preimpact_flow_contact.jpg','collision_flow_review.jpg'):
        shutil.copyfile(LOCAL/name,review/name)
    proposals=read_json(LOCAL/'preimpact_flow_proposals.json')
    save(review/'preimpact_video_points.json',dict(**proposals,user_movement='W->_W',
        review='contact-reviewed white-car roof before impact only; not accepted as any JSON ID',
        first_backward_trace='REJECTED: feature identity switched during impact rotation; retained runtime only'))
    print('AGGREGATE',json.dumps(aggregate),flush=True)


TEMPLATE=r'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Traffic Phase — проверка единой модели</title><style>
:root{color-scheme:dark;font:16px system-ui;background:#10151c;color:#e3eaf1}body{max-width:1080px;margin:24px auto;padding:0 16px}h1{font-size:26px}h2{font-size:20px}p{line-height:1.5;color:#bbc7d5}a{color:#82bfff}.note{border-left:4px solid #f4ba56;padding:12px;background:#25221b}section{background:#18212b;border:1px solid #334252;border-radius:12px;padding:16px;margin:16px 0}button,select,input{font:inherit;color:inherit;background:#243445;border:1px solid #526479;border-radius:6px;padding:8px}input[type=range]{width:100%;padding:0;margin:14px 0}.controls{display:flex;align-items:center;gap:12px;flex-wrap:wrap}table{border-collapse:collapse;width:100%;font-size:14px}td,th{text-align:left;padding:9px;border-bottom:1px solid #344454}th{color:#c5d6e6}.scroll{overflow:auto}.player{display:grid;grid-template-columns:300px 1fr;gap:20px}.heads{display:grid;gap:8px}.headrow{display:grid;grid-template-columns:1fr repeat(4,48px);gap:6px;align-items:center}.light{padding:9px 0;border-radius:6px;text-align:center;color:white;font-weight:bold}.g{background:#186b46}.y{background:#967900}.r{background:#943a40}.ry{background:linear-gradient(135deg,#943a40 50%,#967900 50%)}.u{background:#465361}.track{display:flex;height:17px;width:100%;margin:5px 0 10px;border-radius:3px;overflow:hidden}.track i{flex:1}small{color:#a8b6c6}#second{width:80px}svg{width:100%;height:auto}.chartbar{height:12px;background:#254353}.chartbar b{display:block;height:100%;background:#72b8ef}img{max-width:100%;height:auto}@media(max-width:650px){.player{grid-template-columns:1fr}.headrow{grid-template-columns:1fr repeat(4,35px);font-size:12px}body{padding:0 10px}td,th{padding:6px}section{padding:10px}h1{font-size:22px}}
</style><h1>Единая модель цветов и переменной длительности</h1>
<p class="note"><strong>Эксперимент не прошёл приёмку. В приложении остаётся v7.</strong><br>
Новая модель удержала12/12 добавленных секунд зелёного, но ухудшила обычный жёлтый и часть синтетики.95% для проекта не подтверждены.</p>
<p>Во входе алгоритма — сохранённая офлайн-модель и текущие машины. Видео используется только для проверки. История «+10с» доступна через10 секунд после оцениваемого момента; её нельзя считать мгновенным прогнозом.</p>
<section><h2>Реальный JSON и его изменённая копия</h2><div class="controls"><label>Поток <select id="case"><option value="extended">Зелёный +12 секунд</option><option value="baseline">Исходный JSON</option></select></label><button id="play">▶ Воспроизвести</button><label>Скорость <select id="speed"><option>1</option><option selected>5</option><option>20</option></select>×</label><label>Секунда <input id="second" type="number" min="0" value="0"></label></div>
<input type="range" id="seek" min="0" value="0" step="1"><p id="clock"></p><div class="player"><svg id="scene" viewBox="0 0 300 300" aria-label="Машины на условной схеме"></svg><div><div class="headrow"><strong>Оценка</strong><b>N</b><b>S</b><b>E</b><b>W</b></div><div class="heads" id="heads"></div><p id="truth"></p><small>Независимые метки есть только для основной N: зелёный и жёлтый в трёх известных циклах. Пустые промежутки не размечены. Физическая геометрия схемы не подтверждена.</small></div></div>
<h2>Цвет основной N во всём окне</h2><div id="timelines"></div><div class="scroll"><table><thead><tr><th>Оценка</th><th>Верно / всего</th><th>Жёлтый</th><th>Добавленный зелёный</th></tr></thead><tbody id="metrics"></tbody></table></div></section>
<section><h2>Новые парные физические сценарии</h2><p>12 потоков по30 минут: K=2…5, обычный режим, блокировка N и продление12с. Все основные цвета, UNKNOWN считается ошибкой. Один и тот же интервал180–1790с для всех оценок. Это контроль симулятора, не доказательство точности на дорогах.</p><div id="aggregate"></div><div class="scroll"><table><thead><tr><th>K</th><th>Сценарий</th><th>v7 сейчас</th><th>Единая сейчас</th><th>История +10с</th></tr></thead><tbody id="synthetic"></tbody></table></div></section>
<section><h2>ДТП на Энтузиастов: привязка ещё не принята</h2><p>Пользователь подтвердил разворот пострадавшей белой машины W→_W. Прежний кандидат8341 записан E→_W, его соответствие не подтверждено. Повторно прочитаны все6 JSON:10117 траекторий,23 записи W→_W. Часы нельзя подбирать по цветам светофора.</p><a href="video_link/collision_flow_review.jpg">Исходные кадры столкновения</a> · <a href="video_link/preimpact_flow_contact.jpg">Сопровождение белой машины до столкновения</a><p><small>Первый автоматический трек во время удара перескочил на соседнюю машину и отвергнут. Показан отдельный проход до удара. Подтверждённого track ID и секундной метрики по ДТП пока нет.</small></p></section>
<p><a href="summary.json">Машинный итог</a> · <a href="v5/protocol.json">Протокол сырого replay</a> · <a href="v5/synthetic/protocol.json">Протокол синтетики</a></p>
<script id="payload" type="application/json">__DATA__</script><script>
const data=JSON.parse(document.querySelector('#payload').textContent),$=s=>document.querySelector(s),labels={v7:'v7 сейчас',joint:'Единая сейчас',joint_history:'Единая: история +10с',path_history:'Путь: история +10с'},css={GREEN:'g',YELLOW:'y',RED:'r',RED_YELLOW:'ry',UNKNOWN:'u'},short={GREEN:'З',YELLOW:'Ж',RED:'К',RED_YELLOW:'КЖ',UNKNOWN:'?'},palette={GREEN:'#32af75',YELLOW:'#e7c54b',RED:'#d65b62',RED_YELLOW:'#e5954b',UNKNOWN:'#59697b'};
let maps={},active,timer=null;const pc=n=>(100*n).toFixed(2)+'%',esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;');
function load(){active=data.cases[$('#case').value];maps={};for(const [key,rows] of Object.entries(active.series))maps[key]=new Map(rows.map(r=>[r[0],r[1]]));const length=(active.end-active.start)/1000;$('#seek').max=length;$('#second').max=length;$('#seek').value=0;$('#second').value=0;
 $('#timelines').innerHTML=Object.entries(labels).map(([key,label])=>'<small>'+label+'</small><div class="track">'+active.series[key].map(r=>'<i style="background:'+palette[r[1].N]+'" title="'+new Date(r[0]).toLocaleTimeString()+' '+r[1].N+'"></i>').join('')+'</div>').join('');
 const old=$('#case').value==='extended'?{total:165,correct:147,YELLOW_correct:3,YELLOW_total:9,added_correct:2,added_total:12}:{total:153,correct:147,YELLOW_correct:5,YELLOW_total:9};
 const rows=[['v7 сейчас',old],['Единая сейчас',active.metrics.counts],['Единая: история +10с',active.metrics.history_counts],['Путь: история +10с',active.path_metrics]];
 $('#metrics').innerHTML=rows.map(([n,c])=>'<tr><td>'+n+'</td><td>'+c.correct+'/'+c.total+' ('+pc(c.correct/c.total)+')</td><td>'+c.YELLOW_correct+'/'+c.YELLOW_total+'</td><td>'+(c.added_total?c.added_correct+'/'+c.added_total:'—')+'</td></tr>').join('');render();}
function render(){let second=Number($('#seek').value);$('#second').value=second;const now=active.start+second*1000;$('#clock').textContent=new Date(now).toLocaleString('ru-RU',{timeZone:'Asia/Yekaterinburg'})+' · '+second+'с';
 $('#heads').innerHTML=Object.entries(labels).map(([key,label])=>{const h=maps[key].get(now)||{};return '<div class="headrow"><span>'+label+'</span>'+['N','S','E','W'].map(a=>'<span class="light '+(css[h[a]]||'u')+'" title="'+(h[a]||'UNKNOWN')+'">'+(short[h[a]]||'?')+'</span>').join('')+'</div>';}).join('');
 const truth=active.truth.find(r=>r[0]<now&&now<r[1]);$('#truth').textContent='Видеометка N: '+(truth?({GREEN:'зелёный',YELLOW:'жёлтый'}[truth[2]]):'нет уверенной метки');
 const cars=active.vehicles[String(now)]||[];$('#scene').innerHTML='<rect width="300" height="300" rx="12" fill="#29343e"/><path d="M110 0H190V300H110ZM0 110H300V190H0Z" fill="#44515d"/><path d="M150 0V100M150 200V300M0 150H100M200 150H300" stroke="#bcb370" stroke-dasharray="8 8"/><text x="150" y="18" text-anchor="middle" fill="white">N</text><text x="150" y="292" text-anchor="middle" fill="white">S</text><text x="280" y="155" fill="white">E</text><text x="8" y="155" fill="white">W</text>'+cars.map(([x,y,a])=>'<rect x="-4" y="-7" width="8" height="14" rx="2" fill="#83b9ff" transform="translate('+(x*300)+','+(y*300)+') rotate('+(a*180/Math.PI)+')"/>').join('');}
$('#case').onchange=load;$('#seek').oninput=render;$('#second').onchange=()=>{$('#seek').value=$('#second').value;render();};$('#play').onclick=()=>{if(timer){clearInterval(timer);timer=null;$('#play').textContent='▶ Воспроизвести';return;}$('#play').textContent='Ⅱ Пауза';timer=setInterval(()=>{const next=Number($('#seek').value)+Number($('#speed').value);if(next>Number($('#seek').max)){$('#play').click();return;}$('#seek').value=next;render();},1000);};
$('#synthetic').innerHTML=data.synthetic.map(r=>'<tr><td>'+r.k+'</td><td>'+({normal:'Обычный',blocked_N:'Блокировка N',extended_12s:'Продление12с'}[r.case])+'</td><td>'+pc(r.accuracy.v7_instant)+'</td><td>'+pc(r.accuracy.joint_instant)+'</td><td>'+pc(r.accuracy.joint_history_10s)+'</td></tr>').join('');$('#aggregate').innerHTML=Object.entries(data.aggregate).map(([n,r])=>'<p>'+({v7_instant:'v7 сейчас',joint_instant:'Единая сейчас',joint_history_10s:'Единая: история +10с'}[n])+': <b>'+pc(r.accuracy)+'</b> ('+r.counts.correct+'/'+r.counts.total+')</p><div class="chartbar"><b style="width:'+pc(r.accuracy)+'"></b></div>').join('');load();
</script></html>'''


if __name__=='__main__':main()
