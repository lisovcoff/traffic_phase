# Этап 2B.1: контракт временного evidence автомобиля

Дата: 2026-10-13. Основа — `benchmark/stage2a-offline-20261013`, `aa2c4a3`.
Ветка работы — `fix/stage2b1-temporal-evidence-20261013`.
Ветки этапов 1 и 2A отправлены в origin; main локально и в origin остаётся
`a005a2521f62ce3b2c9f9d52f9f0d73913754e01`.

## Подтверждённые дефекты

* Старый `_track_event_view` использует первую detection входной зоны, с fallback
  на первую detection. Это demand entry, не измерение пересечения стоп-линии.
* Metadata release = entry + stay. `_speed_restart_plausible` возвращает True
  при <6 speed points. Двухточечная траектория с stay=6s получает release
  confidence=0,9 без доказательства остановки/разгона (unit counterexample).
* Kinematic release — существующий relative image-speed solver, который ищет
  длительный low-speed участок и повышение скорости. Это не calibrated m/s,
  не stop-line crossing и не точное включение лампы. Smoothing и sampling дают
  дополнительную временную неопределённость; низкая скорость не обязательно STOP.
* Старый `_choose_phase_evidence` требует глобальную квоту ≥80/15% events и
  release coverage ≥половины streams. При её невыполнении *все* movements
  переключаются на mixed main timestamps, включая entry. Надёжный restart
  одного движения подменяется demand timestamp из-за разреженности другого.
* `load_event_streams` пакует только timestamps: индивидуальные source ID,
  method и confidence теряются до fitting. Method counts не восстанавливают
  их связь с конкретным событием. Unknown uncertainty нельзя получить из counts.
* In-memory путь не дедуплицирует треки; path loader использует ID+first time+OD,
  что может склеить разные безымянные/частичные треки. Duplicate detection
  timestamps и NaN не защищены в старом V9 preprocessing.

Общий `trajectory_events.py` уже содержит stop/release logic, zone transition,
causal extraction и stop_line_provider. Его возможности не переписывались.
Переиспользованы `_zone_crossing_timestamp`, `_first_sustained`,
`EventExtractionConfig`, `_finite_number` из существующей normalizer/geometry;
V9 image-speed candidate тоже переиспользован без нового motion solver.

## Единый контракт и семантика

`app/core/temporal_evidence.py::TemporalEvent`:

| Поле | Значение |
| --- | --- |
| timestamp_ms | Время автомобильного evidence, absolute Unix milliseconds; для heuristic candidate — proxy, не истинный lamp switch |
| event_type | ENTRY / STOP / RELEASE / CROSSING_PROXY / CROSSING |
| movement | Нормализованный OD, произвольные направления поддержаны |
| source_track_id | Исходный ID, включая None без выдуманного ID |
| evidence_method | Конкретный наблюдаемый/эвристический способ |
| confidence / evidence_quality | Heuristic vehicle evidence score и HIGH/MEDIUM/LOW; **не вероятность лампы** |
| temporal_uncertainty_ms | Консервативный heuristic radius; None — неизвестна. Это не calibrated statistical CI |
| provenance | Source/member, track fingerprint/range, quality issues, observation bracket, proxy role, отсутствие lamp observation |

ENTRY — спрос. Если origin не наблюдался, entry — left-censored first-detection
proxy. STOP — stationary evidence, без знания места относительно стоп-линии и
без вывода RED. RELEASE — косвенный proxy возобновления движения. Он одинаково
возможен после разрешения движения, при permissive turn и после снятия ДТП-блокировки.
Причина остаётся неизвестной. Никакие события не содержат GREEN/RED.

Zone transition при неизвестной геометрии — **CROSSING_PROXY**. Timestamp
самого наблюдаемого zone transition хранится вместе с sampling bracket;
sampling gap отдельно от temporal_uncertainty относительно стоп-линии (None).
Конец траектории не создаёт crossing evidence. CROSSING допустим только при
явном verified_stop_line provenance; default V9 ни одной стоп-линии не предполагает.
`adapt_trajectory_event` соединяет старый TrajectoryEvent с этим контрактом:
старый CROSSING enum без verified geometry автоматически остаётся proxy.

