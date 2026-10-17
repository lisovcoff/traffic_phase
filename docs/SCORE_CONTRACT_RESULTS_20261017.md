# Согласованный score модели — D2+D3, 2026-10-17

Base: `e41c075d7c9cef7c6eb512cfadf7d29d435cafba`.
Ветка: `fix/coherent-fit-score-20261017`.
Code/config до нового прогона: `787c9776e47675ab9dede456330b65850f0ef799`.
Main: `a005a2521f62ce3b2c9f9d52f9f0d73913754e01`, без изменений.
[Протокол](SCORE_CONTRACT_PROTOCOL_20261017.md) зафиксирован до сравнения.

В `app/core/v9/fit.py` исправлены два воспроизведённых дефекта:

* D2: decoder score относился к входным шаблонам, payload возвращал новые.
  Теперь score пересчитан для возвращённых labels/probs, без второго decoding;
  лучшая итерация выбирается по согласованному penalized objective. Исходный
  `decoder_input_objective` сохранён отдельно. Независимый пример до исправления:
  -31.1996767597 вместо фактического -13.1925242351.
* D3: seed и refined сравнивались по разным определениям score. Теперь публичный
  `em_fit.score` всегда alias `data_loglik`/`pointwise_loglik`; штрафной objective
  отдельный, null для seed. `candidate_metrics.objective` всегда data likelihood.
  Для одного path/probs прежние BIC21.3837147913/22.8837147913 стали одинаковыми
  21.3837147913. Score-only models отвергаются; исторический pointwise alias допустим.

Это явное изменение основы приблизительного K-критерия, а не простое имя поля.
Число параметров K*S, log(N*S), recurrent penalty5/cycle, support eligibility,
redundancy и seed/coherence/ensemble selection rules сохранены. Это не marginal
likelihood, calibrated confidence или вероятность лампы. Модель occupancy и её
ограничения не исправлялись этим заданием. Внутренний refinement.score остаётся
штрафным и явно маркирован; публичный score — data LL. Потребителям старых
diagnostic scores нужно учитывать эту смену семантики.

Проверки: до исправления оба независимых counterexamples FAIL. После — 222 PASS
и 6 strict XFAIL в основной выборке, ещё3 PASS в затронутых discovery callers:
**225 уникальных PASS**,6 известных XFAIL для5 оставшихся дефектов D4-D8.
Проверены независимые суммы при K2/K3, dt=.5/1/2, обратный порядок stale/corrected
итераций, отсутствие дополнительного decode/мутации входов, uniform criterion,
K4 recovery/renaming, бюджет, lossless cache, запрет labels в worker, state/query
UNKNOWN и существующие потребители. Один прежний Starlette/httpx deprecation
warning; зависимости не устанавливались. Старых ожиданий цветов не меняли.

## Единственное development-сравнение

Нативный unchanged control записи19 до правок: schedule/K/period **exact**,
6.702с. Затем один worker на каждый из трёх сохранённых event caches. Три output
SHA зафиксированы до доступа evaluator к annotations. Сам evaluator/±2с не менялись.
Исходные JSON/ZIP не читались, event selection/anchors exact. Эти3 записи —
development, не независимый holdout.

Во всех строках ниже метрики **до = после**. M/T/P = matched/truth/predicted;
MAE/p95 относятся только к matched, nearest MAE — отдельная diagnostic метрика.

| Запись / history | M/T/P | Precision | Recall | Matched MAE / p95, с | Nearest MAE, с | Temporal coverage |
|---|---:|---:|---:|---:|---:|---:|
|17 raw|15/17/18|83.33%|88.24%|0.7093 / 1.4852|1.1052|100%|
|17 baseline|15/17/17|88.24%|88.24%|0.7483 / 1.7859|1.0859|100%|
|19 raw|1/8/8|12.50%|12.50%|1.5460 / 1.5460|4.7820|100%|
|19 baseline|1/8/8|12.50%|12.50%|1.5995 / 1.5995|3.9516|100%|
|6 raw|3/9/15|20.00%|33.33%|1.4713 / 1.7969|2.8059|100%|
|6 baseline|1/9/15|6.67%|11.11%|1.4184 / 1.4184|2.7519|100%|

| Запись | K до→после / annotation K | Ошибка периода, с (неизм.) | Candidates | Worker wall до→после, с |
|---|---|---:|---|---:|
|17|3→3 /3|0.018187|K2..6,5/5|17.428→16.879|
|19|2→2 /2|0.299500|K2..6,5/5|7.086→7.433|
|6|3→3 /2|0.129248|K2..6,5/5|16.324→16.968|

Runtime включает cached canonical discovery/import/validation/export; это не
профиль и не сравнение скорости raw ingestion. Число запусков не позволяет
утверждать ускорение/замедление. Все поиски complete, timeout нет. Бюджеты:
60с cooperative K search,90с hard worker,360с control+3 workers maximum.

Суммарно raw19/34 truth и19/41 predicted (P46.34%,R55.88%); baseline17/34 и17/40
(P42.50%,R50%). Нет улучшения и нет новых регрессий в итоговых histories.
Все15 K-specific fitted labels/probs exact относительно D1. Изменённые scores
не поменяли победителей: например запись19 K2/K3 criterion4145.993/4202.058 →
4117.329/4160.560; запись6 K2/K3 7714.699/7676.898 →7665.556/7575.006.
Более широкий margin в пользу неверного K3 записи6 **не является confidence**.
У записи17 eligible K2/K3 выбраны seed paths, их data LL criterion не изменился.
Неподдержанные кандидаты сохранены с причиной eligibility; serialized null
selection score соответствует прежнему infinity, а не отсутствующему fit.

Structural gate **PASS**; development benefit **FAIL_NO_GAIN**. Подгонки после
результатов нет. Temporal coverage — покрытие модельной истории, не наблюдение
камерой/лампами. Physical states UNKNOWN; 2D.1 **FAIL/default-off** сохранён.

## Проверяемые материалы и следующий шаг

Полные counts/ranges/reasons и metrics: `benchmarks/score_contract_20261017/comparison.json`.
Predictions доступны отдельными файлами там же в `predictions/`; temporal events
не дублируются, указаны SHA исходных lossless caches. Logs/commands/readonly
verifier/diff/manifest и компактный ZIP: `evidence/score_contract_20261017/`.
Verifier проверяет неизменность protected code, old artifacts, period/selection,
main, output hashes и все score identities, не вызывает inference/evaluator.

Следующий отдельный алгоритмический шаг — D7: корректные одинаковые ranks для
ties в 3→2 redundancy с независимым тестом перестановки колонок; затем D6:
совместные shared-movement signatures. D4/D5 ensemble и D8 censored baseline
тоже открыты. Ни одна из этих правок не сделана скрыто в текущем сравнении.
Независимая event/lamp calibration и validation остаются необходимы для приёмки
точности продукта; исправление D2+D3 само по себе её не подтверждает.
