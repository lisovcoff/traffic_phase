# traffic_phase — план до готового продукта

2026-10-19, уточнение полного сценария: **продукт ещё не готов к полной сдаче**.
[Аудит кода, конкретные разрывы и условия приёмки](docs/DELIVERY_GAP_ASSESSMENT_20261019.md).
Оставшиеся блоки, по зависимостям:

1. Общая сохраняемая модель перекрёстка и автоматический анализ всего ZIP,
   включая все допустимые JSON/сеансы, без ручного выбора фаз/схем.
2. Автоматические3/4 подхода и гипотезы секций без именных профилей; проверенная
   история переменных длительностей и каталог режимов разных дней.
3. Причинный онлайн на этой модели: текущие машины раз в секунду, K/структура
   только из офлайна, продления и выбор режима, хранение истории и состояния.
4. Одна панель офлайн/онлайн, общий плеер/машины, сквозной replay без будущих
   данных, проверка точности/задержки, установка и комплект сдачи.

Сквозную интеграцию собирать на ограниченном примере как можно раньше.
Измеренная поставка ниже закрывает часть офлайн-анализа, не эти четыре блока.
Этим аудитом алгоритм не изменялся и2D.1 не возобновлялся.

2026-10-19: [улучшенный алгоритм подключён к приложению](docs/ACCURACY_RECOVERY_RESULTS_20261019.md).
Поставлено: выбор permission отдельно по машине, сокращение ложных фаз
интенсивности, наблюдаемые старты очереди, уточнение устойчивого периода,
полная история выбранного сеанса и общий backend веб/CLI без видео.
219/219 реальных источников;315/315 совпадений производственного кода
с зафиксированным вариантом;3/3 холодных HTTP ZIP и браузерные проверки PASS.
72 случая разработки: K68/72, ошибка фаз4,01%;24 новых: K24/24, ошибка2,85%.
Новый фрагмент видимой основной N:8/9 переключений ±2с против3/9.
Готовы три просмотра и интерактивный отчёт всех96 сценариев.

Остаётся научная/продуктовая граница: нет независимой истины для большинства
реальных дат; для Энтузиастов не связаны часы, для Чичерина недоступно видео.
Четыре ошибки K на сложной синтетике, строгая ручная метрика6/13 вместо7/13
и непринятая история продлений2D.1 сохранены в отчёте. Универсальная точность
всех физических ламп не объявляется. Следующая проверка требует новых реальных
сеансов с независимыми переключениями, без настройки по уже раскрытому контролю.
Main сохранён, эксперимент2D.1 FAIL/default-off не возобновлялся.

Ниже — история предыдущих поставок и их ограничений.

2026-10-19: [завершён прогон всех архивов и реалистичной синтетики](docs/ALL_ARCHIVES_SYNTHETIC_RESULTS_20261019.md).
219/219 источников обработаны; 216 уникальных JSON, 134,6 млн детекций с копиями.
72 сценария /62 часа: K совпало13/72; ошибка логических фаз42,1%, цветов основных
голов36,4% с UNKNOWN. Универсальная точность НЕ принята. Готовы общий отчёт,
интерактивные сравнения и входные ZIP без истины. В обычном обученном просмотрщике
отключён автоматический выбор видеопоправки конкретного архива; прежние результаты
с такой поправкой — диагностика. Решатели/профили/main и2D.1 FAIL/default-off сохранены.
Далее нужен отдельный проверяемый шаг по лишним фазам, периоду и задержке очереди,
с новыми контрольными данными после подбора. Никакой эксперимент этим не включён.

2026-10-19: [жёлтый включён в общий алгоритм истории сигналов](docs/YELLOW_TIMING_RESULTS_20261019.md).
YELLOW3с до RED, RED_YELLOW до2с перед GREEN; нет ложного жёлтого при продолжении
основного зелёного через смену стрелки. Пропуски/слишком короткие интервалы дают
UNKNOWN. Общий API обучения задержек любой головы требует независимой связи часов
и только обучающей разметки; перенос чисел между источниками запрещён SHA-scoping.
На свежем видео3300..3600 Свердловского, без изменения замороженных поправок:
MAE green2.547→0.097с, red3.563→0.122с, yellow0.128с,9/9 в0.5с от brackets.
Это3 цикла видимого N той же записи при условной привязке часов, не все головы
и не другой день. Пятая независимая машина на3600с подтвердила прежний delta.
У Энтузиастов добавлена подтверждённая основная пара E/W,8 новых видеометок,
одна жёлтая граница неразрешена; JSON/video clock по-прежнему не принят.
1392 full PASS; реальный ZIP каждого участка, MP4 обоих видео и mobile QA PASS.
Следующее: независимый clock link Энтузиастов, прямые метки стрелок/красно-жёлтого
и другой день. Main/старые evidence и2D.1 FAIL/default-off сохранены.

Дополнение19.10: пользователь подтвердил манёвр кандидата7 Энтузиастов E→_E
с ожиданием W→_E. Проверены9 новых native кадров28–36с; начало заметного завершения
манёвра между29/30с. [Кадры и исходный speed](evidence/enthusiasts_turn_clock_20261019/report.html).
Часы этой пары ещё не приняты, новых fits нет. Следующий контроль — другая машина
в удалённой части видео/JSON; стоящий при уступании автомобиль не означает RED.

2026-10-19: [независимая проверка часов по четырём машинам](docs/CARDINAL_CLOCK_LINK_RESULTS_20261019.md).
Свердловский: прежние H/delta прошли на новых машинах в15/30/45/55мин, без refit
и без сопоставления светофорных циклов. Delta1.253838с; условный диапазон1.127–1.369с.
Задержка N main после учёта часов: green2.644/red3.685с. Экспортированы22 видеометки
в шкале JSON с отдельными интервалами неопределённости и калиброванные N-main onsets.
Новый MP4 viewer проверен в Edge,57 tests PASS. Поправки пока отдельные от полного
плана фаз/production: стрелка и другие головы не проверены. Пользователь исправил
направление стрелки на N→E в обеих системах; Энтузиастов видимая голова E, E/W
одинаковы по его подтверждению. Дополнительный fit Энтузиастов не прошёл; сохранён.
Следующий шаг — конкретный review идентичностей машин Энтузиастов, страница готова;
не повторять подбор по старому контролю. Main и исторические evidence сохранены.

