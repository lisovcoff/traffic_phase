# Протокол независимой валидации реконструкции сигналов

2026-10-16: operational definitions и source eligibility зафиксированы в
`config/calibration_acceptance_v1.json`; подготовлен набор30 разнородных записей
одной development-сессии, см. `CALIBRATION_BUNDLE_20261016.md`. Допуск±2с и
прежние proposed targets не менялись; independent release SLA не назначена.
Набор не является continuous lamp truth и не создаёт новый holdout.

Версия 1, 2026-10-13. Протокол задаёт будущие проверки; приведённые пороги —
предлагаемые инженерные gates, а не уже достигнутые результаты. Аудит и
фактические проверки описаны в `IMPLEMENTATION_PLAN.md`.

## 1. Разделение задач и истины

Оценивать отдельно: (a) движение/события, (b) анонимные фазы и режимы,
(c) logical signal groups, (d) реальные состояния каждой основной и дополнительной
секции. Совпадение K, периода или traffic activity не доказывает GREEN/RED.
Trajectory-only результат — гипотеза; отсутствие машины не является RED,
проезд не является однозначным GREEN. ДТП не является выводом из задержки.

Истина для (d): независимые журналы выходов контроллера с известной связью
signal group→head либо видео видимых ламп с синхронизацией. Журнал заданного
программного плана не равнозначен наблюдаемому состоянию исправной лампы.
Источник truth и его ограничения указывать явно. Известные ручные Lenina-фазы
и шесть archive K служат регрессией; не считать их новым независимым тестом.

Размечать каждую секцию в интервалах `[start_ms,end_ms)`: GREEN, YELLOW, RED,
RED_YELLOW, OFF; flashing states отдельными классами, если реально присутствуют.
Дополнительная секция может быть OFF, а не RED. Truth UNKNOWN означает
невидимость/спорную разметку и исключается из accuracy denominator с обязательным
отчётом доли. Prediction UNKNOWN — отказ алгоритма; не исключать его без учёта
coverage и end-to-end ошибок.

Два разметчика независимо от модели, затем adjudication разногласий.
Хранить confidence, visibility, временной допуск каждой границы, hardware ID,
annotation version и evidence reference. Не размечать лампы по движению машин.
Временной допуск не получать подгонкой к предсказанию.

## 2. Входной контракт и время

Дополнение по найденным данным (2026-10-13): в локальном каталоге
`data/ручная разметка` доступны 3 trajectory/annotation пары с 40 метками
начала фаз. `timestamp_ms`, `start_ms`, `offset_s` внутренне согласованы;
`timestamp_local` совпадает с UTC+5. Расчёты вести по Unix milliseconds,
отображение — Asia/Yekaterinburg. Это ещё не проверка синхронизации камеры
с независимо наблюдаемой лампой. Интервалы truth строить между соседними
метками; не продолжать последнюю фазу до конца записи без её конечной границы.

Пользователь подтвердил отсутствие дополнительных секций для двухфазных
записей и три movement groups для трёхфазной:
`N->_S/S->_N`, `E->_W/W->_E`, `N->_S/N->_E/E->_N`.
Это dataset-specific truth/configuration, а не inference prior для всех
перекрёстков. Буквы A/B/C в annotation не содержат movement mapping;
зафиксировать его по независимому описанию/источнику на calibration.
Старая fixture с W->N не должна автоматически расширять пользовательскую схему.
Совместное N->_S в двух фазах необходимо сохранить при оценке состояния.

На этих файлах можно независимо проверять размеченные границы/phase agreement
после фиксации semantics. Полная per-lamp accuracy, yellow/all-red и hardware
arrow timing требуют более подробной истины. Три известные записи — development
и regression data, не достаточный untouched holdout для универсальной точности.
Сначала offline работа над ядром и evaluator; FastAPI/HTML — после приёмки
алгоритма. Интерфейсы не используются для подбора результата «на глаз».

