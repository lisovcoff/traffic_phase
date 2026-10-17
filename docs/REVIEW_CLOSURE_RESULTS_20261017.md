# Закрытие подтверждённых дефектов ревью, 2026-10-17

Base: `c414c5ef486b145cb7605017fbeabee3e68237b0`.
Ветка `fix/remaining-review-defects-20261017`.
Code/config до новых результатов: `9e987c804c1880b991f5298da27f71224778d8c8`.
Main `a005a2521f62ce3b2c9f9d52f9f0d73913754e01` не изменён.
[Протокол до fitting](REVIEW_CLOSURE_PROTOCOL_20261017.md).

**Все8 подтверждённых механизмов Astra теперь имеют проходящие regression tests.**
Это не утверждение, что найдены все ошибки проекта или достигнута требуемая
точность. Все13 cases из tests/test_v9_independent_review.py проходят без XFAIL.
Изначальные external artifacts/логи и исторические FAIL сохранены.

| Finding | Исправление / происхождение |
|---|---|
|D1|Split seeds генерируются до dedup/fitting; ранее35fc8fe899193bea4440b3e910e4f49782563836.|
|D2/D3|Согласованные params/score snapshots, единый data LL criterion; ранее787c9776e47675ab9dede456330b65850f0ef799.|
|D7|Average ranks точных ties, permutation invariance; ранееa57ae53f7b9e1f336ee0293a1425ac79264ee2a1.|
|D4|Теперь producer сохраняет group_streams без изменения clustering. _fuse_seed_views находит уникальное максимальное соответствие по общим streams, требует ненулевые overlaps/совместимый cyclic order. Неоднозначные identity/antipodal onsets → нет ensemble, с причиной. Midpoint по короткой дуге, группы переставляются вместе с onsets. Seed provenance сохраняется и после refinement.|
|D5|Все источники конкурируют по прежнему model_quality; убрана привилегия ensemble и .002 override. Exact tie → первый retained source; внутри seed прежний refinement margin .0001 сохранён.|
|D6|Активная fitted signature сравнивается с каждым конкурентом по совместным координатам, с прежними .08/1.15. AB/AC/BC допускаются без exclusive stream. Duplicate/ничтожные различия/inactive rows не дают support. Старые exclusive counts и новые pairwise witnesses разделены. Это model support, не calibrated identifiability/лампы.|
|D8|Baseline берёт только contiguous phase changes. First segment, gaps/continuation не создают onsets. При missing/undefined onsets — пустой baseline и structured unavailable, без raw/zero fallback. Канонический model сохраняет diagnostics, raw history доступна отдельно. Legacy two-item helper API сохранён.|

Gemini повторно учтён как набор гипотез без code review: demand/motion/visibility,
recurring plan/local history и hardware alternatives разделять. Его fixed−2с,
queue⇒RED/flow⇒GREEN, exclusive event constraints, профильные «confidence» и
гарантии anchored history не перенесены на реальные RELEASE. Нового decoder/
likelihood/prior/local-history эксперимента здесь нет. 2D.1 **FAIL/default-off**.

## Проверки

**291 уникальный PASS**: финальная основная выборка269, ещё20 V9 discovery
checks и2 handcrafted redundancy checks. До фикса4 независимых cases FAIL.
Новые tests покрывают реальные producer memberships, matching через wrap/time
origin, ambiguous/global assignment, cyclic disagreement, antipodes, общий
quality/ties, shared signatures/переименование/дубликаты/tiny differences,
censored/gapped/invalid histories и UNKNOWN настоящего V9 configured query.
Старые K2/K3/K4, missing events/blocked stream/jitter, JSON/ZIP, query и evaluator
checks проходят. Один прежний Starlette/httpx warning; установки зависимостей нет.

Расширенная проверка выявила2 устаревших assertions, не скрытые XFAIL:

* `"NS" not in json.dumps(result)` ошибочно ловил `MULTIPLE_UNSUPPORTED_PHASES`.
  Теперь проверяются настоящие нормализованные stream identities/phase names
  и отсутствие topology cap.
* Local-regime test неявно объединял recordings с7200с gap, против принятого
  session contract. Теперь fixture содержит два adjacent периода в одной
  непрерывной capture; rebase delta вычисляется один раз. Сам isolation code
  exact относительно base, никаких merge guards не ослабляли.