2026-10-18: [два исходных видео и все9 JSON проверены](docs/DIRECT_VIDEO_TRUTH_RESULTS_20261018.md).
Прочитаны часы, сохранены24 video-only green-on brackets и10 red brackets;
остальные сомнительные кадры и пропуски не скрыты. Условная оценка задержки
Свердловского: green3.898с/red4.939с по первому участку; отдельный второй участок
проверен без повторного подбора. Это объединённая задержка модели/часов, не
доказанная физическая ошибка: независимый JSON↔PTS clock link и полное назначение
видимых голов ещё требуются. Поправки production не меняют. Доставлен локальный
MP4/visible-head before-after viewer, проверен на реальном3GB видео в Edge;
50 соответствующих tests PASS. Дальше: ответ пользователя о сторонах света,
независимое совпадение машин, особенно для offline-export Энтузиастов; лишь затем
калибровка времени алгоритма с учётом синхронизации. Main/2D.1 сохранены.

2026-10-18: [реализован отдельный обученный режим](docs/LEARNED_PHASE_RESULTS_20261018.md).
На временном контроле второй половины трёх записей 11/13 границ в ±2с против
7/13 у старой модели на тех же окнах; 15 прогнозов против 17. Число фаз задано
обучающей половиной, не автоматическим discovery. Два новых автоматических
count-варианта проиграли и сохранены отдельно. Проверены два реальных ZIP
(один JSON/сеанс каждого), HTTP upload и браузер. 1367 full PASS, затем 26
targeted PASS. Запуск: /visualization/learned; готовые HTML и сводка в
evidence/learned_release_20261018/. Следующее доказательство — независимый день
с метками; на имеющихся данных универсальность и точность ламп не доказаны.
Не повторять подбор по этому контролю. Main и 2D.1 FAIL/default-off сохранены.

Проверка после принятого duration-исправления:1357 tests PASS, отдельное
равенство3 production-историй кандидату и START_WEB.cmd --check PASS.
Отчёт всех вариантов: evidence/algorithm_checks_20261018/summary.html.
Реальные15/17,1/8,3/9 не улучшились; новый комплект не означает приёмку точности.

2026-10-18: [выполнены5 раздельных проверок исправлений](docs/ALGORITHM_CHECK_RESULTS_20261018.md).
Отбор по машине реализован и проверен, но реальная точность ухудшилась —
default не заменён. Приняты одинаковые ограничения длительностиK2/K3:
контрпример20/80с исправлен, три реальные истории15/17,1/8,3/9 сохранены
и подтверждены отдельными production-прогонами. Остальные варианты отклонены,
включая положительные фронты и цензурирование пустот. Реального прироста
временной точности нет; все отрицательные результаты сохранены. Раунд завершён.

2026-10-18: [проверены все три ответа Gemini](docs/GEMINI_REVIEW_ASSESSMENT_20261018.md).
Подтверждена потеря событий других машин при выборе RELEASE по всему movement.
Часть причин/гарантий Gemini не подтверждена; default использует permissions,
BIC работает, хорошийK3 тоже имеет1unsupported-фазу. Отдельный приоритет —
победа периодической начальной разметки над уточнением на17. Новых fits и
правок алгоритма нет. Следующий обоснованный опыт — selector по траектории,
отдельно от длительностей/K/модели пустот, с новым явным cache selection.

Пакет Gemini проверен после свежей распаковки:478 файлов,9 602 084байта,
все SHA-256/CRC и точное повторение оценок на3 event caches PASS. Итоговый файл:
`../deliverables/traffic_phase_gemini_review_20261018_v2.zip`.
Протокол: `evidence/gemini_review_20261018/receipt.json`. Код алгоритма сохранён.

2026-10-18: по запросу пользователя подготовлен компактный пакет для независимого
ревью Gemini: весь текущий Python-код app/scripts/tests, схемы, полный cache
событий и predictions трёх размеченных записей, исходные manual_marks и operator
reviews, исходные фрагменты траекторий с явными границами/обрезками и SHA-256.
Задание: docs/GEMINI_REVIEW_BRIEF_20261018.md. Сборщик ограничивает ZIP10МБ,
переносимый verifier пересчитывает прежние оценки без fitting. Точность и
default-алгоритм при подготовке ревью не меняются; новая модель не запускалась.

2026-10-18: [проверена ручная разметка и исправлена схема Свердловского](docs/MANUAL_MARKS_VALIDATION_20261018.md).
Четыре основных светофора, допсекции только N/E; W/S без них. В интерфейсе
отдельная оценка сигналов по локальной истории и явный профиль перекрёстка.
Свежие полные прогоны всех3 JSON:15/17,1/8,3/9 границ в ±2с; задержка ручного
нажатия0–3с проверена отдельно без сдвига. Пять ложных переключений одинакового
состояния объединены. Фильтрация каналов ухудшила результат и отклонена;
предсказания сохранены.1348 full PASS +33 targeted PASS, Edge3 viewers PASS.
Исправление схемы не закрывает оставшиеся ошибки времени на двух записях;
это следующий алгоритмический пробел. Main и2D.1 FAIL/default-off сохранены.

2026-10-18: [исправлен основной пространственный просмотр](docs/MODEL_PHASE_VIEW_20261018.md)
после сообщения о постоянных «?». По умолчанию показаны цветные характеристики
движений текущей логической фазы; неподтверждённые лампы доступны отдельным
переключателем и остаются UNKNOWN. Есть перерисованный реальный результат
пользователя без нового fitting/чтения архива, синтетический пример,73 targeted
PASS и браузерная проверка2 результатов (desktop/mobile, playback, seek).
Изменение отображения, не рост точности; main/прежние результаты/2D.1 сохранены.

