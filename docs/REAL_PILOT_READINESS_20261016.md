# Допуск реальных материалов к calibration/validation

Base: `e537c525e605602a1146b8e98e916fa0feacdf8c`.
Ветка: `audit/real-pilot-readiness-20261016`.

## Выполненная проверка

Новый `scripts/check_real_pilot_readiness.py` проверяет **только метаданные**:
идентичность непрерывной съёмки/исходников между split, происхождение обязательных
параметров существующего observation bridge, наличие источников синхронизации,
mapping и prior. Не запускает likelihood, decoder, fitting или replay.
Список обязательных параметров импортируется из самого bridge, без второго
набора scientific defaults. Статус `ready_for_independent_review` означал бы
полноту деклараций, **не** подтверждение их истинности и не допуск в production.
Проверка не заменяет content deduplication: ложные новые capture/source IDs
должны выявляться независимым review источников, а не этим metadata checker.

Текущий [manifest](../evidence/real_pilot_readiness_20261016/manifest.json)
регистрирует начальный участок 243 треков и A/B как три development-блока
**одной** непрерывной записи Ленина—Свердловский 27.02.2025. Другие известные
JSON/экспертные разметки остаются development; здесь не объявлен новый полный
каталог и не проводился поиск всех файлов на диске.
JSON SHA взят из сохранённого полного streaming scan, а не вычислен повторно.
Видео имеет прежние metadata/частичный fingerprint, не новый full-content SHA.
Хешированы только семь явно перечисленных небольших документов, всего 208773 байта.
Большие JSON/архивы/видео не читались.

Результат: `incomplete`. Отдельная calibration-сессия ещё не зарегистрирована
как документированная, независимая validation-сессия отсутствует. Все обязательные
scientific параметры bridge остаются незаполненными; это не утверждение, что
каждый параметр нужно получать отдельным экспериментом. Нужна совместная модель
их идентифицируемости, а не независимое угадывание rates × exposure × detection.
Local clock compatibility при фиксированной геометрии не стала calibrated joint
uncertainty. Operator mapping H1 сохранён, повторно спрашивать направления не нужно.
Он не удостоверяет raw movement labels, весь перекрёсток и protected/permissive
семантику. Supplier units и стоп-линия остаются UNKNOWN.

## Конкретный маршрут без повторения прежних восьми машин

1. **Calibration intake.** Использовать существующую пару JSON/видео 27.02 как
   development/calibration-кандидат. До новых расчётов зафиксировать независимые
   часы/события привязки, диапазон применимости и uncertainty, видимые секции и
   наблюдаемые интервалы камеры. Название файла и отсутствие машин не доказывают
   ни часы, ни coverage. Уже просмотренные участки не выдавать за untouched test.
2. **Отдельная validation-сессия.** Нужны JSON и независимый источник сигналов
   того же перекрёстка из другого непрерывного сеанса, предпочтительно другого дня.
   Контроллерный лог может заменить видео, если его семантика/часы проверяемы.
   До использования зарегистрировать original hashes, capture/session ID,
   timestamps и отсутствие дубликатов/перекрытий. Новый фрагмент того же MP4
   остаётся within-session development check.
3. **Единственный calibration-протокол.** Заполнить существующий
   [independent-review template](../evidence/video_calibration_pilot_20261015/review_template.json),
   не создавать новый интерфейс. Vehicle stop/restart и сигнальные границы
   размечать раздельно; жёлтый/невидимые секции UNKNOWN. Дополнить независимое
   соответствие raw movements ↔ группы/секции, shared movements и permissive/
   protected. Геометрию и supplier definitions приложить там, где они используются;
   иначе явно UNKNOWN и запрет зависимых утверждений.
4. **Один заранее утверждённый model-admissibility эксперимент.** Только после
   входов выше определить оцениваемые calibration-параметры, nuisance assumptions,
   источник duration prior и зависимости детекции. Проверять vehicle-delay model,
   включая движение до GREEN; не объявлять её временем реакции. Зафиксировать
   held-out протокол, бюджеты и критерии до запуска. Не выбирать synthetic prior
   по известным данным и не переносить exclusive marks на реальные RELEASE.
5. **Замороженная validation и продукт.** Отдельно оценить K/состав, point precision/
   recall ±2с и counts, интервалы/ширину, coverage/UNKNOWN и prior dependence.
   Не настраивать по validation. Затем принимать trajectory-only режим и аппаратные
   альтернативы и соединять с существующим HTML/API. Каждому новому пользователю
   размечать каждый JSON не потребуется. Lamp accuracy заявляется только для
   действительно наблюдённых секций/режимов с независимой truth.

Это план следующей работы, **не разрешение на скрытый запуск нового эксперимента**.
Нет обещания срока или точности до независимой validation. Synthetic tests полезны
для алгебры, ограничений ресурсов и контрпримеров, но не заменяют такую проверку.

## Проверки и сохранённые ограничения

Команды/результаты: `evidence/real_pilot_readiness_20261016/commands.log`.
31 tests прошли: новый intake, seals артефактов и затронутый observation bridge. Проверены same-capture
разные окна, renamed/shared original source, старый development под новым split,
NaN/отрицательная uncertainty, отсутствие scientific inputs/provenance и
неиспользование annotations. Проверка reference hashes не удостоверяет большой
исходник заново. Manifest и readiness пригодны для повторного запуска команды.

2C и защитный state/query contract приняты. 2D.1 остаётся FAIL/opt-in/default-off;
исторические реальные K3/2/3 против truth3/2/2 и raw19/34 ±2с не изменены.
Новая DP проверена только в declared finite synthetic model. Production/core,
priors, main, evaluator и predictions в этом шаге не менялись.