Manifest каждой записи: intersection_id, camera_id, session_id, source SHA256,
archive/member identity, UTC диапазон, timezone metadata, firmware/config
version при наличии, calibration ID, truth source и split.
Сохранить millis как исходный timestamp; проверить sorting, nonfinite values,
дубли и gaps. Стоп-линия/геометрия, units и semantics stay/move durations
версионируются. `millis-move_duration` явно помечается proxy.

Clock offset и drift оценивать по внешним общим событиям/часам до test;
сохранять интервалы их ошибки. Не сдвигать test timeline до максимальной
accuracy. Проверять преобразования recording/event/analysis/display base,
local window offset и cyclic seam единым эталонным набором timestamps.

Выход: head/group ID, state, state probabilities (сумма известных состояний=1,
если вероятностная модель применима), отдельная uncertainty и abstention reason,
boundary interval, source и observation coverage. Activity probability не
переименовывать в вероятность лампы. UNKNOWN не кодируется confidence=0
для уверенного RED и не превращается в RED в HTML/API/экспорте.

## 3. Предотвращение утечки

1. Дедуплицировать до split: raw hashes, ZIP members, перекрывающиеся time ranges,
   track fingerprints и копии fixture. Записи одного непрерывного сеанса,
   соседние фрагменты и производные events/features остаются в одном split.
   Новое имя ZIP или track ID не делает запись независимой.
2. Зафиксировать train/calibration/test manifest до настройки. Пример 60/20/20
   только при достаточном числе независимых сеансов; для малого набора grouped
   cross-validation и отдельный untouched pilot. Секунды не random-split.
3. Два независимых режима оценки: новый день известного перекрёстка
   (chronological session holdout) и новый перекрёсток (leave-intersection-out).
   Отдельно заявлять calibration по геометрии; тест с известным physical plan
   оценивает timing, тест без плана — discovery. Не смешивать эти задачи.
4. Purge/embargo между временными окнами не меньше максимального контекста
   модели, smoothing, длины трека и периода формирования features.
   Для бесконечной online memory — reset либо документированная калибровка
   строго на предшествующих данных. Если контекст не ограничен, делить целые
   независимые сеансы/дни, а не обещать достаточность произвольного embargo.
5. Fit нормализации, геометрических learned transforms, prior, threshold,
   startup lag, K range selection, regime selector и calibration только на
   train/calibration. Train baseline и reference pools не содержат test
   сеансов, включая копии и соседние фрагменты.
6. Semantic mapping фаз фиксируется на calibration или независимой конфигурации.
   В test `evaluate` best permutation можно оставить отдельной cluster
   agreement diagnostic; это не lamp accuracy. Test не выбирает phase permutation,
   offset, duration envelope или physical plan по собственным меткам.
7. Offline reconstruction может читать все trajectory observations внутри
   test-сеанса: это разрешённая transductive задача, если объявлена заранее и
   не использует его truth. Offline и causal online результаты отчётно разделены.
   Online на t получает только timestamps≤t, baseline из прошлого и разрешённую
   calibration. Future archive regime consensus недопустим в causal режиме.
8. Synthetic split — по generator family, parameter combinations и seeds.
   Одни и те же базовые траектории и их rotations/noise variants держать в одном
   split. Добавить отдельный генератор нарушений модели, иначе тест повторяет
   предположения likelihood/clearance.
9. Test truth недоступна inference loader, cache и feature builder. Хранить
   её отдельно, доступ только evaluator после фиксации prediction hashes.
   Не отбирать «успешные» test окна по точности или визуальному сходству.

Автоматические leakage checks: отсутствие shared session/hash/overlap в split;
перестановка/замена test truth не меняет prediction hash; удаление manual marks
не меняет discovery; train-only normalization/reference provenance; causal
prefix invariance; чистый cache и cache key с source/config/code/split hashes.
Известные regression cases не входят в независимый headline test.

## 4. Метрики