2026-10-18: подготовлен [комплект для сдачи](docs/DELIVERY_20261018.md).
Исправлена зависимость временной привязки длинных записей от нумерации фаз;
четыре независимых FAIL до исправления, PASS после. Устранены конфликт сбора
pytest и отсутствие scripts в Dockerfile; исторические code seals проверяются
по сохранённым точным Git blobs, без изменения прежних результатов. Есть
Windows installer, фиксированные версии проверенного Python 3.12 окружения,
синтетический HTML с40 траекториями и проверка HTTP/пакетного скачивания.
В clean Python3.12 исправлен низкий resolution таймера бюджета выборки
(perf_counter, отказ на deadline); сохранены исходный FAIL и независимые тесты.
Финальный полный прогон clean Python3.12:1325 PASS,0 FAIL; smoke/compile/launcher
и обязательная legacy Lenina regression PASS. Контейнер не запускался без daemon.
Это доставка приложения, не итоговая приёмка точности: raw19/34, baseline17/34,
новый операторский набор0/11, K3/2/3 против3/2/2; нового real replay нет.
2D.1 FAIL/default-off, physical UNKNOWN, main и исторические artifacts сохранены.
Следующий критический шаг качества — observation/delay/demand и независимая
оценка; регистрацию программы для ЭВМ не путать с ARM или доказательством точности.

2026-10-18: [car-registration гипотеза проверена и отвергнута](docs/ENTHUSIASTS_CAR_REGISTRATION_20261018.md).
Train3.6px/full rank не прошёл distinct-car controls; проекция пересекает road
horizon. Experimental calibration CLI теперь проверяет весь supplied road scope
и отказывает до clock-set/scoring.53 tests PASS; отрицательные fits/annotation
correction сохранены. Clock transforms0, phase replay0,2D.1 FAIL/default-off.
Нужны однозначные пространственно разнесённые anchors и coordinate semantics;
не переносить локальную train accuracy на другие подходы или lamp timing.

2026-10-18: [происхождение видео Энтузиастов подтверждено](docs/ENTHUSIASTS_VEHICLE_LINK_20261018.md).
Полный Инфо.docx прямо связывает архив05.10 с public video; полный SHA256/MD5
локального6.79GB MP4 совпали с supplier-linked resource. Это закрывает source
provenance, несмотря на offline millis2025 против camera2024; clock link не закрыт.
Один малый JSON entry:245tracks/39215detections,38 новых video contexts, три bus
candidates остаются provisional (поставщик рекомендует car). Принятых anchors0,
clock fit0, paired metrics UNAVAILABLE. Следующий вход — same-exposure/PTS links
либо плотный independent car matching с контрольными машинами; не phase alignment.
Main/default/исторические результаты и2D.1 FAIL сохранены.

2026-10-17: [новое5ч видео Энтузиастов проверено](docs/ENTHUSIASTS_VIDEO_INTAKE_20261017.md).
200 native frames:4 независимых appearance brackets по66.7мс, без model predictions.
FPS gaps33/67/100мс, не ground truth1мс. Камера05.10.2024, но6 prefixes JSON
из архива05.10 имеют millis23.02.2025; Инфо.docx предупреждает об offline clocks.
Paired evaluation UNAVAILABLE до независимой PTS↔detection/same-car связи;
видео-reference доступен, другие heads не инвертируются из одной секции.64 tests,
без fitting/replay/default changes. Следующий путь — независимая registration/
clock проверка этого нового материала; не phase-based alignment или fixed lag.

2026-10-17: [все8 подтверждённых Astra defects закрыты тестами](docs/REVIEW_CLOSURE_RESULTS_20261017.md).
Сейчас D4/D5/D6/D8 исправлены вместе: membership/circular matching с abstention,
общая quality selection, joint signatures без exclusive stream, censored baseline
без raw/zero fallback.291 уникальный PASS, review XFAIL0;2 stale tests исправлены
по прежним контрактам, исходные FAIL сохранены. Один frozen cached run3 после
code commit: raw19/34 и K3/2/3 exact, baseline17/34, у19 nearest MAE3.9516→4.3177
регрессирует, у17 matched MAE .7483→.7198. Тюнинга нет. Качественный gate NOT_READY,
2D.1 FAIL/default-off и UNKNOWN сохранены. Следующий критический алгоритмический
шаг — проверенная method-specific observation model/delay/demand и независимая
calibration/validation, затем local history. Не обещать идеальность и не заменять
отсутствующие наблюдения GREEN/RED или fixed−2с. Main/исторические artifacts intact.

2026-10-17: [D7 tied ranks исправлен](docs/TIED_RANKS_RESULTS_20261017.md).
Равным probabilities назначаются средние ранги; независимые feature/decision
counterexamples и все120 перестановок full witness проходят.240 уникальных PASS,
4 strict XFAIL(D4/D5/D6/D8). Единственный frozen cached run3 после code commit:
rank diagnostics изменились, но K3/2/3/raw19/34/baseline17/34 и все15 fits exact.
Structural PASS, benefit FAIL_NO_GAIN; tuning и timeout нет. Следующая отдельная
задача D6 — поддержка joint shared signatures без требования exclusive stream.
Main/2D.1 FAIL/default-off/UNKNOWN и independent validation ограничения сохранены.

2026-10-17: [D2+D3 score contract исправлен](docs/SCORE_CONTRACT_RESULTS_20261017.md).
Score refinement относится к возвращённым params; K сравнивает единый data LL,
а decoder penalty маркирован отдельно.225 уникальных PASS,6 strict XFAIL для5
оставшихся D4-D8. Exact unchanged control; один frozen cached run3: все15
candidate labels/probs и итоговые raw/baseline histories exact, K3/2/3,
raw19/34,baseline17/34. Structural PASS, benefit FAIL_NO_GAIN, без tuning.
Следующий шаг D7 tie-invariant redundancy, затем D6 joint shared signatures;
не новый UI или повтор calibration одних машин.2D.1 FAIL/default-off сохранён,
независимая observation/lamp validation открыта; main не изменён.

