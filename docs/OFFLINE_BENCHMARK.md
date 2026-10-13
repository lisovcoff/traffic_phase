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