## Ограниченный цикл изменений

* Санитизация finite integer timestamps, sorting, exact duplicate detections;
  conflicting same-time observations исключаются без произвольного выбора.
  Exact track fingerprint дедуплицирует одинаковые записи; разные безымянные
  треки с одним start не склеиваются. Partial snapshots с различным содержимым
  ещё не сшиваются — это остаётся отдельной задачей.
* Единый typed extractor для path и in-memory discovery. Оба пути сохраняют
  sidecar до вызова фазовой модели и в результат `event_extraction.temporal_events`.
  `selected_event_indices` указывает события, чьи timestamps получила модель.
* Metadata restart требует наблюдённый sustained zero-speed stop, достаточный
  before/after support, наблюдаемый подъём скорости и bracket без gap>2s.
  Для raw speed неизвестны единицы: абсолютные m/s thresholds не применяются;
  exact zero и относительный restart имеют unit-independent смысл. Общие
  stop_min_duration/gap limits взяты из существующего EventExtractionConfig.
* Existing image-space restart допускается лишь при полных finite centroids,
  достаточном числе points, наблюдаемом incoming/zone transition и без gaps>2s.
  Метод называется kinematic_restart_proxy, качество не выше MEDIUM.
* Uncertainty metadata restart ≥3s (его before/after support window), image
  restart ≥1,3s (два существующих smoothing scales по 0,65s); sampling brackets
  сохранены отдельно. Эти engineering bounds заранее выбраны по механизму,
  не по ручным marks; calibration ламповых задержек отсутствует.
* Selection **отдельно по movement**: поддержанные RELEASE, иначе eligible
  zone-crossing proxies. ENTRY никогда не подменяет фазовое permission evidence.
  Без любых permission proxies — явный ValueError с UNKNOWN, а не fabricated K.
* Zone proxy может быть LOW с неизвестной stop-line uncertainty и всё же давать
  движение-подобный фазовый признак. Эта слабость видна в diagnostics. HSMM
  получает только timestamps; confidence/uncertainty пока не входят в likelihood.
  Реализация их весов/цензурирования относится к следующему заданию.

Это изменение event ingestion и выбора evidence. HSMM, infer_period, выбор K,
periodic_baseline_from_segments и physical mapping не менялись. Временной extent
при новой политике включает последнюю permission observation, а не обрезается
последним demand entry. Offline evaluator, its CLI/config и annotations неизменны.

## Совместимость

`load_event_streams` возвращает tuple-compatible EventStreamBundle длины 10;
existing unpacking и packed array streams сохраняются. Default main/entry slots
теперь demand views; истинные selected phase timestamps находятся в
`permission_streams`. Атрибуты sidecar сохраняют происхождение. Публичные
legacy `extract_event_views`/`load_event_views` остаются tuple adapters и явно
документированы как legacy.

`discover_path(..., evidence_policy='legacy_v9')` и
`discover_records(..., evidence_policy='legacy_v9')` сохраняют старый extractor
и global gate. Default — `permission_per_stream`. Это намеренное изменение
семантики, а не обещание прежних фазовых результатов. Внешние consumers,
которые непосредственно unpack load_event_streams и выбирают evidence,
должны использовать permission_streams, а не считать demand slot разрешением.
`scripts/v9_regime_diagnostics.py` остаётся старым consumer release-only views;
его нельзя считать canonical selection диагностики новой политики.

Память sidecar O(vehicle events), а не O(raw detections). В рамках текущих трёх
записей это несколько тысяч events. На больших архивах сериализация provenance
может быть заметна; долговременный indexed sidecar/JSONL storage требует
отдельной resource проверки. Не запускать здесь полный 43GiB benchmark.

## Проверки и запуск

Новые unit cases: no-stop, stop/restart без геометрии, очередь с lag от внешнего
green, permissive/ДТП без причинного вывода, sparse/missing detections,
duplicates/conflicting timestamps, truncated records, missing IDs, no demand,
per-movement selection и sidecar сохранён до fitting, shared-event adapter.
Existing regression tests не переписаны ради зелёного результата.

