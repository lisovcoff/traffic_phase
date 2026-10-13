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
