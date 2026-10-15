# События автомобилей относительно наблюдаемого H1

Основа `039c0bd06e1e9ca8a17e021c036263d7d0086f58`, отдельная ветка
`calibration/event-signal-associations-20261015`. Выполнено одно извлечение событий
из подготовленных243 целых треков. Метки/видео не передавались extractor: события
и SHA256 зафиксированы до чтения signal references. Извлечение заняло1.351с.
Алгоритм фаз, selector, thresholds, period, mapping, evaluator и main сохранены.
Phase fitting/replay/benchmark не запускались; новые архивы и видео не читались.

## Объём данных и границы вывода

На всех целых треках:238 ENTRY,238 CROSSING_PROXY,72 RELEASE,0 STOP/actual CROSSING.
Пять same-arm записей (E→E/W→W) не дали событий из-за существующего origin==target
guard. Это не пять доказанных разворотов: нужны проверка движения/ошибок зон.
В44268 detections есть42097 конечных raw speed, но **ни одного точного нуля**.
Диапазон чисел0.000384865–84.994960, units UNKNOWN. Отсутствие exact-zero STOP
не означает, что ТС не останавливались. Все72 RELEASE получены методом
`kinematic_restart_proxy`, по относительному image motion, не по доказанной остановке.
Heuristic radius1.3с не является погрешностью переключения лампы.

Основной анализ ограничен video273.033333–393.033333с. Учитывается **всё** supplied
conditional clock set0.700099–1.643698с, не только лучший offset.347 событий полностью
внутри для всех этих offsets,7 частично пересекают край,194 снаружи. Последние201
не используются для численного сопоставления. Полные треки не обрезались; поэтому
548 общих событий не следует называть событиями ровно трёхминутного окна.
Clock uncertainty условна на фиксированной геометрии и не является полной calibrated
sync uncertainty. Ошибки локализации vehicle event и физического switch не смешиваются.

| Movement | ENTRY | CROSSING_PROXY | RELEASE | Выбрано текущим selector |
|---|---:|---:|---:|---:|
| E→N | 5 | 4 | 3 | 3 RELEASE |
| E→W | 33 | 34 | 5 | 5 RELEASE |
| N→E | 3 | 2 | 2 | 2 RELEASE |
| N→S | 30 | 30 | 5 | 5 RELEASE |
| S→E | 0 | 1 | 2 | 2 RELEASE |
| S→N | 24 | 24 | 12 | 12 RELEASE |
| W→E | 52 | 52 | 7 | 7 RELEASE |
| W→S | 8 | 7 | 2 | 2 RELEASE |
| **Всего внутри clock scope** | **155** | **154** | **38** | **38 RELEASE** |

Все238 proxy целых треков, включая154 внутри окна, исключены selector: каждый
поток содержит хотя бы один RELEASE. Это повторное подтверждение уже известного
механизма на новой calibration записи, не новый алгоритмический дефект и не повод
повторно писать selector. Существующий `app.experimental.local_evidence` использован
для сохранения отдельных каналов и same-track зависимости. Внутри strict окна192
permission events относятся к155 track groups; выбранные38 RELEASE представляют
38 групп, ещё117 групп отсутствуют в selected permission.192 события нельзя считать
192 независимыми ламповыми наблюдениями или просто объединить в старом likelihood.

Внутренний local-evidence query покрывает **union** отображений conditional clock:
354 событий,195 eligible vehicle events/158 групп, включая7 частично цензурированных.
Эти числа намеренно отличаются от strict347; `clock_scope` сохраняется у каждого
события. Exposure/demand остаются UNKNOWN: наличие видео и отсутствие машины
не подменяют camera/detector coverage. Все347 vehicle-level physical states UNKNOWN;
temporal reconstruction coverage и lamp accuracy здесь не измеряются.

## Первое количественное сопоставление

В clock scope есть **одно** наблюдаемое включение основного зелёного с боковой
секцией H1: media318.866667–318.933333. Ниже все RELEASE потоков N→S/N→E в strict
окне, без отбора по величине ошибки. Привязка этих потоков к H1 запрошена у автора
и на момент отчёта не подтверждена. Это signed offsets к указанной reference,
а не присвоенные реакции водителя, causal delay или обученные параметры модели.