2026-10-17: [оба внешних ревью проверены локально](docs/REVIEW_RESPONSE_20261017.md).
Astra:8 дефектов воспроизведены; D1(потеря K3 split-seeds) исправлен единственным
переносом существующего блока.208 PASS,8 strict XFAIL для7 открытых дефектов.
Нативный unchanged control exact; один cached run3 файлов после code/config
commit,6 новых split refinements выполнены, но не выбраны: K3/2/3,raw19/34,
baseline17/34 без изменений, benefit gate FAIL_NO_GAIN. Нового тюнинга нет.
Gemini не видел код; его fixed−2с/4с, queue⇒RED, positive-motion⇒GREEN,
profile-score confidence и гарантии anchored DP не приняты как доказательства.
Полная замена архитектуры пока не обоснована. Следующий алгоритмический приоритет:
единый контракт score/data_loglik/params для seed/refined(D2+D3), затем
tie-invariant redundancy и joint shared signatures(D7/D6), circular matching/
общий выбор ensemble(D4/D5), censored baseline(D8). Каждый эффект отделять.
Калибровку наблюдений вести отдельным этапом, без ожидания supplier для кодовых
дефектов.2D.1 FAIL/default-off,UNKNOWN и main сохранены; знакомые данные development.

2026-10-16: выполнено [алгоритмическое исправление HSMM](docs/HSMM_RECURRENCE_RESULTS_20261016.md),
без UI. Исправлены ложный запрет короткого предшественника перед длинной фазой и
bin/second mismatch штрафа при dt≠1. Независимый exhaustive oracle:12 FAIL до
исправления, все17 cases PASS после;199 уникальных targeted checks прошли.
Один unchanged control точно воспроизвёл saved schedule/K/period. Затем один
cached-evidence development run3 записей без rawJSON ingestion/настройки: некоторые
невыбранные кандидаты улучшили objective, итоговые schedules и метрики неизменны.
Raw19/34, baseline17/34, K3/2/3 против3/2/2; это **не рост реальной точности**.
2D.1 FAIL/default-off,main/selector/period/Kcriterion/mapping/UNKNOWN сохранены.
Следующий алгоритмический пункт — отдельным независимым structural test проверить
seed candidate flow в em_fit: K3 split-seeds добавляются после построения unique,
но оценочный цикл проходит только unique. Не подбирать этот шаг по ошибкам записи6.
Calibration/отдельная validation остаются обязательными для приёмки точности,
но не блокируют исправления математически воспроизводимых ошибок ядра.

2026-10-16: [bounded batch JSON/ZIP→сеансы→HTML/ZIP готов](docs/BOUNDED_ARCHIVE_BATCH_20261016.md).
Автоматически обрабатываются отдельные source/session views без общего archive K;
один extraction на источник, отдельный subprocess с hard wall timeout, общие
job/time/input/output budgets. API/CLI, отдельные predictions, UNKNOWN/partial и
скачивание ZIP; streaming upload cap до multipart spooling.317 tests, один
технический batch из3 сохранённых synthetic sessions за16.7826с, затем только
UI replay. В screenshot найдено обрезание вложенного отчёта; исправлена высота.
Полное сравнение state выявило старый query timestamp=start segment в HTML;
исправлены только метаданные,15/15 финальных queries exact. K/period/schedule/
event selection сохранены, runtime diagnostics различаются ожидаемо.
Пункты8/9 продвинуты; полноценная точность/эксплуатационная приёмка не завершены.
Без hard RAM cap, без independent hardware validation;2D.1 FAIL/main/default
сохранены. Следующий критический вход — producer frame↔millis связь и отдельная
validation session, затем заранее заданная calibration и frozen validation;
не повтор уже непринятых synthetic/replay экспериментов.

2026-10-16: [archive/session isolation доведён до HTML](docs/ARCHIVE_SESSION_ISOLATION_20261016.md).
Canonical V9 не объединяет разные ZIP JSON по умолчанию; metadata choices до
extraction, session choices до model fitting. Тот же guard у discover_records,
тот же selector только на выбранном scope, существующий gap1800с не менялся.
API/UI/CLI поддерживают выбор; OTHER intervals UNKNOWN.219 tests, один synthetic
ordinary discovery и actual browser409→409→200,40/40 tracks/events. Mobile defect
найден по screenshot и исправлен с saved replay без нового fit;12 queries совпали
с Python. Односеансовый event bundle exact baseline parity, fit functions AST
unchanged. Main/2D.1 FAIL и real metrics сохранены. Batch-all-sources, общие
ресурсные лимиты, точная локальная история и independent calibration ещё открыты.

2026-10-16: [исправлен реальный JSON/ZIP input defect](docs/STRICT_JSON_INPUT_20261016.md),
пункт9 плана. Два streaming readers отвергали пустой[] и принимали лишние closing
brackets/records вне массива; теперь закрытие/EOF/лимит объекта корректны.
Canonical V9 source закрывается при ошибке: Windows ZIP cleanup больше не
подменяет JSON error на WinError32.172 tests,6 multipart API requests, реальные
7tracks/3851detections JSON/ZIP равны stdlib. Новых fitting/phase metrics нет;
2D.1 FAIL,main/default сохранены. Calibration ждёт producer input; доступный
следующий шаг — изоляция archive sessions/provenance, не повтор clock diagnostics.

2026-10-16: [доступность frame↔clock входов проверена](docs/FRAME_CLOCK_INPUTS_20261016.md).
В3851 detections всех7 сохранённых raw tracks frame/PTS link отсутствует;
container metadata MP4 не связывает camera clock с JSON. Различающиеся FPS
поля не использованы для выдуманной frame-time привязки. Готов bounded manifest
checker+пустой template и точный локальный supplier request;53 tests. Нужен
исходный exposure/PTS/millis fragment либо механизм timestamping от producer.
Новые fitting/replay не запускались; main/default/2D.1 FAIL сохранены.