На абсолютной UTC сетке `t0+n*1000ms` оценивать состояние в точке времени;
отдельно хранить subsecond truth transitions. Секунды с неопределённой границей
помечать ambiguous; давать strict score на всех достоверных секундах и
boundary-aware score, явно показывая исключённую длительность. Не усреднять
разные лампы внутри секунды. Полуоткрытые интервалы обязательны.

| Задача | Метрики |
| --- | --- |
| Signal head/section | Confusion matrix по классам, macro-F1, per-class precision/recall, balanced accuracy; отдельно main/arrow/OFF |
| Отказ/coverage | known prediction seconds / valid truth seconds; selective error на known; end-to-end accuracy с UNKNOWN как ошибкой; доля truth UNKNOWN |
| Опасная уверенность | false GREEN при truth RED/OFF отдельно; false RED при GREEN; длительность и число непрерывных ошибочных эпизодов |
| Переходы | Type-matched one-to-one boundary matching, signed bias, MAE, p95, misses/extra switches; tolerance заранее из uncertainty truth |
| Структура | K accuracy по сеансам, order edit distance с допустимой циклической ротацией; group membership precision/recall и inclusion/overlap |
| Время | Period error по режимам, drift, per-cycle durations, errors около seam и смены режима |
| Аномалии | Episode precision/recall, detection delay, false alarms/hour, coverage во время hold/skip; без утверждения причины |
| Вероятности | Brier/log loss и reliability calibration на независимом test; risk–coverage curve, uncertainty boundary coverage/width |
| Эксплуатация | Peak RSS, source bytes read, runtime, latency p50/p95, dropped/duplicate events, determinism |

Показывать micro по секундам и macro по независимым сеансам/перекрёсткам.
Разрезы: K, спрос, ночь, occlusion, permissive/protected, адаптивность,
длинные очереди, gaps, аварийные сценарии, known/unseen intersection.
95% CI — block bootstrap независимых сеансов/перекрёстков, не секунд;
для малого n указать raw counts и нестабильность. Ошибки сильно автокоррелированы.
Ноль observed errors не означает истинный нулевой риск.

## 5. Матрица сценариев и бюджет

Обязательные компактные случаи: unequal K2–4; K5–8 при заявленной поддержке;
renamed/rotated движения; permissive turn без стрелки; independent arrows;
no-demand при GREEN; очередь при GREEN; ДТП/блокировка при неизменном плане;
green extension, shortening, skipped phase/preemption; regime switch и drift;
yellow/all-red, OFF/flashing; out-of-order/duplicate timestamps и ZIP members;
partial cycles, cyclic seam, missing 10/30/50% observations, camera blackout.
Для неидентифицируемых пар сценариев ожидается UNKNOWN, а не угадывание.

Уровни: unit counterexamples → небольшая независимая synthetic suite →
короткие размеченные реальные сеансы → отдельная эксплуатационная проверка
больших архивов. Реальный пилот включает разные перекрёстки и дни, а не только
первые треки одного файла. Число независимых сеансов определить расчётом
статистической мощности; четыре трека аудита для этого недостаточны.
Первые проверки ограничить несколькими MB и минутами CPU. Большие архивы
читать streaming только после прохождения малых gates; никаких full reruns
или tuning против известного CSV без конкретной гипотезы.

## 6. Критерии приёмки

Безусловные software gates: leakage checks проходят; UNKNOWN сохраняется во
всех интерфейсах; no-demand не доказывает RED; permissive движение не доказывает
hardware arrow; causal prefix invariance; out-of-coverage UNKNOWN; все принятые
контракты и regression tests зелёные. Исправление известного baseline behaviour
допускается только с письменной причиной и independent counterexample.

Начальные предлагаемые gates для размеченного пилота (после review SLA):
boundary MAE≤1s и p95≤2s на observable transitions, coverage≥80% достоверных
секунд, macro-F1≥0,90 среди known predictions. Вместе обязательно публиковать
end-to-end score, false GREEN, длительность confident errors и CI; selective F1
нельзя улучшать скрытым падением coverage. Для false GREEN до пилота согласовать
допустимый риск и верхнюю 95% границу по независимым эпизодам. Без такого
порога нельзя объявлять промышленную приёмку. Для ограниченной observable subset
публиковать также размер и причину ограничения.

