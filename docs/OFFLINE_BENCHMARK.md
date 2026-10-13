# Этап 2A: воспроизводимый offline baseline V9/V10

Запуск из корня Git-копии репозитория с уже установленными зависимостями:

```powershell
python -m scripts.offline_benchmark run --data-dir 'D:\Code\PythonProjects\traffic_phase\data\ручная разметка' --out 'benchmarks/stage2a_20261013' --timeout 90
```

Использовать новый output directory для повторного запуска: существующее
prediction намеренно не переиспользуется. Exit code 1 означает partial/unavailable,
а не выдуманный результат. На каждый файл ограничение inference 90 секунд;
это фиксированный resource gate, не hyperparameter. ZIP не открываются.
Все три исходных JSON читаются streaming V9 по одному. Для provenance считаются
полные SHA256 (добавочный линейный проход), схема исследуется ограниченным
префиксом ≤1MB/16 полных треков. Нет загрузки полного trajectory массива в память.

Worker `infer` имеет только trajectory path, output path и dt; вызов V9 —
`discover_path(source, dt=1.0)`, без marks_path. Directory inference запрещён,
чтобы V9 не просканировал соседние annotations. Seed=0, PYTHONHASHSEED=0,
BLAS/OMP threads=1. Исходный результат V9, включая automatic V10 plan, атомарно
сохраняется в `predictions/` и хешируется **до** оценки. Evaluator читает этот
артефакт, проверяет неизменность хеша, не вызывает fitting или physical mapping.

`baseline_metrics.json` фиксирует Git SHA/branch, source hashes всех core .py,
config digest, Python и версии numpy/scipy/sklearn, пути/размеры/hashes входов,
схему sample, метки, sample ranges и source-specific predictions. Git SHA
generation code является версией измеренного кода, а commit добавления отчёта
может быть следующим: полные code hashes исключают двусмысленность.

## Контракты оценки

Validator отвергает нечисловые/nonfinite/дробные/отрицательные timestamps,
неотсортированные/дублированные метки, missing labels, несовместимые offsets,
orders и local UTC+5. Не сортирует и не ремонтирует разметку молча. Initial
phase до первой метки неизвестна; последняя метка не имеет terminal boundary,
её состояние не экстраполируется. Неполнота truth — warning, не повод отвергать
все полные интервалы. Истина определена на `[first_mark,last_mark)`.

* Phase count — число различных наблюдаемых labels против V9 K. Не доказывает
  полноту аппаратного плана. V10 plan phase count выводится отдельно;
  неизвестное соответствие букв OD-группам не назначается.
* Truth recurrence period — медиана всех соседних возвращений к той же букве.
  Список возвращений сохраняется. При skip/hold это лишь диагностическая
  повторяемость; фиксированный controller period неизвестен.
* Границы оцениваются в абсолютных Unix milliseconds, отдельно для
  `raw_hsmm_segments` и `baseline_segments`. Anchor —
  schedule_base_timestamp_ms с fallback на analysis_base_timestamp_ms.
  Никакого сдвига/warping/modulo alignment к truth. Endpoints first/last mark
  исключены: только внутри имеется два полностью размеченных соседних интервала.
* Matching — monotone one-to-one, максимум числа совпадений в допуске **2s**, затем
  минимум суммарной absolute error. MAE/p95 условны на этих совпадениях;
  их всегда читать вместе с precision/recall, counts, misses/extra boundaries.
  Без совпадений MAE/p95=null, а не 0. Untyped boundaries не подтверждают semantics
  перехода; type-matched оценка ждёт независимого mapping.
* Дополнительно nearest-boundary MAE без допуска (возможен reuse prediction)
  показывает величину промахов. Это диагностическая метрика, не one-to-one.
* Temporal coverage — длительность union непротиворечивых сегментов внутри
  truth range / truth duration. Пробелы UNKNOWN; outside-range не заполняется.
  Coverage не равна ни правильности фазы, ни наблюдаемости лампы. Невалидные
  overlaps/unsorted segments приводят к unavailable.
* Permutation-invariant phase agreement на абсолютной 1s сетке — только diagnostic
  для равной cardinality; optimal mapping хранится как diagnostic_mapping и никогда
  не передаётся inference/physical semantics. На different K diagnostic=null.
  Coverage и число known/total grid points сохраняются отдельно.
* Physical lamp accuracy всегда unavailable: нет независимой per-head truth и
  зафиксированного semantic mapping. K2 без доп. секций и три пользовательские
  OD-группы — внешнее описание этих данных, не automatic A/B/C assignment.

Каждая численная метрика содержит value (или null), n_observations, range_ms,
reason, а границы — знаменатели precision/recall и пары совпадений. Не агрегировать
секунды в независимые статистические наблюдения; набор development/regression,
а не untouched test. Не оптимизировать V9 по этим результатам на этапе 2A.

## Проверка старых fixtures и утечки

V9 `model.py::_discover_from_stream_views` строит fit и baseline из trajectory
streams, затем optional marks_path передаётся только в evaluate. Importing
evaluate не означает чтения меток. В benchmark этот argument не передаётся.
Текущий automatic V10 plan построен из V9 schedule, не из ручного файла.
`scripts/ci_lenina_regression.py` вызывает kinematic discovery без --manual-marks,
но acceptance envelopes и signature expectations основаны на известных
ручных данных — это developer regression и риск настройки под fixture.
Старый `src/evaluate_manual_correct.py` вне актуальной Git-линии оптимизирует
циклический shift и offset против этих меток: не использовать его как независимую
оценку. Анонимное agreement также не является точностью ламп.