2026-10-16: [clock/vehicle association check выполнен](docs/CLOCK_OBSERVATION_RESULTS_20261016.md).
Три overlay readouts несовместимы с прежним candidate и frozen-H set при обеих
условных zero-latency display-моделях. Причина не установлена, offset не менялся.
Все8 video-motion/H1 associations сохранены (2 до,5 после,1 касание), без delay
fit.50 tests, один115562B checker run. Нужна detection timestamp↔camera frame
привязка независимо от положения машины либо описание overlay/detection timing;
joint calibration UNAVAILABLE. Main/default/2D.1 FAIL и метрики неизменны.

2026-10-16: пользователь уточнил источник `millis`: **«Из часов камеры»**.
Ответ сохранён как [user provenance](evidence/camera_clock_provenance_20261016/user_confirmation.json)
для обсуждаемой H1 calibration, без обобщения на все архивы/поля. Это закрывает
вопрос происхождения на уровне сообщения пользователя, но не измеряет sync,
latency или drift. Старые sealed artifacts, диагностический offset и UNKNOWN
не изменены. Следующий шаг — совместный clock/geometry uncertainty protocol,
а не повторный вопрос об источнике часов или новый fitting.

2026-10-16: [H1/clock facts проверены по существующим anchors](docs/H1_CONFIRMATION_20261016.md).
На3 полных сохранённых кадрах прочитан camera timestamp, increments2+2с совпали
с PTS; это локальный readout check, не JSON sync certificate. Source raw7 и4
withheld registration anchors сверены, N->_S/N->_E proposals сохранены с
verified=false; operator video-relative H1 mapping уже подтверждён. В Инфо.docx
найдено явное предупреждение offline processing/millis≠real event time (scope
поля/этого сеанса не уточнён). На момент этого предыдущего checkpoint источник
часов ожидался; ответ пользователя внесён выше. Joint error model остаётся
открытой.25 tests; без новых fits/кадров/replay, main/default/2D.1 FAIL сохранены.

2026-10-16: [критерии и calibration evidence bundle подготовлены](docs/CALIBRATION_BUNDLE_20261016.md).
30 typed records (9 H1 appearance,8 video-motion,8 RELEASE proxies,5 operator
reports), source hashes и17 blank independent-review tasks;14 endpoint frames
и10 derived proof images проверены.31 tests; без fitting/новых predictions.
Clock transform/prior/delay не приняты; metric eligibility явно unavailable там,
где нет truth. Следующий шаг — отдельный joint clock/geometry/mapping protocol
по independent anchors, затем bounded observation calibration; не phase-error
alignment или новый удобный synthetic run. 2D.1 FAIL и main/defaults сохранены.

2026-10-16: [настоящий browser ZIP→spatial HTML smoke выполнен](docs/WEB_ARCHIVE_QA_20261016.md).
Synthetic40 и real243 tracks обработаны, corrupt ZIP422. Исправлены bypass
общего контракта в spatial JS/JSONL, implicit colors/modulo fallback и explicit
plan overwrite (перенос cb104669).111 browser queries совпали с Python, desktop/
mobile screenshots просмотрены;66 tests. Real subsetK2 не объявлен верным без
независимого complete plan. C: free0B обойдён task-local temp на D; чужие файлы
не удалялись. 2D.1 FAIL и прежние метрики сохранены; это приёмка технического
web flow, не всей точности/продукта. Main и inference defaults не менялись.

2026-10-16: [offline JSON/ZIP route и HTML подключены к product/query contract](docs/OFFLINE_PRODUCT_HTML_20261016.md).
Убран отдельный JS activity→lamp threshold и fallback на последний сегмент.
Есть `--prediction` без fitting и три готовых HTML,52 tests; K/period/schedule/
selection hashes совпадают с предыдущим export. Raw JSON/ZIP route сохранён,
проверен без реального fitting. Browser visual QA не выполнена из-за ошибки
browser runtime; UI/checklist ещё не приняты целиком. 2D.1 FAIL,2/8 закрытых
инженерных пунктов, main/inference default и исторические метрики сохранены.

2026-10-16: реализован [единый product result для сохранённых predictions](docs/PRODUCT_RESULT_20261016.md).
K/period/schedule/selection сохранены на трёх записях;42 tests pass. Движения
по source zones, shared activity signatures, общий logical query и UNKNOWN hardware
готовы для consumers. Это ещё не новый raw JSON/ZIP endpoint и не финальный HTML.
По явно заданному checklist закрыто2/8 инженерных пунктов (25%), не процент
кода/точности/оставшегося времени. Следующий доступный шаг — интеграция этого
контракта с существующими offline input/HTML, параллельно независимому пилоту.
2D.1 FAIL/default-off, main и исторические результаты сохранены.

2026-10-16: выполнен [metadata-only допуск реального пилота](docs/REAL_PILOT_READINESS_20261016.md).
Текущие 243-track/A/B блоки — одна development-сессия, не независимый holdout.
Есть запускаемый intake, provenance seals и 31 checks, без нового inference/replay.
Следующий конкретный вход — отдельная пара JSON + независимый источник сигналов
для validation того же перекрёстка и документированная calibration/sync/model
для текущей пары. Пять последовательных шагов и критерии приведены в документе;
synthetic defaults не переносятся в реальные параметры. 2D.1 FAIL сохраняется.

## Текущий критический путь к продукту — уточнение 2026-10-16

Выполнено: [bounded-history exact DP](docs/BOUNDED_FACTOR_RESULTS_20261016.md).
Nonlocal q support до3 cells(default), до5 явно; closure potentials + history/
run-length/count messages без enumeration/beam. Oracle equivalence,178 checks;
один64с delayed-pair technical example завершён, не recovery/real accuracy.
2D.1 FAIL; default/core/priors и historical evidence сохранены.
Следующий барьер — применимость observation assumptions на реальных inputs,
independent calibration/validation и контекстная обработка длинных sessions с
общими vehicle IDs. Не переносить synthetic rates/delays и не заменять этот
пункт ещё одной удобной recovery suite.80с context и duration4..48с остаются.