После unit/regression запускается один benchmark с тем же evaluator/config:

```powershell
python -m scripts.offline_benchmark run --data-dir 'D:\Code\PythonProjects\traffic_phase\data\ручная разметка' --out benchmarks/stage2b1_20261013 --timeout 90
python -m scripts.compare_temporal_evidence benchmarks/stage2a_20261013/baseline_metrics.json benchmarks/stage2b1_20261013/baseline_metrics.json --out benchmarks/stage2b1_20261013/comparison.json
```

Comparer проверяет равенство configuration/source/annotation hashes и
неизменность prediction artifacts. Старые event counts показывают число
выданных entry/release views, а weak percentage unavailable из-за потери качества:
не восстанавливать его выдуманными числами. Нулевые STOP/CROSSING в legacy
означают «тип не выдавался», а не физическое отсутствие остановок/пересечений.
Разметка и три development-case не используются для настройки threshold.

После одного сравнения сохранить результаты, явно показать ухудшения и остановиться.
Без следующего задания не переходить к 2B.2.

## Реальное сравнение одного ограниченного запуска

Measured code: `161f32fd42ce80cca01bb74c0a00988d6969382a`, clean working tree
на момент запуска. Config SHA256 совпал с 2A:
`c1ca38484ba0033703cb44e49dcdb15d918345df3f9e909f2a59f2975cfab383`.
Источник и annotation hashes совпали для всех трёх пар. Before artifacts
не изменялись. After: `benchmarks/stage2b1_20261013/baseline_metrics.json`,
три lossless prediction JSON и `comparison.json`. Evaluator не модифицирован.

| Запись | V9 K before→after (truth) | V10 plan K before→after | Period error s before→after | Runtime s before→after |
| --- | --- | --- | --- | --- |
| 17_2025_2_19_10 | 3→3 (3) | 3→3 | 0,018187→0,018187 | 15,577→28,358 |
| 19_2025_2_24_16 | 3→2 (2) | 2→2 | 0,299500→0,299500 | 9,331→17,204 |
| 6_2025_2_14_20 | **2→3 (2), regression** | 2→2 | 0,129248→0,129248 | 12,023→20,248 |

V9 K accuracy остаётся 2/3: исправлен один development-case, испорчен другой.
V10 plan count совпадает в 3/3, но это не hardware lamp accuracy. Период
на этих записях численно неизменен. Sum runtime 36,931→65,810s (×1,782);
overhead включает очищение/хеширование detections и JSON-сериализацию provenance.
Это не performance profile и не прогноз на большие архивы.

| Запись/history | Matches before→after / truth | Predicted boundaries before→after | Precision %, before→after | Recall %, before→after | Nearest MAE s before→after |
| --- | --- | --- | --- | --- | --- |
| 17/raw | 3→15 / 17 | 18→18 | 16,67→83,33 | 17,65→88,24 | 6,4222→1,1052 |
| 17/baseline | 5→15 / 17 | 18→17 | 27,78→88,24 | 29,41→88,24 | 2,9450→1,0859 |
| 19/raw | 1→1 / 8 | 13→8 | 7,69→12,50 | 12,50→12,50 | 5,6570→4,7820 |
| 19/baseline | 2→1 / 8 | 13→8 | **15,38→12,50** | **25,00→12,50** | 6,3045→3,9516 |
| 6/raw | 2→3 / 9 | 10→15 | 20,00→20,00 | 22,22→33,33 | 3,0281→2,8059 |
| 6/baseline | 1→1 / 9 | 10→15 | **10,00→6,67** | 11,11→11,11 | 3,6181→2,7519 |

±2s tolerance unchanged. Raw summed matches 6→19 / 34; precision
14,63→46,34%, recall 17,65→55,88%. Baseline matches 8→17 / 34; precision
19,51→42,50%, recall 23,53→50,00%. Temporal coverage остаётся 100% для обеих
histories, что не доказывает correctness или observability. MAE/p95 matched
и individual matching pairs сохранены неизменным evaluator в after report;
nearest MAE отдельно, без one-to-one constraints, как в 2A.

