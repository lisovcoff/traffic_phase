# Совместная модель автомобиля: результат ограниченного synthetic эксперимента

Base: `59cb228516b40ad41c52334b826286500714e4b1`.
До реализации зафиксирован [протокол](JOINT_TRACK_OBSERVATION_PROTOCOL_20261015.md).
Code/config freeze: `b8f5e560b0c86f8809b48148e8ee606072a6ed7d`.

## Что реализовано

`app.experimental.joint_track_model` использует Poisson rate и supplied exposure,
совместно маргинализирует латентное время автомобиля, delay restart и transit до
crossing. Один автомобиль даёт один likelihood term, даже если видны оба события.
Пропущенный detection и censoring входят в вероятность observed pattern.
Off-phase движение разрешено положительной фоновой интенсивностью; shared
movement может поддерживаться несколькими фазами. Уверенность extractor не
превращается в вес likelihood или lamp probability.

Входом служит предыдущий local-evidence view, с известной ассоциацией наблюдений
внутри synthetic автомобиля. Неизвестная identity/method, clock/delay или missing
rates/exposure/count/anchor дают unavailable. Это ограничение данного прототипа,
а не утверждение о невозможности оценки фаз при других моделях.

Полное перечисление конечных paths даёт diagnostic MAP path и ordinal posterior
на сетке2с. Equal-tailed90% intervals относятся к **supplied модели**.
Публикуемые logical/physical states сохраняются UNKNOWN по общему state contract.
Прототип требует известных K/order/initial anchor и **четырёх observed segments**.
Поэтому здесь не проверялись discovery K, неизвестное число переходов, left
censoring, multi-regime или online. Конец horizon цензурирован, не switch.

## Проверки и ресурс

59 tests passed до suite: normalization joint observed patterns, count/exposure
closed form, redundant second mark без усиления evidence, censoring/gaps,
nonexclusive/structural-zero cases, identity/duplicates, clock/metadata guards,
rename/immutability, ресурсы, запрет truth в inference; также local channels и
прежний event-time prototype. Worker не имеет truth-файла в contract test;
evaluator отказывается работать до seal.

Один запуск: 24 case/seed inputs, каждый одновременно оценён с обоими заранее
заданными priors. Все24 — complete finite posterior, без timeout/retry; CPU
worker0.266с при бюджете60с. Это CPU time всего suite worker, не профиль отдельных
компонентов и не benchmark production pipeline. Outputs/hashes зафиксированы
до первого чтения truth для оценки. Генератор independent от decoder.

## Point и interval результаты

| Scope | flat: matched/truth/predicted | soft: matched/truth/predicted |
|---|---|---|
| Stable + hold + shortening: 10 cases | 29/30/30 | 30/30/30 |
| Correctly specified informative: 16 cases | 45/48/48 | 48/48/48 |
| No-demand / all-missing: 4 cases | 4/12/12 | 4/12/12 |
| Misspecified rate / blockage: 4 cases | 9/12/12 | 11/12/12 |
| Все24 cases | 58/72/72 | 63/72/72 |

Все matching — прежний evaluator, ±2с, без offset/permutation fitting.
В informative scope precision=recall93.75%/100%, matched MAE0.622/0.625с,
matched p952с. Это диагностические synthetic метрики при известных параметрах,
не реальная точность; число predicted boundaries задано scope, не восстановлено.

Original per-case point criterion recall>=.8: flat **9/10 PASS, 1/10 FAIL**;
soft10/10 PASS. Провал flat: hold10_K2 seed4099, truth=[10,30,40], point=[8,30,44].
Критерий не ослаблялся и не заменялся interval containment. Soft не выбран для
production. MAP paths различаются между priors в14/24 cases.

На hold30 truth=[10,50,60]с. Для seed2027 оба priors дали[10,50,60]; seed4099
flat=[10,52,60], soft=[10,50,62]. Первая граница не сдвинулась вслед за hold;
изменение длительности отражено локально, общего fitted offset нет.

Intervals по всем cases: truth внутри72/72 для каждого prior; issued72/72,
unissued0. Median width6/4с, p9517.8/14с, width<=4с35/72 и40/72.
В informative scope containment48/48, median width4с, p9511.3/9.3с,
width<=4с32/48 и35/48. Эти small-suite числа **не подтверждают nominal90%
coverage**; границы зависимы, seeds всего два, параметры rates/delays известны.
Intervals не являются lamp-switch error bounds.

No-demand и all-missing дали constant likelihood, posterior=prior (KL0),
без информативной vehicle evidence. Их случайные point matches4/12 нельзя
называть восстановлением истории. Widths12..20с явно показывают неопределённость.
Diagnostic temporal coverage полная при known-count assumption, опубликованная
logical history UNKNOWN100%, physical UNKNOWN100%; это разные величины.

Misspecification не выявляется автоматически: неверные rate/blockage assumptions
могут давать полноценный posterior. Ноль несовместимых joint patterns не
доказывает верные границы; проверка по независимому источнику остаётся необходимой.

## Следующий реальный барьер

Совместное observation likelihood теперь есть и проверено на declared generator;
переносить synthetic rates/delays, известный count или initial anchor на реальные
RELEASE нельзя. Для реальных данных нужно отдельно получить/оценить delay model,
demand/exposure и обосновать association/semantics событий. Часть характеристик
движения и взаимных времён внутри track можно измерять по trajectories; точность
их привязки к сигналу требует внешней calibration. Знание оператором перекрёстка
полезно для структуры и слабых временных гипотез, но не калибрует posterior.

Следующий практический шаг — calibration-пилот на уже указанном видео
`len_sverdl 2025-02-27T10_00_00_2025-02-27T12_00_00.mp4` и соответствующем JSON:
сначала установить наличие видимых сигналов/пригодной геометрии и проверить
совпадение времени/автомобилей, затем независимо разметить небольшой непрерывный
участок. До этого неизвестны пригодность видео и синхронизация; не назначать
им статус verified. Для validation нужен отдельный сеанс, не знакомые development
записи. Удаление known-anchor/count assumptions — отдельный bounded algorithm scope.

Main/default/production inference и реальные predictions не менялись. Старый
2D.1 остаётся FAIL; реальные 0/11 на новых датах и19/34 на прежних сохранены.
Изменение алгоритма на реальных данных и рост реальной точности не заявляются.
Артефакты: `evidence/joint_track_observation_20261015/` — manifest, inputs/truth
separation, seals, predictions, hashed evaluation adapters, comparison,
compact CSV, aggregate, commands/logs и небольшой evidence ZIP.