Для аномалий и редких аппаратных режимов пороги определяются отдельно по SLA
и доступности истины; до этого статус experimental/insufficient validation.
Заявление «99%» допустимо только с определённым denominator, независимой
hardware truth, достаточными независимыми наблюдениями, confidence interval
и coverage. Ни текущий аудит, ни K6/6 этих условий не выполняют.

## 7. Артефакты каждого будущего запуска

Сохранять code SHA, dependency versions, source/annotation/split/config hashes,
run ID, seeds, mode offline/causal/configured, training/calibration provenance,
сырые predictions по секциям с coverage, per-boundary matches, агрегаты и
resource measurements. CSV, JSON и report генерируются из одной таблицы
результатов; автоматическая сверка числителей/знаменателей обязательна.
Отчёт содержит ошибки и UNKNOWN, а не только удачные HTML кадры. Test manifest
замораживается; исправления после просмотра ошибок требуют нового untouched
holdout или явно маркированного повторного regression результата.

На этапе 1 создаются только этот протокол и план. Отсутствующая независимая
ламповая разметка, clock calibration и hardware geometry перечислены в плане;
их отсутствие не препятствует software проверкам, но препятствует утверждению
точности реальных сигналов.

## 8. Checkpoint: входы независимого calibration-пилота

После prototype `c99268b700b2b46bc0202a2a37f635e3af93f70d` следующий шаг —
сбор следующих материалов; новые эксперименты до их получения не запускаются.

1. **Calibration session:** trajectory JSON и независимый источник состояний/
   границ (видео видимых секций или журнал контроллера с описанной семантикой),
   ID/дата сеанса, временные окна, хеши. Нужны проверенное соответствие часов,
   offset/drift, способ проверки и uncertainty синхронизации/разметки.
2. **Отдельный validation session того же перекрёстка:** свой JSON и независимая
   truth, те же сведения о времени; непересекающиеся интервалы и проверка
   дубликатов треков/фрагментов. Split фиксируется до calibration; validation
   не используется для выбора параметров. Известные три записи — development,
   не untouched holdout.
3. **Семантика и mapping:** независимо установленное соответствие логических
   групп movements, shared movements, permissive/protected режимы; источник
   аппаратного mapping. Если используется геометрия — подтверждённый источник,
   версии зон/стоп-линий и преобразование координат. Зона не равна стоп-линии.
4. **Supplier definitions:** определения и units speed, coordinates, durations,
   способы расчёта и версия producer. Неподтверждённые поля остаются UNKNOWN;
   правдоподобные численные диапазоны не заменяют спецификацию.
5. **Prior и задержка события:** независимый источник duration prior (например,
   документированный план контроллера) и основания модели задержки vehicle
   event относительно сигнала. Нужны синхронные пары событий/сигналов из
   calibration, условия применимости и uncertainty; sampling/localization
   события отделяются от signal-to-event delay. Nominal10 не выбран, параметры
   по validation не оцениваются; exclusive marks не предполагаются для RELEASE.

Использовать существующий `independent_review_template.json` из
`evidence/stage2b1_ew_event_audit/` в коммите
`a5f1176aaab3be1a86b744d6390804b01fed02d5` (диагностическая ветка; в текущей
production-линии файл не копируется). Его поля independent_event_type,
временной интервал, visibility, geometry/source, reviewer и vehicle uncertainty
заполняются только по независимому источнику. Существующие event IDs относятся
к прежней выборке, а не к новым сеансам. Выводы extractor не являются truth;
неизвестное оставлять незаполненным с причиной. Повторный аудит и поиск ранее
отсутствовавших источников на этом checkpoint не требуются. Ограничения и FAIL
сохраняются; пилот не является автоматической промышленной приёмкой.
