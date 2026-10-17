# Внешние ревью: что подтверждено и что делаем дальше

Update2026-10-17: все8 подтверждённых D1-D8 теперь закрыты regression tests,
см. [финальный status/реальные ограничения](REVIEW_CLOSURE_RESULTS_20261017.md).
291 уникальный PASS, review XFAIL0. Raw19/34 и неверный K3 записи6 остаются;
baseline19 nearest error ухудшился после устранения censored onset. Это не
приёмка точности/2D.1. Таблица и следующие шаги ниже — исторический intake,
а не утверждение, что эти восемь исправленных механизмов всё ещё открыты.

Base `b7675c70bf191a20454fe974baa18cc161f01856`.
Ветка `fix/review-seed-flow-20261017`.
Исходные Gemini/Astra и весь маленький ZIP сохранены без редактирования:
`evidence/review_intake_20261017/`. Проверены hashes всех членов manifest Astra,
совпадение отдельно присланных report/patch с ZIP и LF hashes всех8 просмотренных
им исходников с нашей базой. Чужие логи не называются нашими тестами/запусками.

## Astra: локальная проверка выводов

Полностью прочитан patch, тесты и runner; внешние installation/runner команды
не исполнялись. Из пакета перенесены проверенные unit counterexamples, применён
только D1 diff после git apply --check. Реальные runs выполнены нашим отдельным
runner, со своими исходниками, freeze и доступными локально original annotations.

| ID | Механизм и локальное свидетельство | Решение |
|---|---|---|
|D1|`em_fit`: unique построен до добавления K3 split-seeds. Ни один parent не посещался; dt.5/1/2 и реальный refinement воспроизводят дефект.|Исправлено: существующий dedup перемещён после генерации, никаких новых правил.|
|D2|`_fit_from_initial_labels`: score под old_probs возвращается с new_probs. Независимый пересчёт −13.192524 против возвращённых−31.199677.|Подтверждено, открыт отдельный score/params fix.|
|D3|`candidate_metrics`: seed score=data LL, refined score=penalized decoder score. Один path/probs даёт BIC21.383715 против22.883715.|Подтверждено, требует явного общего selection objective.|
|D4|`em_fit`: sorted zip фаз +линейное среднее не circular-equivariant. Общий сдвиг10с меняет исходный ансамбль[25,75]→[0,50].|Подтверждено; один circular mean без group matching недостаточен.|
|D5|Special ensemble preference исключает pure release/entry независимо от разницы Q. Контроль Qrelease−.05 лучше Qensemble−.20, но побеждает ensemble.|Подтверждено; нужен общий выбор по объявленному quality/tie rule.|
|D6|Exclusive-stream support объявляет AB/AC/BC unsupported=3, хотя joint emission signatures различны.|Подтверждено как неправильное отождествление exclusive support с различимостью. Distinct fitted rows сами по себе не доказывают физическую/логическую истинность K.|
|D7|Double argsort раздаёт разные ranks ties: перестановка колонок меняет correlation−1→−.5 и отдельный полный redundancy decision False→True.|Подтверждено; существующий renaming test не охватывал ties.|
|D8|`periodic_baseline_from_segments` включает цензурированный start0 как onset; из истинных onsets30/10 получается32.951672/10.|Подтверждено; endpoint окна не событие переключения.|

Наш before: **12 FAIL,1 PASS** с --runxfail, все8 механизмов воспроизведены.
После D1: **208 PASS,8 strict XFAIL**. Восемь XFAIL — восемь cases для семи
ещё открытых дефектов; это не прохождение восьми требований. Включены recurrence
oracle, cached lossless/no-label checks, K4/renaming/shared/budgets, state/query,
event contracts, API, product/HTML и unchanged evaluator tests. Новые зависимости
не установлены; только прежнее предупреждение Starlette/httpx deprecation.

AST-проверка: весь production diff — перенос четырёх прежних AST nodes в em_fit
после существующего if k==3 и комментарий. Остальные функции fit.py идентичны.
Decoder, objective rules, thresholds, selector, period, mapping, uncertainty,
query contract, evaluator и historical artifacts не менялись.

## Gemini: архитектурные идеи и неподтверждённые гарантии

Gemini прямо указал, что не читал этот код. Поэтому его текст — архитектурная
гипотеза. Полезны разделение demand/visibility/motion, recurring plan/local history,
shared movements и hardware alternatives. Эти направления уже согласуются с
product contract; они не означают, что предложенный EC-AHSMM проверен.

Не принимаем без отдельной модели/данных:

- RELEASE «в первые4с GREEN», универсальный сдвиг−2с, clearance2..4с, min phase6..8с,
  окно hold+20с и sigma4с не установлены на этих источниках. Самостоятельное
  объявление их «физическими константами» не является calibration; hold+30 вообще
  выходит за предложенный search window.
- Стоп/стоящая очередь не доказывают RED или отсутствие protected режима:
  возможна блокировка при GREEN. Проезд ходом не удостоверяет GREEN; vehicle
  queue restart может отражать снятие препятствия. Геометрия/units не сертифицированы.
- E=I(наблюдённые события/очередь) — outcome-derived mask, не независимо известная
  экспозиция камеры или спрос. Обнуление всех остальных bins не создаёт само
  по себе нормированную observation likelihood. Alpha/beta scores в предложении
  ещё не определяют вероятностную модель.
- Bracket между последним и первым проездами ограничивает switch только при
  дополнительных exclusive-mark/order/delay assumptions. Для реальных RELEASE
  эти предположения не установлены; аналогичный synthetic reference уже существует.