| Track ID | Movement | Offset кандидата, с | Условный диапазон, с |
|---|---|---:|---|
| 9915800 | N→S | +0.354 | −0.034…+0.976 |
| 9915797 | N→S | +0.840 | +0.452…+1.462 |
| 9915806 | N→S | +1.074 | +0.686…+1.696 |
| 9915811 | N→S | +1.913 | +1.525…+2.535 |
| 9915815 | N→S | +2.410 | +2.022…+3.032 |
| 9915764 | N→E | +2.753 | +2.365…+3.375 |
| 9915830 | N→E | +3.705 | +3.317…+4.327 |

Положительные offsets согласуются с гипотезой разъезда очереди после разрешения,
но не подтверждают абсолютную STOP-семантику extractor. Первый conditional range
пересекает ноль. Семь машин одного onset не являются семью независимыми циклами;
у них общая ошибка часов. Универсальные1/2/3с delay/threshold/offset не вводились.

Отдельно рассмотрены все3 заранее выбранных и визуально сопоставленных ТС:

* Фургон9915665: RELEASE есть, но находится вне validated clock scope — aligned
  delay не назначается. CROSSING_PROXY внутри окна, на44.34с раньше указанного
  H1 onset. Это другой поток E→W, не доказательство проезда на запрещающий сигнал.
* Эвакуатор9915986: RELEASE нет; ENTRY на12.94с, CROSSING_PROXY на16.66с позже
  H1 onset (conditional crossing offset16.27–17.28с). Уже движущееся ТС входит
  в поле позже переключения; zone transition не является переключением/стоп-линией.
* Троллейбус9916124: RELEASE нет, есть ENTRY и CROSSING_PROXY, последний исключён
  из selected E→W из-за RELEASE других машин. Его offset к тому же H1 onset62.93с
  не называется реакцией: принадлежность H1 этому потоку не установлена.

## Что реализовано и что дальше

Изолированный join сохраняет signed offsets **к каждой из4 references отдельно**,
не выбирает ближайшую/лучшую фазу и не назначает цикл.1388 строк соответствуют
347 событиям ×4 references, не1388 независимым свидетельствам. Для candidate
окончания мигания сохраняется его особый status. Calibrated delay model имеет
машинно различимое UNAVAILABLE с причиной HEAD_MAPPING_AND_EVENT_SIGNAL_RELATION_UNVERIFIED.
Происхождение, методы, selected indices, source fingerprints, uncertainty и все
данные вне/на краю окна сохранены. Никакие старые predictions не перезаписывались.

Следующий конкретный шаг — подтвердить H1 approach/movement mapping и по видео
разметить фактическое начало движения/видимость всех7 N-потоковых RELEASE, затем
добавить независимые циклы calibration и отдельный validation session. Это позволит
оценить method-specific delay, не зашивая реакцию в lamp timestamp. При развитии
sequence model использовать уже готовые отдельные каналы и зависимости ТС;
не продвигать простое timestamp union в production. 2D.1 остаётся FAIL/default-off.

## Проверки и артефакты

`app/experimental/event_signal_associations.py`, отдельные CLI
`scripts/seal_vehicle_events.py` (raw-only extraction) и
`scripts/event_signal_associations.py`; воспроизведение join по уже сохранённому
extractor output описано в commands.log. Никакого повторного извлечения для анализа.
В evidence/event_signal_associations_20261015: plan, полный vehicle sidecar,
extraction seal, association JSON/CSV, summary и разбор3 ТС, команды/логи/хеши/ZIP.
Все4 production producer file SHA256 совпали с base; исходный user review сохранён.

`python -m pytest tests/test_event_signal_associations.py tests/test_local_evidence_channels.py tests/test_vehicle_temporal_evidence.py -q -p no:cacheprovider`:
**54 passed in2.35s**. Новые counterexamples проверяют clock multimodality/censoring,
no-demand UNKNOWN, корреляцию, missing track identity, rename invariance, запрет
приписывать causal delay/ламповую вероятность, seal barrier до чтения references
и запрет передавать файл разметки в extraction wrapper.
