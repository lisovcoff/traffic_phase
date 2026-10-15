# Подключение evidence к существующей модели наблюдений

Base: `1981bdef6e94e5e691871bb30bdb3fef7b1e36ef`.
Ветка: `experiment/phase-observation-bridge-20261015`.

Scope до проверок: только opt-in подготовка компонентов уже существующего
`joint_track_model.observation_components`, без нового likelihood, sequence inference,
fitting, prior experiment, видео или real replay. Production/default не меняется.
Прежний 2D.1 FAIL и результаты сохраняются.

## Критерии до запуска

Применить bridge к двум сохранённым evidence queries A/B без научных параметров:
обязателен structured unavailable с перечислением недостающих входов, сохранением
хеша исходного view, UNKNOWN logical/physical, без синтетических defaults.
Это проверка контракта на сохранённых данных, не реконструкция фаз.

Компактные технические counterexamples: off-phase событие до начала основной
фазы допустимо; два marks одного track дают одну vehicle contribution; silence
при supplied zero demand не различает фаз; unknown demand не превращается
в full/zero exposure; missing sources, source gap, off-grid clock и budget
дают явную причину; bijective rename и immutable inputs сохраняются.
При известном положительном demand модель может использовать отсутствие events
через Poisson compensator — это условие supplied модели, не доказательство RED.
Блокировка и отсутствие спроса могут иметь одинаковые наблюдения, причина UNKNOWN.

Лимиты: максимум512 событий; существующий q-cell budget50000 и horizon80с;
одна целевая тестовая команда, до30с CPU. Никаких recovery seeds, нового
decoder, подбора priors и оценки по фазовым меткам.

## Связь компонентов

`localized_evidence_adapter.query` → `prepare_joint_observation` → существующие
`observation_components` → компоненты для `path_loglik`.
Bridge ничего не вызывает после подготовки компонентов. Legacy HSMM не подключён:
его independent occupancy emission нельзя подменять неявным timestamp union.

Bridge требует источники rates, demand, windows, delay; не оценивает их по8 машинам.
Обязательные положительные nonexclusive intensities — ограничение этой экспериментальной
ветки для непроверенных proxies, не универсальное утверждение об аппаратных фазах.
Это допускает движение вне основной фазы без назначения permissive/нарушение/creep.
Относительная задержка внутри vehicle process не является задержкой от GREEN.

Абсолютные timestamp переводятся относительно явно supplied origin без округления.
Provenance/uncertainty исходного события остаются в исходной шкале; clock conversion
не объявляется calibration. Существующая finite clock2с+250мс не подходит для
произвольных реальных timestamps: bridge честно отказывает, не округляет данные.
Known count/start/order остаются ограничением прежнего sequence prototype;
данная подготовка likelihood их не устраняет и не выдаёт sequence estimate.

## Результат проверки

74 targeted tests passed,2.26с. Оба сохранённых views содержат по4 events/4
идентифицированных ТС. Оба дали `OBSERVATION_MODEL_INPUTS_UNKNOWN`; перечислены
недостающие scientific inputs, components отсутствуют, logical/physical UNKNOWN.
Нового sequence inference0, чтения фазовых меток0. Byte SHA исходного файла
проверен до/после. Хеши и команды: `evidence/phase_observation_bridge_20261015/`.
При финальном self-review добавлен отказ для eligible channels, которые существующая
модель не поддерживает: они не должны теряться при подготовке likelihood.

## Следующий продуктовый барьер

Для следующего bounded шага нужна event-time likelihood с supplied continuous/rounded
timestamp observation kernel и nuisance/demand model, затем неизвестный start/count.
Не переносить finite synthetic rates/delays на реальные RELEASE. Внешняя calibration
нужна для связи activity с сигналом; оценку K/состава и логических гипотез можно
продолжать при явно проверяемых assumptions и UNKNOWN. Потребитель готового продукта
не должен размечать каждый JSON. Текущая работа не повышает заявленную реальную точность.
