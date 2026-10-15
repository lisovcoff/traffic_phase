# Промпт для независимого технического ревью

Скопируйте текст ниже в отдельный чат. Приложите evidence ZIP текущего шага
и, если GitHub недоступен ревьюеру, исходники перечисленных модулей.

---

Ты независимый senior ML/Python engineer по транспортным потокам. Проведи
критическое ревью traffic_phase: https://github.com/lisovcoff/traffic_phase .
Не считай отчёты автора доказательством корректности: сверяй с кодом и артефактами.
Если не смог прочитать код/ZIP, явно скажи это и не изображай выполненный аудит.

Цель продукта: JSON/ZIP одного3/4-подходного перекрёстка → движения → число и
состав фаз (включая shared movements) → локальная история с extension/shortening →
подтверждённая или неоднозначная схема основных/допсекций → существующий HTML/API.
Автомобильное движение не доказывает GREEN, отсутствие движения не доказывает RED,
поворот не доказывает аппаратную стрелку. Причина продления по JSON не гарантирована.
Нужен полезный автоматический продукт с явными пределами, а не бесконечный
synthetic prototype и не необоснованное обещание восстановить любые лампы.

Production/default не менялись.2C и защитный state/query contract приняты;
2D.1 FAIL. Исторические development: K3/2/3 против truth3/2/2, raw19/34 границ±2с.
Ручная trajectory-разметка не независимая lamp truth. Есть немного видео H1,
operator mapping и проверенные motion-before-visible-GREEN контрпримеры, но нет
полностью калиброванного event→signal delay/demand/permissive model. Новые8
машин дали mixed restart validation: A2/4→1/4, B0/4→2/4; timing/lamp calibration
не подтверждена. Не предлагай снова настраивать extractor по этим машинам.

Проверенная база последнего algorithm step:
`41563f5852ec2708a0db6a590d04888b256baae9`, ветка
`experiment/unanchored-phase-sequence-20261015`.
Читайте ROADMAP.md, docs/PROJECT_STATUS.md, docs/PRODUCT_GOAL.md,
app/experimental/joint_track_model.py, rounded_observation.py,
phase_observation_bridge.py, unanchored_sequence.py и соответствующие tests.
См. docs/UNANCHORED_SEQUENCE_PROTOCOL_20261015.md и RESULTS.
Новее — ветка experiment/sparse-duration-validation-20261015 и приложенный
отчёт sparse-duration проверки; при отсутствии этой ветки не выдумывай её итоги.

Модель прототипа: fixed supplied K2/K3/mapping/order, piecewise rates на2с grid,
continuous latent vehicle time, supplied Poisson rates/exposure, discrete
vehicle delay atoms, rounded timestamp cells, supplied camera windows.
Один latent vehicle — один likelihood term даже при паре RELEASE/CROSSING_PROXY.
Не positive-GREEN-delay model: off-phase intensities положительны.
Unknown initial phase/age/count: stationary grid-renewal residual prior,
оба старых duration priors flat/soft4..48с, без выбора лучшего. Полный finite
path posterior или unavailable при10000 paths/5с/32MiB allowance. Публичные
logical/physical состояния пока UNKNOWN; MAP diagnostic. Короткие16с witnesses
точны, но count4 и minimum durations практически фиксировали границы.

Нужен ответ по существу:
1. Проверь likelihood/compensator, rounding/delay/detection/censoring,
   joint-track dependence, left/right duration censoring и prior normalization.
   Укажи конкретные файл/функцию и контрпример для каждого дефекта.
2. Что подтверждено тестами, что только условно при supplied parameters, что
   принципиально неоднозначно, а что можно оценивать по trajectory-only данным?
3. Насколько finite full enumeration пригоден для минут/часов? Есть ли более
   простой bounded semi-Markov/DP/beam подход с честными truncation diagnostics,
   учитывая nonlocal log-sum joint-track likelihood? Не предлагай DP, если не
   показана нужная factorization.
4. Не ушли ли мы в сторону от продукта? Предложи один следующий эксперимент
   с наибольшим шансом снять реальный барьер, а не ещё один удобный synthetic test.
   Укажи минимально необходимые уже имеющиеся/недостающие данные.
5. Дай короткий путь до usable MVP и отдельно до независимо проверенной высокой
   точности. Какие выходы можно честно автоматизировать уже сейчас, какие требуют
   alternatives/UNKNOWN? Не обещай точные аппаратные секции по одним поворотам.

Результат: до5 приоритетных findings с воспроизводимыми контрпримерами, решение
«продолжать / изменить модель / остановить конкретный путь», один следующий scope
и критерии приёмки point accuracy, interval coverage/width, UNKNOWN и runtime.
Ничего не подбирай по трём известным development-разметкам и не называй synthetic
success lamp accuracy. Не объявляй весь проект невозможным из-за произвольного
unknown demand; оцени practically useful identifiable outputs.