Выполнено: [context/query censoring](docs/CONTEXT_OBSERVATION_RESULTS_20261016.md)
под supplied bounded delays. Target отделён от latent context, unsafe edges
UNKNOWN; явный rounded query kernel в существующем интеграторе.106+34 checks,
без recovery/real replay. Это условное решение population-edge contract,
не calibration реальных RELEASE. Strict/default остаётся require_complete.
Также выполнен [exact cell-local DP](docs/LOCAL_FACTOR_DP_20261016.md):12 tests,
эквивалентность oracle для коротких cases,64с/no-demand normalization без полного
перебора. Это local subset, широкие kernels явно unavailable. Следующий deliverable —
bounded expanded history для nonlocal factors, затем реальная calibration/validation.
Не переходить к full enumeration/новой recovery suite вместо снятия scaling blocker.
2D.1 FAIL сохраняется.

Независимое ревью получено: [ответ/проверенные findings](docs/REVIEW_RESPONSE_20261015.md).
Закрыт P1 query-completeness: short query больше не создаёт ложное negative
evidence вне доставки; shared guard для обоих likelihood backends, rounded
timestamp support,108+16 tests. Исторические artifacts/default сохранены.
Следующий маршрут: (1) согласованный latent prehistory/context для реальных окон;
(2) scalable fixed-K inference с доказанной factorization и контролем truncation,
полный перебор только oracle; (3) независимый calibration/validation пилот при
наличии sessions/sync, без переноса synthetic rates; (4) K/состав/секции и
сквозная приёмка существующего HTML.2D.1 FAIL; пилотные пороги из ревью пока
предложения, не достигнутые результаты. Не запускать новую recovery suite
вместо исправления identified blockers.

Новейшая проверка: [sparse stochastic durations](docs/SPARSE_DURATION_RESULTS_20261015.md)
по frozen seeds7/23: core flat8/12 PASS,soft7/12, synthetic29/34 matched±2с;
hold+30 упирается в path budget.2D.1 FAIL, никаких post-result настроек.
Полный перебор — small-input reference, не production решение длинных историй.
Следующий приоритет: независимое review по `EXTERNAL_REVIEW_PROMPT.md`, выбор
scalable inference с обоснованной factorization/approximation и короткого пути
к usable trajectory-only output. Не повторять ту же calibration или новые
удобные synthetic suites вместо снятия computational/observation blockers.

Последний выполненный шаг: [unknown initial phase/count](docs/UNANCHORED_SEQUENCE_RESULTS_20261015.md).
Opt-in full finite alternatives при fixed K/order, явный stationary-start prior,
rounded event likelihood;105 pre-run tests+3 artifact checks. Один short witness
run5 cases, без real replay. Unknown-start/count барьер снят только в bounded
grid model;2D.1 ещё FAIL. Следующая приёмка — sparse stochastic hold/shortening
с разными initial ages и без жёстко фиксирующего границы короткого horizon.

Новее: [rounded observation backend](docs/ROUNDED_OBSERVATION_20261015.md)
снимает требование observed timestamps=250ms+2s*n, через точный интеграл
continuous latent vehicle time и supplied rounding kernel.87 targeted tests,
без inference/real replay; opt-in, production unchanged. Следующий барьер —
unknown initial phase/start/count при fixed K/order и bounded alternatives;
phase/intensity grid2с и реальная calibration остаются открыты.

Последний шаг: [phase observation bridge](docs/PHASE_OBSERVATION_BRIDGE_20261015.md)
подключает lossless event views к подготовке существующего joint likelihood.
74 targeted tests; оба сохранённых реальных окна честно unavailable из-за
неизвестных scientific inputs. Нового inference/real replay нет. Следующий
алгоритмический scope — непрерывная/rounded timestamp observation model и
неизвестный start/count, с отдельно зафиксированными assumptions до запуска;
не повторная разметка восьми машин и не новый K search.

Цель неизменна: **JSON/ZIP → подходы/движения → K и состав фаз → локальная история
с продлениями → возможные аппаратные секции → согласованный HTML/API**.
Завершение определяется этим сквозным результатом и независимой проверкой,
а не числом calibration-отчётов или synthetic tests. Основные функции ещё не приняты;
обоснованного процента «почти готово» сейчас нет.

1. **Выполнен opt-in шаг:** [локализация раннего vehicle restart proxy](docs/RESTART_LOCALIZATION_20261015.md):
   существующий smoothed seed сохранить, timestamp локализовать по raw intervals,
   явные UNKNOWN/альтернативы; independent synthetic counterexamples, затем один
   check всех7 сохранённых development-треков.21 synthetic cases прошли; на известных
   машинах6 proxy/1 UNKNOWN с альтернативами. Это не phase/lamp accuracy.
   Без нового phase fitting, clock fit, видеоразметки или настройки по семи машинам.
   Default сохраняется; переход к production ещё требует отдельной validation.
2. **Проверены новые блоки, выполнена интеграция event-контракта:**
   [8 новых машин/2 окна](docs/RESTART_MULTICYCLE_VALIDATION_20261015.md), без настройки.
   A имеет ухудшение point containment2/4→1/4; B0/4→2/4. ClockA UNKNOWN,
   B conditional-compatible. По видео движение может начаться до видимого GREEN H1.
   Новый opt-in adapter подключён к существующим local evidence channels,
   сохраняет reference/UNKNOWN/alternatives без timestamp union в legacy likelihood.
   Следующий алгоритмический deliverable — ограниченная phase observation integration
   с nonexclusive/nuisance events и unknown demand под отдельным явным scope;
   не universal delay, не повторная калибровка этих машин. Default не принят.
3. **Вернуться к основной алгоритмической цепочке:** принять состав/K по движениям
   для3/4 подходов и shared movements; затем локальную историю hold/shortening
   без подмены обычным циклом. K и длительности оценивать раздельно; 2D.1 пока FAIL.
