# Независимый review traffic_phase

Проверен commit `b7675c70bf191a20454fe974baa18cc161f01856`, ветка
`fix/hsmm-predecessor-duration-20261016`. Remote ref совпал с commit. Review и
единственное исправление находятся локально в `review/seed-flow-20261017`;
публикации/изменения main нет. Номера строк ниже относятся к проверенному commit,
до patch. Источник всех выводов — этот код и перечисленные воспроизводимые тесты.

**Вывод:** подтверждены восемь дефектов. Исправлен только порядок формирования
списка seeds. Реальный прирост K/границ не установлен: один неизменённый контроль
остановил дальнейший development comparison по заранее объявленному строгому
условию равенства. Причина — округление порядка 1e-15, не изменение raw истории.

**1. Что действительно доступно.**

Все приоритетные файлы доступны полностью: `app/core/v9/{fit,decoder,model,
primitives,events,vehicle_evidence}.py`, оба `docs/HSMM_RECURRENCE_*.md`, тесты
recurrence, cache replay, phase search, discovery, redundancy и state contract.
Их base-хеши/размеры сохранены в `evidence/independent_review_20261017/availability.json`.
Отсутствующего алгоритмического кода из запрошенного списка нет.

Доступны три lossless event cache в `benchmarks/stage2c_20261014/predictions`,
исторические corrected predictions и comparison в `benchmarks/hsmm_recurrence_20261016`.
Реконструкция полных TemporalEvent fields, selected indices и anchors проверена
существующей `cached_bundle`: 6172/2789/4795 temporal events,
717/597/1107 selected events соответственно для записей17/19/6.

