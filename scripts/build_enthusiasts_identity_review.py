"""Make provisional car associations reviewable without any new clock fit."""
from html import escape
from PIL import Image,ImageDraw,ImageFont
from scripts.cardinal_clock_link import ROOT,OUT,OLD,RAW,read,save,sha


def main():
    target=OUT/'enthusiasts_identity_review';target.mkdir(exist_ok=False)
    points=read(OLD/'corrected_points.json')['rows']
    points += [r for r in read(OLD/'heldout_points.json')['rows'] if r['track_id']==7]
    selected=[r for r in read(RAW) if r['id'] in [2,6,7]]
    save(target/'provisional_associations.json',dict(points=points,source_tracks=selected,
        source_json_sha256=sha(RAW),accepted_identities=False,clock_mapping_accepted=False,
        purpose='manual identity/turn review after failed geometry; no fitted overlays or clock fitting'))
    colors={2:'#ffc64c',6:'#65e6ff',7:'#ff82c3'};font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',30)
    cards=''
    for t in sorted({p['actual_media_pts_s'] for p in points}):
        rows=[p for p in points if p['actual_media_pts_s']==t]
        original=ROOT/rows[0]['source_native_file']
        expected=rows[0].get('source_native_sha256',rows[0].get('native_sha256'))
        assert sha(original)==expected
        im=Image.open(original).convert('RGB');draw=ImageDraw.Draw(im)
        for p in rows:
            box=p['bbox_native_px'];color=colors[p['track_id']]
            draw.rectangle(box,outline=color,width=4)
            draw.text((box[0],box[1]-38),f"candidate {p['track_id']}?",font=font,fill=color,stroke_fill='black',stroke_width=2)
        name=f"pts_{t:g}.jpg";im.save(target/name,quality=94)
        cards+=f'<figure><figcaption>PTS {t:g} с. Рамки — прежние предположения, ID не подтверждены.</figcaption><a href="{name}"><img src="{name}"></a></figure>'
    paths=''
    for r in sorted(selected,key=lambda r:r['id']):
        ds=r['detections'];coords=' '.join(f"{d['centroid_x']*1000:.2f},{d['centroid_y']*600:.2f}" for d in ds)
        paths+=f'<polyline points="{coords}" fill="none" stroke="{colors[r["id"]]}" stroke-width="4"/><text x="20" y="{30*r["id"]}" fill="{colors[r["id"]]}">JSON ID {r["id"]}: {escape(r["zone_in"])} → {escape(r["zone_out"])}</text>'
    page='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Энтузиастов — проверка машин</title><style>body{font:17px/1.5 system-ui;background:#111720;color:#edf4ff;max-width:1150px;margin:25px auto;padding:0 14px}a{color:#9ccdff}img,svg{max-width:100%;height:auto}figure{margin:20px 0}svg{background:#253047}button{padding:8px;margin:6px}video{width:100%}</style><h1>Энтузиастов: проверить соответствие машин</h1><p>Прежняя привязка не прошла проверку. Здесь сохранены конкретные предположения, которые нужно проверить: жёлтая рамка — кандидат ID2, голубая — ID6, розовая — ID7. Номера в кадре пока предположительные. Разметка не получена из результата подгонки.</p><p>Нужно определить, те ли это машины и соответствует ли их манёвр форме трека ниже. Особенно важен ID7: в JSON он входит и выходит через E. Даже подтверждение манёвра не доказывает совпадение часов.</p><p>Исходные траектории JSON в собственной системе нормированных координат, без совмещения с видео:</p><svg viewBox="0 0 1000 600">'''+paths+'''</svg><p>Для просмотра движения выберите lenina_entuziastov.mp4. Файл остаётся локальным. Кнопки переходят к точкам старых гипотез, не к подтверждённым JSON-кадрам.</p><input id="file" type="file" accept="video/mp4"><video id="video" controls></video><div id="buttons"></div>'''+cards+'''<p><a href="../report.html">Общий результат и ограничения</a></p><script>const v=document.getElementById('video');let url;document.getElementById('file').onchange=e=>{if(url)URL.revokeObjectURL(url);url=URL.createObjectURL(e.target.files[0]);v.src=url};for(const t of [13,13.5,14,15,17,24,28]){const b=document.createElement('button');b.textContent=t+' с';b.onclick=()=>{v.pause();v.currentTime=t};document.getElementById('buttons').append(b)}</script></html>'''
    with (target/'index.html').open('x',encoding='utf8',newline='\n') as f:f.write(page)
    print('Prepared concrete provisional identity review; no new fitting')


if __name__=='__main__':main()
