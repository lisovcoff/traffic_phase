# Один предобъявленный эксперимент A–D, этап 2B.1

Основа — `fix/stage2b1-temporal-evidence-20261013`:
**afcfaa2b38e106201d7e819570425acfc4c5487f**, producer
`161f32fd42ce80cca01bb74c0a00988d6969382a`.
Runner перед sealing — **9bbaeeb4268464ea90a16406bc95d8a73ee76062**,
на отдельной ветке `diagnostic/stage2b1-ablation-20261013`.
Production branch/default и main не изменены. Scope — только запись
`6_2025_2_14_20.json`; больших архивов и трёхфайлового benchmark нет.

## Протокол и неизменяемые данные

`manifest.json` создан до любого fitting; `manifest_seal.json` содержит SHA256.
Exclusive file creation запрещает переписывать manifest, events, attempt ledger
и predictions. Перед/после fitting проверяются seal и input hashes.
Файлы `attempt_A..D.json` показывают **ровно четыре** variant pipeline invocations,
по одной на вариант. Внутри каждого неизменённый solver сравнивает K2/K3,
со своими штатными initialization/EM iterations. Это не четыре отдельных EM steps.

Первый preflight завершился до manifest и fitting: guard ожидал `regime_detection=None`,
но сохранённый результат сериализует `global_fallback/full_input`. Исправлена
только эта проверка до sealing. Ни параметров, ни predictions на этом шаге не было.
Повторных fitting attempts нет.

Варианты заранее заданы пользователем, без отбора по annotations:

* A: saved permission_per_stream selected events, 1107/11 movements.
* B: A без одного S->N RELEASE (track 4632532), 1106/10 movements.
* C: тот же producer extractor с первым outgoing observation вместо track end
  как upper image-candidate bound. Guards/dedup/selection прежние; 1139/11.
* D: A с legacy selected RELEASE timestamps только E->W; 1089/11.

Общие параметры:

```text
analysis = schedule = event anchor: 1739545137142.0 ms
recording start: 1739545136544.0 ms
T: 99.99524773335186 s (из saved prediction, не truth)
extent: 3656.214 s; occupancy length: 3657
dt: 1 s; seed: 0; OMP/BLAS/MKL threads: 1; PYTHONHASHSEED: 0
K solver: unchanged defaults, same demand/topology streams, same K2/K3 candidates
```

Runtime adapters делегируют неизменённым functions общий occupancy extent,
recording_end_s для complexity penalty и baseline extent. Без них C могла бы
неявно изменить длительность данных. `infer_period` на fitting не пересчитывается:
возвращаются один сохранённый T и period_info для всех вариантов. Никаких offset
alignment, изменений thresholds, HSMM/K solver/mapping/uncertainty нет.
Все functions/source blobs и defaults signature фиксируются в manifest.

В model prediction хранится диагностический selected-only event sidecar.
Invocation metadata поэтому не byte-identical production. У C `release_streams`
slot диагностического gateway содержит selected permission, включая 64 proxies:
legacy-named release counters внутри prediction не являются чистым RELEASE count.
Истина о composition/types — immutable `events_C.json` и manifest. Эти counters
не входят в likelihood/selection; это ограничение bookkeeping adapter, не
дополнительный фазовый признак. D legacy quality/method metadata описывает origin;
модель использует только movement/timestamps. Другие movements не меняются.

## Контроль, тесты и отсутствие утечки

A **точно** совпал с saved prediction по всем десяти заранее заявленным полям:
schedule (включая raw/baseline), phase_model_selection, period_inference,
physical plan, analysis/event/schedule/recording anchors, recording duration,
anomaly diagnostics. `control_reproduction.json` подтверждает exact JSON equality.
При расхождении runner обязан был остановиться после A.

Шесть target tests прошли; commands/stdout в `logs/unit_command.json`, `unit.log`:
B удаляет только заявленное событие, D подменяет только E->W, C меняет только
upper argument, labels read guard, exclusive manifest и evaluation-before-seal
запрещены. Guard запрещает annotation filenames во время prepare/run/fit.
Ни marks_path, ни annotation payload модели не передаются.

`predictions_seal.json` создан после A–D; единственный `evaluation_attempt.json`
создан только после проверки всех четырёх hashes. Затем неизменённый
`app/core/offline_benchmark.py` оценил все варианты в одном проходе.
Допуск ±2s и mapping policy не менялись. Annotation digest зафиксирован после
sealing. Predictions hashes после evaluation не изменились.

Команды, воспроизводящие последовательность (на новом experiment output):

```powershell
python -m pytest -q -p no:cacheprovider tests/test_temporal_ablation_2b1.py
python -m scripts.temporal_ablation_2b1 prepare
python -m scripts.temporal_ablation_2b1 run
python -m scripts.temporal_ablation_2b1 evaluate
```

Driver намеренно отказывается повторять команды в заполненном output directory.
Runtime logs каждого variant — `logs/A.log`...`D.log`. Это fitting-only время,
не full ingestion benchmark: подготовка C/D происходила до manifest.