4. **Секции и режимы:** выдавать подтверждённую схему либо альтернативы с причиной
   UNKNOWN. Автомобильный поворот не отличает стрелку от permissive движения.
   Продление оценивается как временное отклонение; пожарная машина/нагрузка/ДТП
   не назначаются причиной без отдельного evidence. Сценарии РФ — матрица тестов
   и явного unsupported, не обещание распознать все причины по JSON.
5. **Сквозная приёмка:** соединить уже существующий HTML/FastAPI с общим query
   contract, интегрировать существующую explicit-plan правку без дубля; затем
   независимые реальные sessions, ошибки/coverage/UNKNOWN, ZIP limits и установка.

Ручное видео используется для разработки/validation. Пользователь готового
продукта не обязан размечать каждый новый JSON. Последний явно разрешённый шаг —
observation-contract integration, выполненный без sequence inference.
Новый decoder/likelihood/prior experiment требует отдельного ограниченного scope.
Ниже сохранён журнал прежних этапов.

2026-10-15: [локальная image/clock привязка проверена на4 withheld машинах](docs/LOCAL_VEHICLE_REGISTRATION_20261015.md).
Один расчёт по3 другим машинам, без signal/RELEASE labels; max withheld residual
снизился158→42px при почти неизменных часах. Найден отдельный technical counterexample:
симметричное сглаживание выдаёт restart18.9s при начале world-motion20.0s.
Следующий инженерный пункт — исправлять локализацию vehicle restart по независимым
synthetic counterexamples, затем multi-cycle calibration/validation; не общий offset
по7 известным машинам. Production/default и прежний2D.1 FAIL не изменены.

2026-10-15: пользователь подтвердил H1 по фото синей машины: подъезд снизу,
основной зелёный прямо вверх-вправо, допсекция налево вверх-влево.
Источник сохранён в `evidence/video_calibration_intake_20261015/h1_operator_mapping.json`.
Повторно спрашивать эти направления не нужно. Это operator mapping, без
сертификации геометрии/часов и protected/permissive semantics. Следующий пункт —
проверка локальных same-car anchors, затем delay calibration нескольких циклов.

2026-10-15: [проверены все7 N-origin машин по видео](docs/SEVEN_RESTART_VIDEO_REVIEW_20261015.md).
Видимое начало движения сохранено отдельно от RELEASE. По frozen clock6/7 точек
раньше brackets, но conditional clock sets пересекаются7/7; ошибка extractor
не отделена от локальной регистрации. Identity provisional, timing validation
UNAVAILABLE. Следующий конкретный пункт — независимые same-car/feature anchors
в нижней области кадра, затем подтверждённый mapping и delay по нескольким циклам.
Новых model runs/offset/threshold изменений нет; 2D.1 FAIL/default-off сохранён.

2026-10-15, шаг3: [первое реальное сопоставление событий и H1](docs/EVENT_SIGNAL_ASSOCIATIONS_20261015.md)
выполнено по sealed extraction, без нового phase fitting. Получены method-specific
offsets и сохранены154 локальных zone proxies, теряемых текущим selector.
Следующий пункт: H1 mapping и независимая проверка restart для7 N-потоковых ТС;
затем delay calibration по нескольким циклам и отдельная validation. Простое
timestamp union в старый likelihood не продвигать; 2D.1 FAIL/default-off сохранён.

2026-10-15, шаг2: [привязка по3 ТС](docs/VEHICLE_CLOCK_ALIGNMENT_20261015.md)
поддержана независимым от fit троллейбусом; max residual23.31px при допуске50px.
Получен локальный clock/image profile, без production использования и без
заявления calibrated timing accuracy. Следующий пункт — method-specific delay
по наблюдаемому H1 с подтверждённым подходом и отдельная validation session.
Основной алгоритм, UNKNOWN и прежний2D.1 FAIL сохранены.

2026-10-15, шаг2: выполнен [прямой review видео](docs/VIDEO_BOUNDARY_VERIFICATION_20261015.md),
90 кадров H1; обнаружены мигание допсекции и неодинаковая семантика меток группы2.
Сохранены покадровые доказательства переходов. Следующий незакрытый пункт —
3 подтверждённых same-car anchors и оценка sync uncertainty, затем независимый
validation split и calibration event→signal delay. Нового model run не было.

2026-10-15, шаг2: подготовлен первый реальный video calibration sample
(243 целых трека,10:04–10:07), просмотр и увеличение видимой секции работают.
[Как разметить](docs/VIDEO_CALIBRATION_PILOT_20261015.md). Следующее действие —
проверить3 одинаковые машины на видео/JSON и разметить читаемые состояния H1.
Синхронизация, аппаратный mapping и независимый validation split пока не подтверждены;
шаг2 не закрыт. Алгоритм/default и прежние FAIL/метрики сохранены.

Обновлено 2026-10-15. Цель пользователя: JSON/архив одного перекрёстка → подходы
и движения → K и состав фаз → обычные светофоры/допсекции → локальная история
с продлениями и другими режимами → понятная HTML-визуализация через FastAPI.
Подробная цель: [PRODUCT_GOAL](docs/PRODUCT_GOAL.md). Текущие доказательства:
[PROJECT_STATUS](docs/PROJECT_STATUS.md), [аудит](docs/PROJECT_AUDIT_20261015.md).

Основа: `45544c3c353c9aae26f301e4711ff1645a0f3a56`.
2C и protective core query contract приняты; 2D.1 FAIL, opt-in/default-off.
Development: K3/2/3 против truth3/2/2, raw19/34 границ в ±2с.
Nominal10 не выбран. Synthetic success не доказывает реальную точность ламп.

