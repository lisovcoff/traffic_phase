# Алгоритмическое исправление рекуррентной формулы HSMM

Base `5b84eab96966f2220d85978056b1568d2f17226a`.
Ветка `fix/hsmm-predecessor-duration-20261016`.
Код перед сравнением: `98446c4d94a4a38a9a291d7ff53aab6ec569b7cc`.
До запуска зафиксирован [scope/критерии](HSMM_RECURRENCE_PROTOCOL_20261016.md).
Main не менялся. UI, event selection, infer_period, K criterion, mapping,
thresholds, UNKNOWN semantics и evaluator не менялись.

## Подтверждённые дефекты и исправление

`app/core/v9/decoder.py::decode_cyclic_hsmm` использовал
`lo=max(min_d_current,t-max_d_current)` для endpoint предыдущей фазы. Это
дополнительное неверное ограничение на её длину. В примере A2→B8 на t=10
получалось lo=8,hi=2, хотя предыдущая A имеет допустимые2bins и B длится8.
Теперь `lo=max(1,t-max_d_current)`; допустимость предшественника уже находится
в dp, собственная длительность текущей фазы ограничена min/max. start>0 не даёт
пропустить initial segment. Правила первой частичной фазы2..max bins и последней
полной фазы сохранены, их достаточность для реального observation model не заявлена.

`_duration_penalty` сравнивал номера bins с target в секундах. Теперь duration
равна bins×dt. Коэффициенты/targets/prior не изменены; при dt=1 формула штрафа
точно прежняя. На трёх известных записях dt=1, поэтому этот второй fix сам по
себе не должен менять их результаты.

До fix12/17 новых cases FAIL. После17/17 PASS: A2/B8,A2/B8/C3,A3/B7/C2,
independent exhaustive enumeration при K2/K3, dt.5/1/2, initial0/unknown и
фиксированных seeds20261018/20261019. Oracle сам перечисляет положительные
длительности и суммирует исходные emissions/costs; decoder не генерирует truth.
Это проверка точного оптимизатора существующей модели, не lamp accuracy.
Дополнительно проверены прежние local-history/query/K4/renaming/selection/API
регрессии и lossless cache/запрет label-bearing input:199 уникальных checks PASS.
Логи93+102+21 содержат17 повторённых checks, поэтому не называются216 уникальными.

## Одно сравнение без настройки

Из сохранённых predictions2C восстановлены все TemporalEvent fields/provenance,
entry/release arrays, anchors и quality diagnostics, включая точные selected_event_indices.
Равенство проверено на всех3 caches до fitting. Большие source JSON/ZIP не читались.
Один контроль записи19 **до исправления** точно воспроизвёл старый schedule,
period и K. После фиксации кода выполнены3 обычных cached V9 discovery с прежними
параметрами K2..6/max5/60с,dt1,seed0; hard90с на worker, без новых starts/retries.
Все predictions/hash зафиксированы до единственного запуска неизменного evaluator.
Метки выбраны только по прежним source name/hash; inference не принимает их.

| Запись | K before→after / truth | Raw matched/truth | Predicted raw | Precision | Recall | Matched MAE / p95, с | Nearest MAE, с |
|---|---|---|---:|---:|---:|---|---:|
|17|3→3 /3|15/17→15/17|18→18|.8333|.8824|.7093 /1.4852|1.1052|
|19|2→2 /2|1/8→1/8|8→8|.1250|.1250|1.5460 /1.5460|4.7820|
|6|3→3 /2|3/9→3/9|15→15|.2000|.3333|1.4713 /1.7969|2.8059|

| Запись | Baseline matched/truth before→after | Predicted | Precision | Recall | Matched MAE / p95, с | Nearest MAE, с |
|---|---|---:|---:|---:|---|---:|
|17|15/17→15/17|17→17|.8824|.8824|.7483 /1.7859|1.0859|
|19|1/8→1/8|8→8|.1250|.1250|1.5995 /1.5995|3.9516|
|6|1/9→1/9|15→15|.0667|.1111|1.4184 /1.4184|2.7519|

Все показатели в таблицах неизменны; строки before/after полностью равны.
Raw итого19/34,19/41 predicted, precision46.34%,recall55.88%.
Baseline17/34,17/40 predicted,precision42.50%,recall50.00%.
MAE/p95 условны на matched, поэтому отдельно показан nearest MAE по всем truth.
Полные знаменатели, reasons и timestamp ranges — в verification.json/comparison.json.
Temporal model-history coverage во всех6 строках1.0; это не наблюдаемость ламп.
Period errors17/19/6=.01819/.29950/.12925с, неизменны.
Cached worker elapsed13.195/5.922/13.868с, таймаутов0. Старые wall32.488/19.112/
23.858с включали ingestion raw JSON: сравнивать их как ускорение decoder нельзя.
Новый control cached5.460с также отдельный scope; полный CPU profile не заявляется.

Почему нет роста выбранной точности: у17 ни одна objective не поменялась;
у19 изменились K4/K6, у6 — K2/K5/K6, но итоговые K и все выбранные schedules
остались прежними. Например19/K4 objective−1848.327→−1845.249,6/K2
−3741.466→−3740.724. Сравнение сделано внутри одного и того же evidence dataset,
не между разными записями. Это изменение кандидатов не объявляется правильными
физическими сигналами или основанием заменить выбранный K вручную.

## Вывод и следующий пункт

**Исправлена математика, реальная точность не выросла.** Никакой дополнительной
настройки по результату не сделано. Исторические результаты и старый recovery
gate FAIL сохранены;2D.1 не принят, experimental opt-in/default-off. Физические
состояния UNKNOWN. Эти записи development, не независимый holdout.

Следующий конкретный алгоритмический кандидат: в `fit.py::em_fit` K3 split-seeds
добавляются в seed_candidates после построения unique, а оценочный цикл читает
только unique. Нужен отдельный независимый structural counterexample генерации/
реального посещения кандидатов, затем ограниченное исправление при подтверждении.
В этом цикле fit.py не изменён и эта гипотеза не использована для подгонки записи6.
Далее важен выбор periodic seed/HSMM refinement и observation model; calibration
нужна для проверки реальной семантики/задержек, не для оправдания арифметических
дефектов. Повторять готовый UI либо ждать supplier для таких исправлений не нужно.