## Saved candidate diagnostics и чувствительность модели

| Variant | Events / occupancy dimensions | K2 objective | K3 objective | K3−K2 selection score | Итоговый K | Fit runtime, s |
| --- | --- | --- | --- | --- | --- | --- |
| A | 1107 / 11 | −3741,465524 | −3572,101666 | −39,283098 | 3 | 5,274 |
| B | 1106 / 10 | −3700,014292 | −3530,752468 | −50,634424 | 3 | 5,432 |
| C | 1139 / 11 | −3858,244021 | −3813,599911 | +210,156398 | 2 | 5,720 |
| D | 1089 / 11 | −3663,246452 | −3632,052156 | +237,056025 | 2 | 5,493 |

Objective и selection_score — разные величины: selection_score включает
approximate BIC и complexity/support penalties. Сравнивать K2 с K3 можно
**внутри** варианта. Абсолютные objectives между строками не интерпретируются
как comparable likelihood: evidence и у B размерность различны.
Полные candidate diagnostics (не только итоговый K) находятся в `fit_*.json`.

B raw/baseline сегменты идентичны A. Исчезновение sparse S->N не устраняет K3
при остальном evidence A; это не доказывает отсутствия interactions с другими
факторами. B одновременно удаляет событие и occupancy column — их отдельный
вклад этим опытом не разделён.

C: guards/selection code сохранены, но отсутствие S->N RELEASE включает
fallback на **64 CROSSING_PROXY**. E->W RELEASE 26→8; меняются и другие candidate
timestamps/counts. Наблюдается чувствительность всего bound→selection пути.
Нельзя приписать K2 чистому смещению upper bound при фиксированном RELEASE наборе
или отдельно выбрасыванию late release: selection-mediated composition смешана.

D: другие 10 movements имеют идентичные event hashes A. Только E->W 26→8 и
его timestamps меняются, dimensions/anchors/T/extent/settings фиксированы.
Следовательно, **в этом детерминированном вычислительном контексте** подмена
E->W evidence достаточна для K3→K2. Это не доказывает, какой E->W event виноват,
не отделяет число событий от их времён и не устанавливает реальную структуру
светофора. Не утверждается, что D является корректным production-вариантом.

## Единственная post-seal оценка границ

Truth range: 1739545472172..1739545972279 ms, 500.107s.
Девять внутренних truth boundaries, endpoints исключены как в прежнем evaluator.
Temporal coverage raw/baseline =100% у всех вариантов (поддержка timeline, не
correctness и не observability ламп). T одинаков, period error одинаков 0,129248s.

| Variant/history | Matched/truth/predicted | Precision / recall | Matched MAE / p95, s | Nearest MAE, s |
| --- | --- | --- | --- | --- |
| A/raw | 3/9/15 | 20,00% / 33,33% | 1,4713 / 1,7969 | 2,8059 |
| A/baseline | 1/9/15 | 6,67% / 11,11% | 1,4184 / 1,4184 | 2,7519 |
| B/raw | 3/9/15 | 20,00% / 33,33% | 1,4713 / 1,7969 | 2,8059 |
| B/baseline | 1/9/15 | 6,67% / 11,11% | 1,4184 / 1,4184 | 2,7519 |
| C/raw | 3/9/10 | 30,00% / 33,33% | 1,7957 / 1,9327 | 2,8059 |
| C/baseline | 3/9/10 | 30,00% / 33,33% | 1,6019 / 1,7065 | 2,5278 |
| D/raw | 2/9/10 | 20,00% / 22,22% | 1,8810 / 1,9422 | 3,0281 |
| D/baseline | 1/9/10 | 10,00% / 11,11% | 1,6736 / 1,6736 | 3,3074 |

C/D дают K2, но timing не улучшается однозначно: у D raw recall ниже A,
nearest errors больше. Matched MAE условен на совпадениях. Никакой вариант
не отобран по этим метрикам. Phase agreement в evaluation — только анонимная
diagnostic metric; per-lamp accuracy unavailable. Dataset остаётся development.

## Семантика и пределы

RELEASE — image restart proxy без подтверждённой стоп-линии или units,
а не точное переключение GREEN. C CROSSING_PROXY — наблюдаемый zone transition,
не стоп-линия. D включает два старых metadata-dwell времени, качество которых
новый default не принимает; их диагностическая подмена не легализует эти события.
Независимые descriptions автомобильных остановок/ускорений отсутствуют.

Проверяемые факты — equality A, состав A–D, fixed scalars, scores/K и post-seal
метрики. Чувствительность модели — B/C/D ответы. Ограниченный причинный вывод
допустим только о вычислительном эффекте D в этом фиксированном контексте;
для C direct timing vs selection effects не разделены. Сигнальная семантика
и истинность RELEASE остаются неизвестными.

Следующее отдельное задание: независимая проверка смысла E->W restart candidates
и координат/units. Не менять default, thresholds или выбрать C/D на основе
этих девяти boundaries. Эксперимент завершён; к 2B.2 не переходили.