Не доступны следующие исходные файлы (исторический префикс в baseline manifest:
`D:\Code\PythonProjects\traffic_phase\data\ручная разметка\`):

| Траектории | Разметка |
|---|---|
| `17_2025_2_19_10.json` | `17_2025_2_19_10.json_manual_marks.json` |
| `19_2025_2_24_16.json` | `19_2025_2_24_16.json_manual_marks.json` |
| `6_2025_2_14_20.json` | `6_2025_2_14_20.json_manual_marks.json` |

Raw-файлы не нужны для lossless cached fitting, но полный новый запуск
`evaluate_prediction` с исходными annotations здесь невоспроизводим. Сохранённые
interior truth boundaries позволяют отдельно воспроизвести boundary metrics.
Никакие phase labels или annotation-файлы не синтезировались.

**2. Фактический путь selected events → raw history.**

`vehicle_evidence.select_permission_events` (181): для каждого movement берёт все
не-LOW RELEASE, если есть хотя бы один; иначе eligible CROSSING_PROXY. ENTRY сюда
не подставляются. Это выбор по movement, не fallback для каждой машины/интервала.
`events._pack_temporal_events` (452) сохраняет selected indices, вычисляет anchor
по минимальному ENTRY и пакует permission timestamps относительно него.

`model._discover_bundle` (1030) передаёт отдельные entry/permission views в
`_discover_from_stream_views` (577). Период оценивается по **ENTRY**. Occupancy
строится по selected permission events: `x[t,stream]∈{0,1}`, несколько событий
одного stream/bin насыщаются до1. Confidence/uncertainty не являются likelihood
weights. Отсутствие события математически участвует как Bernoulli zero; это не
доказательство физического RED. Для input >=7200s дополнительно возможен выбор
локального regime window; на коротком пути работает global fallback.

Далее `discover_phase_count`: K2..6, максимум5 вызовов em_fit, кооперативный60s
бюджет; на каждый K iterations=2. Внутри `em_fit`:

1. release seed, entry seed, ensemble, equal-duration/offset seed;
2. **в base здесь строится unique** по префиксу длиной около периода;
3. только затем K3 добавляет два internal split seed в исходный список;
4. обходится уже готовый unique — оба split не посещаются;
5. каждому посещённому seed соответствуют fitted Bernoulli templates и отдельная
   попытка HSMM refinement с фиксированными seed targets и initial phase;
6. refinement заменяет periodic seed только если
   `Q_refined > Q_seed + 0.0001`, где `Q=pointwise_LL/(n*s)+0.05*coherence`.
   Ошибка refinement перехватывается, periodic seed остаётся допустимым;
7. при наличии именно НЕуточнённого ensemble включается особое предпочтение,
   описанное в дефекте5. `ensemble+hsmm` само по себе эту ветку не активирует.

Различные templates у конкурентов сами по себе не ошибка: одинаковая data
likelihood под отдельно fitted параметрами сравнима. Ошибки — устаревшее значение
score относительно возвращённых параметров и разная семантика score.

K выбирается по `candidate_metrics`: `-2*score + K*S*log(N*S)` плюс5 на каждую
дополнительную относительно K2 фазу за цикл. При K>2 и более одной unsupported
фазе selection_score=∞. Затем `model.py` при победившем K3 может заменить **весь
fit** на `all_fits[2]` по redundancy detector. Это не локальное слияние пары
границ K3. `raw_hsmm_segments` копируются из окончательного `fit['segments']`.
`periodic_baseline_from_segments` строится уже из raw, а не подменяет raw.
Experimental local history не включается по умолчанию и raw не заменяет.

В сохранённых результатах проверенного commit: запись17 имеет seed-only decoder
fallback (`min=max=durations`, нет duration_targets/initial constraint), поэтому
её `raw_hsmm_segments` происходят из **periodic seed**. У19 и6 diagnostics от
настоящего decoder, следовательно raw взят из **HSMM refinement**. Точный seed
view для17/6 в экспорт не сохранён — его нельзя достоверно назвать по этому JSON.
Новый неизменённый контроль19 с пассивной трассировкой подтвердил
`equal_duration_offset_search+hsmm`. Общее имя поля не доказывает HSMM-происхождение.

**3. Подтверждённые дефекты и независимые контрпримеры.**

**D1 — недостижимые split-seeds.** `fit.py::em_fit`, base234–319.
Механизм: unique построен до append. Контрпример: два цикла по24 bins с метками
`0×6,1×6,2×12`, `x=eye(3)[labels]`, без stream views. Генерируются два разных
split parent, но spies на template fit/refinement в base видят только equal seed.
Три независимых масштаба dt=.5/1/2 дают FAIL. Ожидается посещение обоих разных
кандидатов; дубликаты должны посещаться один раз. Исправление: перенести весь
неизменённый dedup block после K3 generation, перед fitting. **Только это внесено.**

**D2 — score не соответствует возвращённым probs.**
`fit.py::_fit_from_initial_labels`, 61–91. Decoder оценивает labels под предыдущим
`probs`; затем fit возвращает `new_probs`, но старый `score`. Лучший iterate тоже
выбирается по lagged score. Контрпример: x содержит три цикла A6/B14, initial
labels A10/B10, period20, iterations1. Возвращено `score=-31.199676759660846`;
независимая сумма emissions под возвращёнными probs и тех же duration/transition
costs равна `-13.192524235065875`. Labels/segments/pointwise_LL согласованы,
score — нет. Decoder bounds относятся к выполненному decode, но не удостоверяют
этот смешанный payload. Конкретный отдельный fix:
`new_score = decoder_score + LL(labels,new_probs) - LL(labels,old_probs)`;
сравнивать snapshots по явно выбранному objective и сохранять согласованный
tuple labels/probs/score/segments/targets. Старый decoder score хранить отдельным
диагностическим полем. Дополнительное декодирование для такого пересчёта не нужно.

**D3 — K criterion смешивает разные objectives.**
`fit.py::em_fit` (418–424), `candidate_metrics` (964).
Seed не имеет score, возвращается чистый pointwise_LL. Refined возвращает
penalized decoder score (к тому же D2). Контрпример: A10/B10 два цикла, одинаковые
labels и probs у seed/refined. Получены BIC21.38371479134521 против
22.883714791345255; разница1.5 — только три transition costs по.25, удвоенные BIC.
Ожидается одинаковый selection objective для одинакового объяснения данных,
независимо от пути получения. Отдельный fix: explicit `data_loglik` для всех
кандидатов и K criterion; penalized decode objective отдельным полем. Альтернатива
— единый полностью заданный penalized objective для ВСЕХ путей с общим правилом
targets/censoring. Это уже изменение K criterion, в текущий patch не включено.

**D4 — ensemble не инвариантен к началу отсчёта.**
`fit.py::em_fit` (158–167), `primitives.initial_seed_from_streams` (208).
Независимо отсортированные onset списки сопоставляются zip, затем используется
линейное среднее. Cluster membership в seed_info не сохраняется. Контрпример
P100: release onsets=[1,51], entry=[49,99]. Соответствующие движения могут быть
парами1↔99 и51↔49: midpoint=[0,50]. Код даёт[25,75]. После общего сдвига10s код
даёт[10,60], то есть[0,50] в исходной системе: одна смена clock origin изменила
результат на четверть периода. Ожидается circular equivariance и сопоставление
тех же фаз. Отдельный fix: сохранять состав групп, сопоставлять циклические
ротации по membership, при неоднозначном соответствии не строить ensemble;
для подтверждённой пары использовать
`(a + .5*((b-a+P/2)%P-P/2)) % P`. Антиподальная пара неоднозначна, не усреднять
её произвольно. Одной замены среднего без phase matching недостаточно.

**D5 — предпочтение ensemble без верхней границы потери качества.**
`fit.py::em_fit` (367–393). При surviving pure ensemble чистые release и entry
исключены из сравнения вовсе; margin.002 применяется только остальным источникам.
Selector-only контрпример с контролируемыми Q: x.shape=(20,2), coherence0,
LLrelease=-2, LLentry=-4, LLensemble=-8, LLequal=-9, refinement недоступен.
Qrelease=-.05, Qensemble=-.20, но выбран ensemble. Это unit-test control flow,
не измеренная real likelihood. Ожидается выигрыш лучшего кандидата по заявленной
Q либо явная одинаковая для всех политика ties. Конкретный fix: общий
`max(fitted,key=model_quality)`; при необходимости tie-break только среди
равных/численно эквивалентных результатов. Не добавлять confidence weights.

**D6 — exclusive-stream support ошибочно принят за идентифицируемость.**
`fit.py::_phase_support_metrics` (449), `discover_phase_count` (1058 далее).
Каждой фазе требуется хотя бы один stream с вероятностью >=1.15 максимума других
фаз. Различимые совместные signatures не учитываются. Контрпример: повторяемые
равные фазы AB, AC, BC, бинарные строки `[1,1,0],[1,0,1],[0,1,1]`.
Templates попарно различимы, но ни один stream не эксклюзивен: supported=0,
unsupported=3, точный K3 fit получает ∞. Ожидается отсутствие hard rejection
только из-за shared movements. Каждый stream может поддержать максимум одну
фазу по этому правилу: возникает и скрытое ограничение supported_count<=S,
несмотря на отсутствие явного topology cap. Конкретный отдельный fix: сохранить
exclusive support как diagnostic, убрать его использование как доказательства
неидентифицируемости; hard structural degeneracy проверять на пустые фазы/
тождественные совместные emission rows, остальные сравнивать общим criterion.
Одна лишь нетождественность estimated rows не доказывает реальное logical K;
проверка устойчивости и demand confounding остаётся отдельной задачей.

**D7 — ties в ranks ломают инвариантность redundancy.**
`fit.py::_rank_correlation` (618), `evaluate_phase_redundancy` (689).
`argsort(argsort(a))` раздаёт разные ranks равным значениям в зависимости от
порядка колонок. Минимум: a=[1,1,0], b=[1,0,1]; одновременная перестановка
[1,0,2] меняет correlation с−1 на−.5. Есть и контрпример до самого решения:
P160, три цикла, длительности40/40/80; в каждом5-bin блоке числа единиц по5
потокам равны `[1,1,2,2,0]`, `[1,2,1,2,0]`, `[0,0,0,0,4]` соответственно.
Templates fitted из бинарного x, все3 фазы supported. Перестановки колонок
[1,3,0,2,4] и[0,2,1,3,4] дают `detected=False` и `True`. Сами данные/метки/
likelihood не изменены. Это может поменять финальное K3→K2 в model.py.
При равных event counts переименование streams меняет tie ordering в
`build_occupancy_matrix`, так что column-order зависимость практически значима.
Ожидается одинаковое решение. Fix: `scipy.stats.rankdata(method='average')`
для обоих векторов, с прежним guard константных векторов. Ранее имевшийся
renaming test проверяет другой, хорошо разделённый случай и этот дефект не ловит.

**D8 — начало обрезанного окна считается реальным onset baseline.**
`events.py::periodic_baseline_from_segments` (737–752).
Первый segment всегда начинается в0, но это может быть середина фазы. Его start
включён в circular mean наравне с переходами. Контрпример P40, segments:
`(0,10,A),(10,30,B),(30,50,A),(50,70,B),(70,80,A)`. Настоящие onsets A=30 mod40,
B=10; код выдаёт A=32.95167235300867. Ожидается30. Circular mean здесь вычислен
правильно, но загрязнён censored наблюдением. Fix: исключить start первого
segment, если нет независимого флага observed onset; использовать внутренние
переходы. Если onset фазы не наблюдался, сохранять unavailable/UNKNOWN вместо
фиктивного нулевого center. Raw не меняется, но periodic baseline и deviations
сейчас могут получить искусственную ошибку.

**4. Что не доказано и требует отдельного эксперимента.**

- Вероятность event occupancy зависит от demand/restart sampling, а не только
  от logical permission. Даже после исправления всех арифметических ошибок
  дополнительная фаза может объяснять меняющуюся интенсивность. Из этих трёх
  development записей не установлено, что именно это причина лишнего K3 у6.
- Redundancy оценивает все пары только при выбранном K3; получает `fit2`, но его
  BIC gap возвращает лишь как diagnostic, не использует как gate. Фактические
  границы fit2 могут отличаться от проверенного merge labels3. Все supported
  фазы сами по себе не защищены от override. Это heuristic, не доказательство
  лишней logical фазы; за пределами D7 реальную частоту false merges не оценивал.
- Initial seed clustering сводит каждый movement к одному circular center.
  Мультимодальные shared movements могут терять структуру. Equal-duration
  fallback существует, но полноты поиска не обеспечивает.
- Split generator делит конечные runs, включая censored края, пополам;
  durations оценивает по полному finite window. Открытие доступа к seeds не
  удостоверяет качество этой инициализации на краях окна.
- Dedup сравнивает лишь первый период+2bins, не полный путь, не duration targets
  и не перестановочную эквивалентность фаз. Возможны лишние удаления/повторные
  вычисления; отдельный минимальный false-dedup пример здесь не проверялся.
- Отдельный late RELEASE переключает selector всего movement с crossing на
  release view. Потеря остальных proxy events и неодинаковая задержка ENTRY/
  RELEASE/zone proxies могут влиять на границы. Extraction/selection не менялись.
- Начальный phase фиксирован seed; decoder допускает левый partial segment от
  двух bins, последний обязан быть полным по ограничениям. Recurrence arithmetic
  исправлена ранее, но finite-window observation assumptions этим не проверены.
- K budget проверяется между вызовами, внутри em_fit есть broad exception
  fallback без подробного ledger по seeds. Внешний search ledger корректно
  отмечает skipped/failed/partial и не обещает global optimum. Неполный поиск
  здесь не скрыт; completeness по K не означает полноту инициализаций.

**5. Единственный patch и его проверка.**

Выбран D1 как первый шаг по отношению ожидаемой полезности к scope: открывает
два уже предусмотренных объяснения K3 и возможные другие границы, меняя только
достижимость кандидатов. Ожидаемый прирост точности количественно неизвестен;
усиление лишнего K3 также возможно. Это не заявление, что D1 обязательно важнее
D3/D7 на реальных данных.

Точный смысл patch:

```python
seed_candidates = release_entry_ensemble_equal_candidates(...)
if k == 3:
    seed_candidates.extend(existing_two_phase_internal_splits(...))
unique = existing_dedup(seed_candidates)  # moved here, rule unchanged
for source, labels0, info in unique:
    existing_fit_and_selection(...)
```

Применяемый diff: `evidence/independent_review_20261017/change.patch`.
Единственный production-файл — `app/core/v9/fit.py`, перемещён существующий блок
и добавлен комментарий. Decoder, period, selector, observation model, K criterion,
evaluator и historical caches побайтово сохранены; хеши проверены.

Новые tests в `tests/test_v9_independent_review.py`: оба split parent при
dt=.5/1/2; dedup; неизменённый K2 route; оба кандидата завершают настоящий decoder;
контрпримеры остальных дефектов как strict xfail. До patch исходный набор:
10 FAIL,1 PASS (три FAIL относятся к D1, семь к прочим дефектам). После patch
и добавления actual-refinement/decision-level checks: совместно с существующими
recurrence, K4/renaming, shared-movement, budgets, cache/state tests — **60 PASS,
8 XFAIL**,3.46s. Это восемь test cases для семи неустранённых дефектов, не восемь
дополнительных исправлений. D7 отдельно воспроизведён с `--runxfail`: False != True.

Первая collection attempt не прошла из-за отсутствовавшего fastapi dependency;
промежуточно54 PASS/7 XFAIL/1 dependency FAIL. После установки test dependencies
полный указанный набор прошёл. Все логи сохранены; исходные не заменены. Большой
synthetic benchmark с threshold grid не запускался: выбраны только два его
handcrafted unit tests. Полная suite проекта не заявляется.

**6. Заранее объявленный development run и фактический результат.**

Протокол `docs/INDEPENDENT_REVIEW_PROTOCOL_20261017.md` и freeze записаны до нового
контроля. Был разрешён максимум1 unchanged control+3 corrected workers,90s каждый,
обычные K2..6/5calls/60s, dt1, seed0. Gate: точное равенство control schedule,
period diagnostics и K. Тuning/retry запрещены. Независимость от известных меток
не заявляется: это development, опубликованные исторические ошибки уже известны.

Фактически выполнен **только control19 на неизменённом b767-коде**,4.043s wall.
K2 и raw segments точно воспроизведены. Но baseline center и два его endpoints
отличились на7.105427357601002e-15s; три period diagnostics — максимум4.44e-16.
Сам period estimate совпал. Это согласуется с floating-point roundoff, но точная
причина между библиотеками/платформами не изолировалась. Условие полного равенства
не прошло; **corrected real runs=0**, расширения допуска/повторного control нет.
Этот строгий контроль оказался излишне чувствителен к незначащим численным
различиям; я не стал менять его после результата.

Без fitting отдельно восстановлены исторические boundary targets из сохранённых
`matches.truth_ms ∪ missed_truth_ms`; raw и baseline sets/intervals совпали.
Неизменённые `match_boundaries`/`segments_absolute`, tolerance2s, воспроизвели
все6 исторических строк и обе новые control19 строки **точно**, включая matches,
precision/recall, MAE/p95, nearest MAE и coverage. Это оценка сохранённых границ,
не восстановление отсутствующей полной разметки.

Ниже **исторический baseline b767**, а не результаты patched алгоритма:

| Запись | История | K / экспертные distinct labels | matched/truth/predicted | precision / recall ±2s | matched MAE / p95,s | nearest MAE,s |
|---|---|---|---|---|---|---|
|17|raw|3 /3|15/17/18|.8333 / .8824|.7093 /1.4852|1.1052|
|17|periodic baseline|3 /3|15/17/17|.8824 / .8824|.7483 /1.7859|1.0859|
|19|raw|2 /2|1/8/8|.1250 / .1250|1.5460 /1.5460|4.7820|
|19|periodic baseline|2 /2|1/8/8|.1250 / .1250|1.5995 /1.5995|3.9516|
|6|raw|3 /2|3/9/15|.2000 / .3333|1.4713 /1.7969|2.8059|
|6|periodic baseline|3 /2|1/9/15|.0667 / .1111|1.4184 /1.4184|2.7519|

Raw суммарно19/34/41, precision46.34%, recall55.88%; periodic17/34/40,
precision42.50%, recall50%. Temporal model-history coverage=1, logical uncovered
fraction=0 на отмеченных интервалах всех6 строк. Это не local observation coverage:
она UNKNOWN; physical state UNKNOWN, calibrated lamp probability отсутствует.
Local2D.1 FAIL/default-off сохранён. Экспертное число distinct labels не обязательно
полное K контроллера.

Исторические cached-worker времена17/19/6:13.195/5.922/13.868s. Новый unchanged
control19:4.043s wall, тот же scope cached fitting без ingestion, другая среда;
это не измеренное ускорение patch. Все метрики control19 совпали с таблицей.
У corrected версии K/counts/precision/recall/errors/coverage/runtime — **N/A,
не запускалась**. Ни улучшение, ни регрессия её реальной точности не измерены.

Среда нового review: Python3.12.14, NumPy2.3.5, SciPy1.17.0, sklearn1.8.0;
OMP/OpenBLAS/MKL1 thread. В требованиях репозитория версии не закреплены.

**7. Минимальный следующий шаг и проверяемый вердикт.**

Первым вносить только D1 patch; он уже готов и проходит regression gate.
Для следующего реального comparison заранее зафиксировать переносимый control:
K, selected indices и raw label path — exact; diagnostic floats сравнивать по
объявленной численной погрешности либо восстановить оригинальную численную среду.
Это отдельное условие воспроизводимости, не изменение evaluator/±2s. Нужны
исходные три *_manual_marks.json для полного annotation evaluation; boundary-only
проверка возможна по уже сохранённым targets с явно ограниченным scope.

Пользу подтвердит заранее объявленный limited run: рост числа верных K или raw
matched >19/34 без потери ранее правильного K; по каждой записи не ухудшаются
matched count/precision/nearest MAE, aggregate precision>=19/41, coverage/UNKNOWN
сохранены, все K рассмотрены в лимите. Matched MAE/p95 обязательно публикуются,
но не заменяют recall. Синтетический успех не является реальной точностью.

Пользу на этих inputs опровергнут неизменные schedules/метрики; ухудшение K,
границ или исчерпание бюджета отвергнет практическую гипотезу этой версии.
Сам факт недостижимого кода остаётся доказанным независимо от real accuracy.
В этом review гипотеза реального улучшения **ещё не проверена**, а не принята.