`tests/fixtures/lenina_manual_signal_marks.json` начинает timestamps с другой
записи (2025-02-27), не с 19.02.2025. Benchmark сравнивает timestamp intersection
каждой пары с mark fixtures и сохраняет hashes/counts. Нулевое пересечение не
доказывает независимость разработки. Physical fixture задаёт A=turn/B=NS/C=EW
и включает W->N сверх уточнённой пользователем схемы: её не передавать benchmark.
Три новые пары уже известны истории проекта, поэтому их статус остаётся
development/regression независимо от результата проверок утечки.

## Проверки

```powershell
python -m pytest -q tests/test_offline_benchmark.py tests/v9/test_v9_signal_renderer.py tests/v10/test_v10_semantic_mapping.py
```

Новые counterexamples: duplicate timestamps; unsorted/invalid offsets;
initial unknown; terminal unknown; cycle seam; skipped phase; +10s hold vs baseline;
no demand при возможном GREEN; gaps/outside history; missing data; unchanged saved
predictions при замене test labels; запрещённый marks_path; label evaluation в
inference output отвергается. Они фиксируют ограничения без изменения алгоритма.

Этот этап не изменяет HSMM/discovery/mapping, не разрабатывает API/UI и не
применяет existing visualizer fix. Следующий этап 2B требует отдельного задания.

## Фактический baseline 2026-10-13

Артефакты: `benchmarks/stage2a_20261013/baseline_metrics.json` и три исходных
prediction JSON в соседнем каталоге `predictions/`. Версия inference/evaluator
на момент запуска: `a9a3523d531e5f195486da127c067713b082d592`, рабочее дерево
чистое. Данные и config hashes находятся в отчёте. Все три inference завершились
за 15,577 / 9,331 / 12,023s, суммарно 36,931s без таймаутов. Префиксы схемы
содержали 13 / 7 / 14 треков; сам V9 обработал полные JSON streaming:
2735 / 1154 / 1901 trajectories, 2728 / 1104 / 1844 usable events.

| Запись | Truth labels / V9 K / V10 plan K | Предсказанный T, s | Absolute recurrence-period error, s (n возвращений) | Truth duration, s |
| --- | --- | --- | --- | --- |
| 17_2025_2_19_10 | 3 / 3 / 3 | 99,842813 | 0,018187 (16) | 597,936 |
| 19_2025_2_24_16 | 2 / 3 / 2 | 120,028500 | 0,299500 (8) | 524,962 |
| 6_2025_2_14_20 | 2 / 2 / 2 | 99,995248 | 0,129248 (9) | 500,107 |

V9 K совпал в 2/3 сеансов, V10 plan count — в 3/3. Это малый development
набор; такие числа не являются оценкой реальных ламп или generalization.

| Запись / history | Matches / truth / predicted boundaries | Precision / recall, ±2s | MAE / p95 matched, s | Nearest MAE diagnostic, s |
| --- | --- | --- | --- | --- |
| 17 / raw HSMM | 3 / 17 / 18 | 16,67% / 17,65% | 1,257 / 1,7284 | 6,4222 |
| 17 / baseline | 5 / 17 / 18 | 27,78% / 29,41% | 1,3372 / 1,7236 | 2,9450 |
| 19 / raw HSMM | 1 / 8 / 13 | 7,69% / 12,50% | 1,347 / 1,347 | 5,6570 |
| 19 / baseline | 2 / 8 / 13 | 15,38% / 25,00% | 1,2655 / 1,6921 | 6,3045 |
| 6 / raw HSMM | 2 / 9 / 10 | 20,00% / 22,22% | 1,881 / 1,9422 | 3,0281 |
| 6 / baseline | 1 / 9 / 10 | 10,00% / 11,11% | 1,7309 / 1,7309 | 3,6181 |

Raw HSMM: 6/34 truth boundaries matched, precision=6/41=14,63%, recall=17,65%.
Baseline: 8/34 matched, precision=8/41=19,51%, recall=23,53%. Это micro sums
для описания данного набора; не независимая CI по 34 границам. MAE условен на
совпадениях, поэтому маленький MAE не компенсирует низкую recall.
Все временные диапазоны и individual boundary errors сохранены в JSON.

Temporal coverage raw и baseline — 100% на всех трёх размеченных интервалах.
Это лишь заполненный timeline. Diagnostic phase agreement raw/baseline:
17 — 76,42%/91,14%; 6 — 94,40%/93,20%; 19 — unavailable из-за unequal K.
Здесь используются оптимальные перестановки исключительно в диагностике,
никакого физического A/B/C mapping не назначено. Physical lamp accuracy
unavailable во всех трёх случаях.

Проверки: 21 новых unit-case (включая parametrized cases), совместно с
существующими V9 renderer/V10 semantic mapping — **41 passed**. Исходные
predictions сохранены до evaluation; SHA256 проверены неизменными после неё.
Все 40 ручных меток прошли validator, с completeness warnings для неизвестных
краёв. Пересечение timestamps с Git manual fixture — 0 во всех трёх записях;
данные по происхождению остаются development regression.

Выявленные baseline limitations: лишняя третья фаза V9 на записи 19 при K2 truth;
низкая boundary recall на всех записях; periodic baseline и raw history могут
давать разные локальные границы при почти одинаковом периоде; 100% timeline
coverage не обеспечивает evidence confidence; no-demand renderer counterexample
выдаёт RED с confidence=0. В этапе 2B начинать с происхождения/качества entry
и release events, задержек очереди, uncertainty и сохранения UNKNOWN.
Не подгонять глобальный offset или tolerance по результатам этого benchmark.
