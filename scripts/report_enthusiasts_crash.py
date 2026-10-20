"""Video-only incident reference; no light predictions or JSON clock fitting."""
import hashlib
import json
from pathlib import Path
import shutil
from PIL import Image,ImageDraw
from scripts.corpus_validation import ROOT,save
from app.core.intersection_project import read_json,digest
from scripts.locate_enthusiasts_crash import OUT,LOCAL


def main():
    video=ROOT/'.web_runtime/incident_validation_20261020/video'
    head=video/'crash_head_3750_4350';frames=read_json(head/'frames.json')['frames']
    # Conservative decoded-image appearance brackets, manually reviewed without
    # algorithm outputs. Occlusion/dark lenses make some brackets wider than1s.
    bounds=[('RED',3770.5,3771.),('GREEN',3806.666667,3807.166667),
            ('RED',3870.8,3871.3),('GREEN',3906.866667,3907.866667),
            ('RED',3970.466667,3971.),('GREEN',4006.633333,4008.666667),
            ('RED',4070.766667,4071.266667),('GREEN',4107.333333,4108.333333),
            ('RED',4170.566667,4172.566667),('GREEN',4206.633333,4207.133333),
            ('RED',4270.733333,4271.233333),('GREEN',4307.3,4308.3)]
    rows=[];(OUT/'head_endpoints').mkdir(parents=True,exist_ok=False)
    for i,(color,a,b) in enumerate(bounds):
        ends=[]
        for tag,target in [('before',a),('after',b)]:
            row=min(frames,key=lambda r:abs(r['pts_s']-target));assert abs(row['pts_s']-target)<.1
            src=head/row['file'];assert digest(src)==row['sha256']
            dst=OUT/'head_endpoints'/f'{i:02}_{tag}.png';shutil.copyfile(src,dst)
            ends.append(dict(file=dst.relative_to(OUT).as_posix(),pts_s=row['pts_s'],pts_ticks=row['pts_ticks'],sha256=digest(dst)))
        assert ends[0]['pts_s']<ends[1]['pts_s']
        rows.append(dict(color=color,approach='E',section='main',
                         bracket_s=[e['pts_s'] for e in ends],before=ends[0],after=ends[1],
                         precision='COARSE_VIDEO_APPEARANCE_NOT_CALIBRATED_PHYSICAL_SWITCH',
                         review='single Codex visual review; no model predictions',
                         warning='some lenses dim/occluded; no subsecond claim for all rows'))
    save(OUT/'video_truth_sealed.json',dict(rows=rows,site='enthusiasts',video_window_s=[3750,4350],
        source_sha256='c574f9204abab0b2bd4dd88425e581da8d335c8e6be0cf4425c0ac7143bfa987',
        source_hash_scope='previous complete video hash; not rehashed this turn',
        video_clock_zero='2024-10-05 11:59:58',user_collision_clock='13:03:50',user_pts_approx_s=3832,
        visible_head='E; user reports W identical; do not double-count as independent heads',
        N_truth='UNKNOWN_NOT_VISIBLE',YELLOW_truth='not certified in this coarse pass; green blinking/dim amber need refinement',
        JSON_evaluation_eligible=False,clock_mapping_accepted=False,algorithm_predictions_read=False))
    for name in ['crash_130350','crash_collision_seconds','crash_after_130350','crash_head_3750_4350']:
        save(OUT/(name+'_frames.json'),read_json(video/name/'frames.json'))
    # Store readable context; originals and their PTS/hashes remain in manifest.
    for name in ['crash_130350','crash_collision_seconds','crash_after_130350']:
        shutil.copyfile(video/name/'contact_0.jpg',OUT/(name+'.jpg'))
    before=Image.open(video/'crash_130350/03830.jpg');after=Image.open(video/'crash_after_130350/04260.jpg')
    display=Image.new('RGB',(1344,800),'white');draw=ImageDraw.Draw(display)
    for i,(im,label) in enumerate([(before,'13:03:48 - before incident'),(after,'13:10:58 - bus still blocks N')]):
        im.thumbnail((672,760));display.paste(im,(i*672,30));draw.text((i*672+8,8),label,fill='black')
    display=display.crop((0,0,1344,430));display.save(OUT/'before_after.jpg',quality=94)
    candidates=read_json(OUT/'raw_candidates.json')
    save(OUT/'incident_review.json',dict(user_statement='13:03:50 - мотоциклист разбился об легковую машину. автобус преградил поток',
        visual_confirmation=True,collision_video_bracket_s=[3832,3834],
        bus_block_observed_at_pts_s=[3840,3850,3860,3870,3880,3900,3945,3990.033333,4035,4080,4125,4170,4215.033333,4260],
        stationary_sample_span_s=420,visible_E_signal_continues_cycling=True,
        raw_categories=candidates['categories'],raw_bus_records=candidates['categories']['bus'],
        motorcycle_category_records=0,absence_of_category_not_proof_of_no_motorcycle_detections=True,
        clock_candidate=dict(id=8341,member='6_2025_2_23_15.json',category='car',duration_s=434.591,
                             role='long interior stop candidate only; identity NOT accepted',
                             track_sha256=digest(LOCAL/'candidates/8341.json')),
        no_phase_fit_or_replay=True,production_unchanged=True,physical_N_colors_not_inferred=True))
    headcards=[]
    for r in rows:
        a,b=r['bracket_s'];headcards.append(f'<tr><td>{r["color"]}</td><td>{a:.3f}–{b:.3f}</td><td>{b-a:.3f}</td>'+
            ''.join(f'<td><img width="120" height="130" src="{r[tag]["file"]}"></td>' for tag in ('before','after'))+'</tr>')
    html='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Энтузиастов: найденное ДТП</title><style>body{font:16px/1.5 system-ui;max-width:1100px;margin:25px auto;padding:0 18px;background:#111820;color:#e7edf5}a{color:#82bfff}img.context{width:100%;height:auto}table{display:block;overflow:auto;border-collapse:collapse}td,th{padding:8px;border:1px solid #46576b}td img{image-rendering:pixelated}.note{padding:15px;background:#29354a;border-radius:8px}</style>
