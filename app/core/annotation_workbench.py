"""Bounded review using the existing JSON reader; no phase inference/evaluation calls."""
from collections import Counter
import hashlib
import json
import math
import time

from app.core.v9.events import _iter_json_records

VERSION = 'trajectory-review-v1'
MAX_BYTES = 256*1024*1024
MAX_TRACKS = 6000
MAX_POINTS = 300000
MAX_SECONDS = 30
KINDS = {'vehicle_event','phase_hypothesis','signal_observation','visibility_gap'}
SOURCES = {'trajectory_review','trajectory_with_onsite_knowledge','video_review','controller_log_review'}


class LimitedReader:
    def __init__(self,stream,max_bytes,deadline):
        self.stream=stream; self.max_bytes=max_bytes; self.deadline=deadline
        self.digest=hashlib.sha256(); self.size=0

    def read(self,n=-1):
        if time.monotonic()>self.deadline: raise ValueError('TIME_LIMIT: чтение превысило 30 секунд')
        chunk=self.stream.read(min(65536,n) if n>=0 else 65536)
        self.size+=len(chunk)
        if self.size>self.max_bytes: raise ValueError('SIZE_LIMIT: JSON превышает 256 MiB')
        self.digest.update(chunk);return chunk


def number(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)


def prepare_preview(stream,filename,*,start_seconds=0,duration_seconds=180,
                    max_bytes=MAX_BYTES,max_tracks=MAX_TRACKS,max_points=MAX_POINTS,max_seconds=MAX_SECONDS):
    started=time.monotonic(); reader=LimitedReader(stream,max_bytes,started+max_seconds)
    if not number(start_seconds) or not number(duration_seconds) or start_seconds<0 or not 0<duration_seconds<=1800:
        raise ValueError('Окно просмотра: начало >=0, длительность от 0 до 1800 секунд')
    # First streaming pass establishes an order-independent global clock/hash.
    # Second pass retains exact detections only for the requested small window.
    t0=t1=None
    for index,record in enumerate(_iter_json_records(reader)):
        if index>=max_tracks:raise ValueError('TRACK_LIMIT: более 6000 записей; откройте отдельный сеанс')
        ds=record.get('detections')
        if not isinstance(ds,list):continue
        for d in ds:
            if not isinstance(d,dict):continue
            t,x,y=(d.get(k) for k in ('millis','centroid_x','centroid_y'))
            if all(number(v) for v in (t,x,y)) and abs(t)<=2**53-1 and t==int(t):
                t0=int(t) if t0 is None else min(t0,int(t));t1=int(t) if t1 is None else max(t1,int(t))
    digest=reader.digest.hexdigest();size=reader.size
    if t0 is None:raise ValueError('NO_COORDINATES: нет пригодных millis/centroid_x/centroid_y')
    if t1<=t0:raise ValueError('NO_TIME_RANGE: нужен ненулевой диапазон времени')
    window_start=t0+round(start_seconds*1000);window_end=min(t1,window_start+round(duration_seconds*1000))
    if window_start>=t1:raise ValueError('Окно начинается после конца записи')
    stream.seek(0);reader=LimitedReader(stream,max_bytes,started+max_seconds)
    tracks=[];stats=Counter();total=0;seen=set()
    for index,record in enumerate(_iter_json_records(reader)):
        stats['source_records']+=1
        if index>=max_tracks:raise ValueError('TRACK_LIMIT: более 6000 записей; откройте отдельный сеанс')
        if time.monotonic()>reader.deadline:raise ValueError('TIME_LIMIT: превышен бюджет подготовки')
        fingerprint=hashlib.sha256(json.dumps(record,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        if fingerprint in seen:stats['duplicate_records']+=1;continue
        seen.add(fingerprint); samples={};conflicts=set()
        detections=record.get('detections')
        if not isinstance(detections,list):stats['records_without_detections']+=1;continue
        for d in detections:
            if not isinstance(d,dict):stats['invalid_detections']+=1;continue
            t,x,y=(d.get(k) for k in ('millis','centroid_x','centroid_y'))
            if not all(number(v) for v in (t,x,y)) or abs(t)>2**53-1 or t!=int(t):
                stats['invalid_detections']+=1;continue
            point=[int(t),float(x),float(y),d.get('speed') if number(d.get('speed')) else None]
            if t in samples:
                if samples[t][1:3]!=point[1:3]:conflicts.add(t)
                else:stats['duplicate_detections']+=1
                continue
            samples[t]=point
        for t in conflicts:samples.pop(t,None)
        stats['conflicting_timestamps_removed']+=len(conflicts)
        points=sorted(samples.values())
        if not points:stats['empty_tracks']+=1;continue
        if points[-1][0]<window_start or points[0][0]>window_end:continue
        # No extra points outside the window: no invented support at its edges.
        points=[p for p in points if window_start<=p[0]<=window_end]
        if not points:continue
        total+=len(points)
        if total>max_points:raise ValueError('POINT_LIMIT: более 300000 detections; требуется меньший сеанс')
        tracks.append({'key':f'{index}:{fingerprint[:16]}','source_track_id':str(record.get('id','')),
                       'fingerprint':fingerprint,'movement':f"{record.get('zone_in','?')}->{record.get('zone_out','?')}",
                       'points':points})
    if reader.digest.hexdigest()!=digest:raise ValueError('INPUT_CHANGED: файл изменился между проходами')
    if not tracks:raise ValueError('NO_WINDOW_OBSERVATIONS: в этом окне нет точек; это не доказательство RED')
    xs=[p[1] for t in tracks for p in t['points']];ys=[p[2] for t in tracks for p in t['points']]
    bounds=[min(xs),min(ys),max(xs),max(ys)]
    if not math.isfinite(bounds[2]-bounds[0]) or not math.isfinite(bounds[3]-bounds[1]):raise ValueError('INVALID_COORDINATE_EXTENT')
    for track in tracks:
        for p in track['points']:p[0]-=t0
    return {'producer':VERSION,'source':{'name':filename,'sha256':digest,'bytes':size,
              'timestamp_origin_ms':t0,'end_timestamp_ms':t1,'timestamp_field':'detections[].millis',
              'units':{'timestamp':'ms (input contract)','coordinates':'UNKNOWN','speed':'UNKNOWN'},
              'observed_extent_not_camera_coverage':True},
            'bounds':bounds,'tracks':tracks,'stats':dict(stats,display_tracks=len(tracks),display_points=total),
            'duration_ms':t1-t0,'preview_window_ms':[window_start-t0,window_end-t0],
            'inference_used':False,'streaming_passes':2,
            'limits':{'bytes':max_bytes,'tracks':max_tracks,'points':max_points,'seconds':max_seconds},
            'display_semantics':'raw image coordinates; no verified road or stop-line geometry',
            'runtime_s':time.monotonic()-started}


def validate_review(payload):
    if not isinstance(payload,dict) or payload.get('schema')!=VERSION:raise ValueError('Неизвестный формат разметки')
    source=payload.get('source',{});digest=source.get('sha256','')
    if len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):raise ValueError('Нет SHA256 исходного JSON')
    lo,hi=source.get('timestamp_origin_ms'),source.get('end_timestamp_ms')
    if not number(lo) or not number(hi) or hi<=lo:raise ValueError('Некорректный диапазон исходного файла')
    if not str(payload.get('reviewer','')).strip():raise ValueError('Укажите имя разметчика')
    marks=payload.get('annotations')
    if not isinstance(marks,list) or len(marks)>10000:raise ValueError('Некорректный список меток')
    seen=set()
    for mark in marks:
        if not isinstance(mark,dict) or mark.get('kind') not in KINDS:raise ValueError('Неизвестный тип метки')
        if not mark.get('id') or mark['id'] in seen:raise ValueError('Повтор ID метки')
        seen.add(mark['id'])
        a,b=mark.get('interval_start_ms'),mark.get('interval_end_ms')
        if not number(a) or not number(b) or not lo<=a<=b<=hi:raise ValueError('Интервал метки вне исходной истории')
        if not isinstance(mark.get('label'),str) or not mark['label'].strip() or len(mark['label'])>500:raise ValueError('Нужна краткая подпись метки')
        src=mark.get('evidence_source',{})
        if src.get('kind') not in SOURCES:raise ValueError('Не указан источник разметки')
        external=src['kind'] in {'video_review','controller_log_review'}
        if external and not str(src.get('reference','')).strip():raise ValueError('Нужна ссылка/имя независимого источника')
        if mark['kind']=='signal_observation' and not external:
            raise ValueError('Цвет лампы нельзя пометить наблюдённым по одной траектории; используйте гипотезу фазы')
        if mark.get('independently_verified') is not False:
            raise ValueError('Этот инструмент записывает review claims, не подтверждает независимую truth')
        expected='independent_source_review_claim' if external else 'trajectory_based_hypothesis'
        if mark.get('interpretation')!=expected:raise ValueError('Семантика метки не соответствует источнику')
        u=mark.get('vehicle_timing_uncertainty_ms')
        if u is not None and (not number(u) or u<0):raise ValueError('Некорректная uncertainty')
        sync=src.get('synchronization',{})
        if external and sync.get('status') not in {'unverified','operator_documented'}:raise ValueError('Нужен статус синхронизации')
        if sync.get('status')=='operator_documented':
            if not str(sync.get('verification_note','')).strip() or not number(sync.get('uncertainty_ms')) or sync['uncertainty_ms']<0:
                raise ValueError('Для документированной синхронизации нужны основание и uncertainty')
    return {'valid':True,'annotation_count':len(marks),'independent_truth_certified':False}