| Шаг | Результат | Условие завершения |
|---|---|---|
| **1. Контур ручной проверки — реализован** | Локальный просмотр JSON, движение машин, выбор трека, интервальные метки, экспорт/возобновление | Протестированы время, provenance, source hash, gaps, round-trip, limits; разметка по trajectories явно hypothesis, без скрытого inference |
| 2. Независимый calibration-пилот | Один calibration и отдельный validation session; источник сигналов, sync uncertainty, mapping и определения полей | Нет пересечений/дубликатов; проверена независимость truth, зафиксированы split и критерии до оценки |
| 3. Согласовать evidence и наблюдаемость | Модель event↔signal delay, demand/exposure assumptions; допустимые альтернативы | Проверка по calibration, затем frozen validation; sampling uncertainty отдельно от signal uncertainty; нет GREEN/RED из отсутствия спроса |
| 4. Закрыть K и состав фаз | Надёжные K/порядок, shared movements, supported/unsupported groups для 3/4 подходов и K4+ | Независимые структурные тесты и реальные validation-метрики; ошибки K и групп не маскируются точностью периода |
| 5. Закрыть локальную историю 2D.1 | Продления/сокращения при фиксированной структуре, оценка точек и интервалов | Прежний per-case point gate не ослабляется; interval coverage/width, UNKNOWN и prior dependence отдельно; реальные ошибки/регрессии опубликованы |
| 6. Аппаратная схема | Несколько signal heads на подходе, одна/несколько допсекций, permissive/protected, shared movements | Сопоставление с независимой схемой/видео; поворот не доказывает стрелку, неоднозначность сохраняется |
| 7. Реестр режимов РФ | Смена плана, вызов/пропуск/порядок, мигание/переходы, приоритет, no-demand, блокировка, специальные сигналы | Для каждой строки: модель, входы, independent test или явный unsupported/UNKNOWN; причина события не выдумывается |
| 8. Сквозной HTML/API contract | Общие reconstructed/configured semantics от core до браузера; правильная геометрия/подходы | UNKNOWN не превращается в RED; fixed transitions только configured; интегрирована существующая explicit-plan правка; реальные UI counterexamples проходят |
| 9. Приёмка и эксплуатация | JSON/ZIP end-to-end, ресурсные лимиты, воспроизводимость, документация | Независимый validation, agreed SLA, CI, тесты повреждений/дубликатов/большого входа/нагрузки, ясные ошибки, установка и итоговый отчёт |

Шаги 4–6 связаны и проверяются отдельно; нельзя объявлять правильную историю
при ошибочном K или физическую точность по логическим фазам. Исправления уже
подтверждённых UI-дефектов из шага 8 можно выполнить раньше отдельным изменением,
не подменяя ими проверку алгоритма. FastAPI уже есть, переписывать его не нужно.

Ручная разметка по JSON полезна для времени/видимости автомобильных событий и
логических гипотез, но не является независимой lamp truth. Для пилота нужны
видео с секциями либо документированный журнал контроллера и синхронизация.
Список входов: VALIDATION_PROTOCOL.md §8; использовать прежний independent-review
template. Три знакомые записи остаются development, не untouched holdout.

Synthetic tests проверяют контракт, граничные случаи и recovery при объявленной
модели. Их дополняют реальные данные; одинаковая надёжность не предполагается.
До каждого эксперимента фиксируются гипотеза, cases/seeds, budget и критерии;
после результатов параметры не подгоняются. Main и production defaults не менять
без отдельного решения. Каждая задача должна закрывать строку этого плана.

Шаг 1 реализован: `START_ANNOTATION.cmd`, `/annotation`, инструкция
[ANNOTATION_WORKBENCH](docs/ANNOTATION_WORKBENCH.md). Проверено 18 тестов и
браузерный round-trip с небольшим реальным фрагментом без inference.
Получены три экспертных экспорта (14 интервалов), проверены schema и source SHA256:
[приём материалов](docs/MANUAL_REVIEW_INTAKE_20261015.md). Заявленная ошибка ≤2с
сохранена как оценка оператора. Следующий шаг — спецификация адаптера интервалов
и независимый calibration-пилот; приём этих файлов не закрывает независимую проверку.

2026-10-15: адаптер и один frozen baseline выполнены, 50 tests passed. На новых
датах K совпал 3/3, но raw/baseline=0/11 внутренних границ при ±2с. Исторические
19/34 относятся к другим датам. [Результаты и следующий эксперимент](docs/EXPERT_INTERVAL_BASELINE_20261015.md).
Приоритет шага 3: устранить потерю локально доступного evidence из-за RELEASE
в другой части сеанса, сохраняя различие методов и UNKNOWN event-to-signal delay.
Механизм selector воспроизведён одним отдельным тестом. Следующее изменение
сначала проверить независимо на synthetic cases; параметры по этим меткам не
подбирать. Production policy и непринятый 2D.1 в этом шаге не изменялись.

2026-10-15: отдельное local-evidence представление реализовано и прошло 49 tests.
Все 80 ранее selected events сохранены; 256 crossing-proxy возвращены без
смешивания методов и двойного счёта треков. [Результат](docs/LOCAL_EVIDENCE_CHANNELS_RESULTS_20261015.md).
Следующая часть шага 3 — совместная observation model на трек: явные delay,
nonexclusive/permissive marks, demand и exposure. Сначала независимый paired-event
synthetic эксперимент; production/default и метрики не менялись. Это ещё не
приёмка восстановления времён сигнала и не закрытие calibration-пилота.

2026-10-15: совместный vehicle likelihood реализован отдельно и прошёл59 tests;
один fixed synthetic suite дал29/30 и30/30 core boundaries для двух priors.
Flat prior имеет один per-case FAIL; production prior не выбирался.
[Результаты и ограничения](docs/JOINT_TRACK_OBSERVATION_RESULTS_20261015.md).
Known anchor/count/rates/delays остаются synthetic assumptions; реальные
0/11 и19/34 не изменялись. Следующий практический приоритет шага2 — проверить
имеющиеся видео27.02 и corresponding JSON на пригодность и синхронизацию для
независимого calibration-пилота. Отдельно предстоит снять known-anchor/count
ограничение модели; не заменять calibration новыми идеальными тестами.