- Drop score2.0 и ширина4/12с не являются calibrated confidence interval или
  доказательством TRAFFIC_LOCKED. Shared demand/delay nuisance и change-point
  nonregularity должны входить в отдельное обоснование неопределённости.
- Anchored prior может оставить nominal baseline point при тишине, но не
  гарантирует правильный hold. Два одинаковых vehicle inputs допускают стабильный
  план и hold без спроса: правильные границы различны. Нельзя публиковать prior
  point как поддержанную реконструкцию вместо UNKNOWN.
- Нулевой прирост от одного arithmetic fix не доказывает исчерпанность старой
  архитектуры. Gemini неверно свёл исправление predecessor feasibility только
  к duration cost и не измерил заявленное доминирование emissions. Новые локально
  подтверждённые D2–D8 опровергают вывод, что кодовые исправления уже исчерпаны.
- Его Arm2 одновременно меняет emissions и censoring, Arm3 добавляет несколько
  prior terms: такие результаты не изолируют заявленные причины. «Ровно в switch»,
  гарантированный прирост,≤20ms и календарные сроки не измерены. MAE — mean,
  а не названная в ответе «медианная абсолютная ошибка».

Не выполнялся новый lag/threshold/grid search по34 известным границам. Полная
замена алгоритма и гарантии «никогда не хуже baseline» не приняты.

## Один нативный development comparison

Заранее зафиксирован [протокол](SEED_FLOW_PROTOCOL_20261017.md). Это отдельная
native проверка, не продолжение/перезапись остановленного эксперимента Astra.
Внешний control остановился при~1e-15 roundoff в другой среде; его FAIL сохранён.
Наш новый control19 воспроизвёл schedule/K/period **точно**, поэтому заранее
разрешённый численный atol1e-12 вообще не понадобился. Raw/K/selected indices
требовались exact; evaluator ±2с не менялся.

Код перед patched run: `35fc8fe899193bea4440b3e910e4f49782563836`.
1control+3patched workers,seed0,dt1,K2..6/max5/60с,hard90с/worker. Каждый output
и его SHA записан до full unchanged evaluate_prediction с прежними marks по
проверенным hashes. Большие raw JSON/ZIP не читались. Все K рассмотрены, timeouts0.
Оба K3 split parent завершили настоящий refinement на всех3 записях —6 новых
refinements, но ни один не стал победителем. Пассивная трассировка сохраняет
инициализации, quality, labels/probs hashes; решения/score не модифицирует.

| Запись | K before→after / экспертные labels | Raw matched/truth/predicted | Raw P/R | MAE /p95 /nearest, с | Baseline matched/truth/predicted | Cached wall, с |
|---|---|---|---|---|---|---:|
|17|3→3 /3|15/17/18→15/17/18|.8333/.8824|.7093/1.4852/1.1052|15/17/17→15/17/17|17.428|
|19|2→2 /2|1/8/8→1/8/8|.1250/.1250|1.5460/1.5460/4.7820|1/8/8→1/8/8|7.086|
|6|3→3 /2|3/9/15→3/9/15|.2000/.3333|1.4713/1.7969/2.8059|1/9/15→1/9/15|16.324|

Все6 полных metric payloads и выбранные schedules точны прежним. Raw19/34,
precision19/41=46.34%,recall55.88%. Baseline17/34,precision17/40=42.50%,recall50%.
Baseline matched MAE/p95/nearest17=.7483/1.7859/1.0859;19=1.5995/1.5995/3.9516;
6=1.4184/1.4184/2.7519с. Period errors17/19/6=.01819/.29950/.12925с, неизменны.
Full ranges/denominators/reasons/coverage, traces и inputs — в
`benchmarks/seed_flow_20261017/comparison.json` и `native_verification.json`.
Model temporal coverage1.0 на размеченных интервалах; local observation/lamp
coverage UNKNOWN. Physical state UNKNOWN, probability отсутствует. Знакомые
записи — development, не holdout. Runtime включает cache validation/import/
fitting/export, не raw ingestion и не CPU profile. Не является доказанным
ускорением/замедлением относительно другого окружения.

**Structural D1 gate PASS, development benefit FAIL_NO_GAIN.** Исправлена
достижимость существующих кандидатов, но реальная точность не улучшена. Нет
пострезультатной настройки, дополнительных retries или скрытого принятия2D.1.
Main сохранён;2D.1 FAIL/default-off и старые artifacts остаются.

## Скорректированный алгоритмический маршрут

1. **Следующий связный scope — D2+D3:** immutable согласованный snapshot
   labels/probs/data_loglik/penalized_decode_score; общий явно названный K objective
   для seed/refinement. Сначала независимые equality/snapshot counterexamples,
   затем один заранее заданный development comparison. Семантика критерия должна
   быть объявлена до метрик; не выбирать вариант по известным labels.
2. **D7/D6:** tie-correct redundancy и устранение ложного hard rejection joint
   shared signatures. Отдельные изменения/контроли: простое различие float rows
   не превращать в calibrated identifiability.
3. **D4/D5:** phase membership/circular matching с abstention при неоднозначности,
   затем одинаковое правило выбора по quality. Единый max не лечит circular pairing.
4. **D8:** censored endpoints исключить из onset evidence; отсутствие observed
   onsets не заменять нулями или точными boundary. Проверить callers/UNKNOWN.
5. Затем observation-model/local-history эксперимент по зарегистрированным
   assumptions и calibration, с отдельно измеренной prior dependence. Не переносить
   идеальные exclusive marks или фиксированную driver delay на реальные RELEASE.

Это возвращает работу к алгоритму. Ожидание supplier не блокирует D2–D8; приёмка
реальной сигнальной семантики по-прежнему требует independent validation.