<h1>Энтузиастов, 05.10.2024: ДТП найдено</h1><p>Указанные 13:03:50 соответствуют PTS3832с. На кадрах3832–3834с видны столкновение мотоцикла с белой машиной и последующая остановка автобуса. Автобус остаётся препятствием перед N на просмотренных кадрах как минимум с13:03:58 до13:10:58.</p><img class="context" src="before_after.jpg"><p class="note">Это пока видеоэталон. Связь videoPTS ↔ millis JSON не принята, поэтому новая точность алгоритма не вычислялась. Видимый E/W продолжает переключаться; цвет N напрямую не виден и из противоположного направления не выдумывается. Видео не поступает в рабочий алгоритм.</p>
<p><a href="crash_collision_seconds.jpg">Столкновение по секундам</a> · <a href="crash_130350.jpg">До/после ДТП</a> · <a href="crash_after_130350.jpg">Перекрытие автобусом</a></p><p>Все6 JSON прочитаны. Найдены213 записей bus; записей категории мотоцикла нет. Среди долгих остановок есть кандидат car8341 (434,591с), но его тождество машине в ДТП ещё не подтверждено. Исходные данные сохранены.</p>
<h2>Видимая E:12 границ появления зелёного/красного</h2><p>Метки получены из видео до чтения прогнозов алгоритма. Это один визуальный обзор; ширина некоторых brackets превышает1с из-за тёмных/перекрытых линз. Жёлтый и красно-жёлтый пока не сертифицированы. Таблица не утверждает посекундную точность алгоритма.</p><table><tr><th>Цвет</th><th>PTS,с</th><th>Ширина,с</th><th>До</th><th>После</th></tr>'''+''.join(headcards)+'''</table><p><a href="../../docs/ENTHUSIASTS_CRASH_REFERENCE_20261020.md">Подробности и следующий шаг</a></p></html>'''
    with (OUT/'index.html').open('x',encoding='utf8',newline='\n') as f:f.write(html)
    save(OUT/'manifest.json',dict(files=[dict(path=p.relative_to(OUT).as_posix(),bytes=p.stat().st_size,sha256=digest(p))
        for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='manifest.json'],
        source_script_sha256=digest(Path(__file__)),model_predictions_read=False,clock_mapping_accepted=False))
    print(OUT/'index.html',flush=True)


if __name__=='__main__':main()
