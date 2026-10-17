# D7: исправлены ранги равных значений в redundancy

Base: `b84e08b1d141e07da8e524080176c64f205233cc`.
Ветка `fix/tie-invariant-redundancy-20261017`; code/config до сравнения:
`a57ae53f7b9e1f336ee0293a1425ac79264ee2a1`.
[Заранее заданный протокол](TIED_RANKS_PROTOCOL_20261017.md).

В `app/core/v9/fit.py::_rank_correlation` двойной argsort назначал разные ранги
одинаковым occupancy probabilities. Простая перестановка колонок меняла corr
с -1 до -.5 и могла менять решение 3→2. Оба независимых теста до исправления FAIL.
Теперь используются средние ранги для **точных** ties (`scipy.stats.rankdata`,
существующая зависимость). Правильная корреляция в трёхэлементном примере -.5
при всех6 перестановках. Fuzzy tolerance не вводилась; прежний std/short guard
с нулевой convention, веса, пороги и весь остальной redundancy code сохранены.
Единственная изменённая production-функция — `_rank_correlation`, плюс import.

После исправления: **240 уникальных PASS**,4 strict XFAIL (D4,D5,D6,D8 остаются).
Основная выборка235 PASS/4 XFAIL; отдельные5 PASS —3 затронутых discovery checks
и2 handcrafted merge/distinct tests. Новый counting-based oracle независим от
scipy/sorting. Проверены все120 перестановок полного пятиколоночного witness:
decision/pair/features неизменны; no-ties parity, constants, exact-vs-near ties,
input nonmutation. Только структурная корректность, не приёмка merge policy.
Предупреждение Starlette/httpx прежнее; установки зависимостей нет.

## Один frozen development run

Unchanged native control записи19 до изменения production: schedule/K/period
exact,6.547с. Затем один cached worker на каждый из3 файлов после code commit.
Исходные большие JSON/ZIP не читались. Inputs/selection/anchors/config frozen;
все output SHA зафиксированы до единственного unchanged evaluator pass (±2с).
Все5 K2..6 рассмотрены на каждой записи, timeout нет; лимиты60с cooperative
search,90с hard worker,360с control+3 maximum. Записи остаются development.

**До = после во всех строках метрик:** M/T/P = matched/truth/predicted.

| Запись/history | M/T/P | Precision / Recall | Matched MAE / p95, с | Nearest MAE, с | Coverage |
|---|---:|---:|---:|---:|---:|
|17 raw|15/17/18|83.33% /88.24%|.7093 /1.4852|1.1052|100%|
|17 baseline|15/17/17|88.24% /88.24%|.7483 /1.7859|1.0859|100%|
|19 raw|1/8/8|12.50% /12.50%|1.5460 /1.5460|4.7820|100%|
|19 baseline|1/8/8|12.50% /12.50%|1.5995 /1.5995|3.9516|100%|
|6 raw|3/9/15|20.00% /33.33%|1.4713 /1.7969|2.8059|100%|
|6 baseline|1/9/15|6.67% /11.11%|1.4184 /1.4184|2.7519|100%|

| Запись | K до→после / annotation K | Period error, с (неизм.) | Worker wall до→после, с |
|---|---|---:|---:|
|17|3→3 /3|.018187|16.879→15.685|
|19|2→2 /2|.299500|7.433→6.645|
|6|3→3 /2|.129248|16.968→14.924|

Worker scope — cached discovery/import/validation/export, не raw ingestion
и не CPU profile. Один прогон не доказывает ускорение. Все15 per-K fits/scores
exact; периоды, selection и итоговые raw/baseline paths exact. Полные ranges,
counts/reasons и метрики: `benchmarks/tied_ranks_20261017/comparison.json`.

Rank features действительно изменились. У17 для пар[0,2]/[1,2]/[0,1]:
-.366667/-.5/-.25 → -.130158/-.366070/-.075. Candidate pair[0,2] и detected=false
сохранились. У6 [1,2]/[0,2]/[0,1]: .554545/-.790909/-.654545 →
.689677/-.536585/-.441929; pair[1,2],detected=false также сохранились.
У19 K2, redundancy не вызывается. Эти диагностические изменения не изменили
окончательный K; вручную подбирать оставшиеся guards по записи6 нельзя.

Итого raw19/34 truth,19/41 predicted (P46.34%,R55.88%); baseline17/34,17/40
(P42.50%,R50%). Structural gate **PASS**, development benefit **FAIL_NO_GAIN**.
Новых итоговых регрессий нет, улучшения точности тоже нет. Coverage отражает
модельную историю, не наблюдаемость ламп. 2D.1 **FAIL/default-off**, physical
UNKNOWN, main/state/query/period/selector/evaluator/historical artifacts сохранены.

Commands/logs/readonly verifier/diff/seal/ZIP: `evidence/tied_ranks_20261017/`.
Predictions отдельными файлами в `benchmarks/tied_ranks_20261017/predictions/`,
ссылаются на исходные event caches по SHA без повторной упаковки26MB событий.
Следующая отдельная задача — D6, support совместных shared-movement signatures;
затем D4/D5 ensemble и D8 censored baseline. Независимая event/lamp calibration
и отдельная validation открыты. Эти следующие правки здесь не реализованы.
