# traffic_phase — план до готового продукта

## Текущий критический путь к продукту — уточнение 2026-10-16

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