Лог18 PASS/2 FAIL сохранён;2 исправленных cases отдельно прошли. Цветовые
ожидания не менялись. Test maintenance — до новых development результатов,
причины/доказательство неизменности source_scope в test_maintenance.json.

## Единственное реальное development-сравнение

Unchanged control19 до production edits: exact schedule/K/period,6.747с.
Затем один worker на каждый из3 lossless event caches; raw JSON/ZIP не читались.
Hashes всех predictions sealed до единственного unchanged evaluator pass ±2с.
Selection/anchors/period inference exact. Все K2..6 рассмотрены, timeouts0.
60с cooperative search/90с hard worker/360с maximum control+3; без tuning/retries.
Изменения объединены по просьбе пользователя: этот run не является абляцией
для причинного разделения вклада D4/D5/D6. Structural witnesses дают отдельные
проверки механизмов. Все15 выбранных per-K labels/probs/quality exact к base;
итоговые raw paths тоже exact, поэтому выигрыша raw нет.

| Запись | K до→после / annotation K | Period error, с (неизм.) | Worker wall до→после, с |
|---|---|---:|---:|
|17|3→3 /3|.018187|15.685→16.642|
|19|2→2 /2|.299500|6.645→6.724|
|6|3→3 /2|.129248|14.924→14.170|

Runtime — cached discovery/import/validation/export, не raw ingestion/CPU
profile; по одному повторению нельзя заявлять ускорение. Записи development,
не untouched holdout. M/T/P=matched/truth/predicted. Precision/recall/counts
ниже **до=после**, ошибки приведены до→после:

| Запись/history | M/T/P | Precision / Recall | Matched MAE, с | Matched p95, с | Nearest MAE, с | Coverage |
|---|---:|---:|---:|---:|---:|---:|
|17 raw|15/17/18|83.33% /88.24%|.7093→.7093|1.4852→1.4852|1.1052→1.1052|100%|
|17 baseline|15/17/17|88.24% /88.24%|.7483→.7198|1.7859→1.7218|1.0859→1.0859|100%|
|19 raw|1/8/8|12.50% /12.50%|1.5460→1.5460|1.5460→1.5460|4.7820→4.7820|100%|
|19 baseline|1/8/8|12.50% /12.50%|1.5995→1.5995|1.5995→1.5995|3.9516→4.3177|100%|
|6 raw|3/9/15|20.00% /33.33%|1.4713→1.4713|1.7969→1.7969|2.8059→2.8059|100%|
|6 baseline|1/9/15|6.67% /11.11%|1.4184→1.4184|1.4184→1.4184|2.7519→2.7519|100%|

Итого raw19/34 truth,19/41 predicted (P46.34%,R55.88%); baseline17/34,17/40
(P42.50%,R50%). **Нет прироста boundary matches.** Baseline17 немного лучше по
matched errors; у19 nearest MAE **регрессирует +.366107с**. Исключение ложного
start-onset меняет baseline centers; оставлять этот псевдо-onset ради лучшей
известной метрики нельзя. Настройки после результата не менялись.

Structural closure **PASS**; development quality benefit **NOT_MET / MIXED**,
реальная приёмка **NOT_READY**. Ошибка K записи6 сохраняется. Physical states
UNKNOWN, temporal coverage означает model-history coverage, не lamp accuracy
или camera observability. Ни одна таблица не подтверждает правильность ламп.

## Что дальше к рабочему продукту

Кодовые ошибки review исправлены, но они не объяснили главные реальные ошибки
границ. Доминирующий следующий вопрос — observation model: связь method-specific
vehicle evidence с логическими переходами, спрос/блокировки/permissive movement,
неизвестная задержка и покрытие. Новая корректная likelihood должна проверяться
отдельным объявленным экспериментом, с prior dependence/UNKNOWN и независимой
calibration/validation, а не универсальным сдвигом или выбором по этим34 меткам.
Существующий failed local decoder не включать. Independent sync/delay/geometry/
supplier units остаются открыты; доступное H1 video не является полным truth
всех ламп трёх перекрёстков. Проект не объявлен невозможным: JSON/ZIP pipeline
и типовые structural cases работают, но точная местная история/аппаратные секции
ещё не прошли продуктовую приёмку.

Predictions/comparison: `benchmarks/review_closure_20261017/`.
Полные ranges/counts/reasons, commands/logs/readonly verifier/diff/seal/ZIP:
`evidence/review_closure_20261017/`. Ссылки на исходные temporal-event caches
с SHA сохранены; многомегабайтные события повторно не упакованы.