| Запись | ENTRY before→after | RELEASE before→after | STOP before→after | CROSSING_PROXY before→after | Weak/unknown %, before→after |
| --- | --- | --- | --- | --- | --- |
| 17 | 2728→2728 | 796→716 | 0→0 | 0→2728 | unavailable→88,40% |
| 19 | 1104→1104 | 611→581 | 0→0 | 0→1104 | unavailable→79,17% |
| 6 | 1844→1844 | 1126→1107 | 0→0 | 0→1844 | unavailable→76,91% |

CROSSING actual =0 после, verified geometry отсутствует. STOP=0 означает,
что conservative zero-speed detector не выдал этого типа; не утверждает
отсутствия реальных остановок. Все after RELEASE на этих трёх записях —
kinematic_restart_proxy, а не metadata restart. Unsupported metadata candidates:
741 / 588 / 780. События ограничены movement labels с usable detections;
7 / 50 / 57 треков не имеют usable event. Sampling conflicts/invalid detections
на этих записях не обнаружены; их handling проверен контрпримерами.

Weak/unknown определяется как quality LOW **или** temporal_uncertainty=None;
в denominator все emitted types, включая demand ENTRY. Это честная метрика
контракта, не риск неправильной лампы. Selected permission events 717 / 597 /
1107; среди них weak/unknown 0,139% / 2,680% / 0%. Даже остальные selected
events имеют только heuristic radius, без stop-line geometry, без calibration
причин restart. Нельзя интерпретировать эти малые доли как confidence в GREEN.

Дополнительный аудит saved sidecar: 127 / 193 / 552 release proxies позже
observed zone transition. Zone transition сам не локализует стоп-линию, поэтому
нельзя автоматически удалить их как нарушения или backdate их к GREEN.
Image solver смотрит low-speed/restart вплоть до track end; происхождение этого
restart (очередь, поворот, interior obstruction, downstream slowdown) не установлено.
Следующий эксперимент должен проверить spatial relevance и stop/restart support
на отдельных независимо описанных треках, а не подбирать фильтр по phase marks.

Tests: окончательный unit/contract набор **72 passed** (19 новых cases, включая
parameterized), existing V9 discovery/renderer/spatial, V10 mapping, streaming,
regime-selection и safety regressions — **56 passed**. В новом тесте исправлено
сравнение packed array с list; production значения при этом не менялись.
AST compare подтверждает отсутствие изменений periodic baseline, deviation
detector и image solver. Git diff защищённых HSMM/phase-count/period/mapping,
offline evaluator и before artifacts пустой. Parameters по marks не подбирались.

## Что ещё не решено и следующий эксперимент

* MEDIUM image restart не доказывает stationary stop: low speed может означать
  поворот/затор; shared metric geometry пока не проверена для реальной камеры.
* Exact zero raw-speed даёт мало STOP evidence; units/quantization и image jitter
  требуют независимой проверки. Не ослаблять zero condition ради этих 40 marks.
* Per-movement priority выбирает все supported releases, даже при малом support;
  sparsity, censored demand и profile-selection bias ещё не моделируются.
* Confidence/uncertainty сохраняются, но frozen HSMM пока использует только
  timestamps. Unknown spatial/causal relation к сигналу не является известным radius.
* Partial snapshots не stitch; temporal provenance storage имеет измеримый overhead.
* K regression на записи 6 и boundary recall regression baseline на записи 19
  зафиксированы, а не скрыты. Изменение K solver запрещено на этом этапе.

Рекомендуемая следующая задача — отдельный bounded эксперимент качества
image-space restart: несколько независимо аннотированных stop/restart/location
траекторий (не фазовые test labels), проверка coordinate/speed units, input-zone
coverage и spatial relevance, затем predeclared quality/abstention rule.
Baseline phase marks оставлять evaluation-only; не подгонять offset/threshold.
Не переходить к HSMM или 2B.2 без нового задания.
