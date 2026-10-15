# Context/target и цензурирование query

Base: `08f82c3b382388fc201baa82a4ec37302ef8c4e4`.
Ветка: `experiment/context-censored-observation-20261016`.
[Scope до проверок](CONTEXT_OBSERVATION_PROTOCOL_20261016.md).

Добавлен opt-in `prepare_context_observation`. Он запрашивает существующий
immutable evidence index, разделяет полный latent context и желаемый target,
сохраняет source namespace, ID/provenance машин и явно исключённые края.
Никакого decoder/sequence run или K search этот компонент не запускает.

Новый явно выбранный `query_delivery_mode=censored_reported_timestamps` учитывает
отбор округлённых меток **и в joint pattern, и в compensator**. Для query[0,2000)мс
при rounding resolution1мс/origin0 удерживаются centres0..1999мс, то есть union
rounding cells[-.5,1999.5)мс. Это пересекается с supplied camera windows и finite
latent support в прежнем точном piecewise integral. Поэтому в примере без событий
log-likelihood−.459885, а не−1.84 и не механическое−.46. Это свойство заданной
модели измерений, не повышение реальной signal accuracy.

Если RELEASE внутри query, а CROSSING вне query, отсутствие CROSSING становится
query censoring, даже при detection probability1. Истинное отключение камеры и
отбор query раздельно записаны в metadata. Нормировка retained joint patterns
в detected exposure проверена. Сам likelihood и heuristic confidence weighting
не переписаны: используется существующий интегратор, веса не добавлялись.

## Защита от внешней популяции при известных bounded delays

Для enabled каналов максимальный supplied vehicle shift=Dmax. Сохраняются только
те clock centres, чьи **целые** rounding cells лежат в[Dmax,h). Тогда при любом
допустимом shift d: u=t−d>=0 и u<h. Ни автомобиль до latent context, ни после него
не может дать оставшуюся метку в рамках этой модели. Это решает конкретный
finite-population edge witness через явное цензурирование, без выдуманной
предыстории автомобилей или объявления начала записи началом фазы.

Safe target требует полного потенциального event support внутри retained true
mark interval: [retained_start,retained_end−Dmax). Поля target/context/query/retained
support различны. Target вне safe interior получает unavailable/UNKNOWN без
fallback. Context phase history всё равно должна оцениваться совместно; нельзя
отрезать её и перезапустить phase prior на target. Неиспользуемые края не являются
RED. Здесь target не публикует фазу: logical/physical UNKNOWN100%.

Пример Dmax2с,h8с: query reported[2001,8000)мс, retained true[2000.5,7999.5)мс,
safe target[2000.5,5999.5)мс. RELEASE250мс, требующий latent−1750мс, исключён;
RELEASE2250мс с latent250мс сохранён. Другие движения и предыстория не выдуманы.
Повторное получение overlapping contexts сохраняет те же vehicle IDs: их
likelihood нельзя автоматически перемножать как независимые.

## Проверки и пределы

106 targeted tests +34 затронутых регрессии/artifact/adapter tests passed.
Итоговая общая проверка вместе с12 DP tests:152 passed,11.79с pytest wall time.
Проверены normalization, closed forms, fractional clocks, camera gaps, zero demand,
invalid/unsafe delays, numeric limits, event budget, absolute origin, rename и
immutability. Contract examples/hashes сохранены до итогового отчёта. Новых
scientific sequence runs/recovery suite/real replay0; короткие прежние inference
unit tests исполнялись как регрессии. Производительность pipeline не измерялась.

Default **по-прежнему require_complete**: старый короткий query без явного режима
цензурирования отклоняется QUERY_DOMAIN_INCOMPLETE. Finite-clock backend не
принимает этот режим ни через bridge, ни напрямую. Core/default/HSMM/K/period/
mapping/extraction, priors, thresholds и historical artifacts не изменены.
2D.1 остаётся FAIL; реальные K3/2/3 vs truth3/2/2 и raw19/34 сохранены.

Ограничение: Dmax/rates/demand/detection/rounding/camera windows здесь **supplied**.
Граница задержки для реальных RELEASE ещё не калибрована; unbounded/unknown
delay этим доказательством не покрыт. Vehicle-to-event shift не является
задержкой от GREEN. Полнота исходного index — допущение, не проверенный факт.
Safe temporal domain не доказывает vehicle demand, наблюдаемость сигнала или
лампы. Не заявляем готовность к произвольному реальному JSON.

Дополнительно выполнен заранее зафиксированный scaling subset:
[exact DP для строго cell-local kernels](LOCAL_FACTOR_DP_20261016.md),12 tests
с oracle equivalence. Технический64с/no-demand пример обработан без enumeration;
это не hold recovery. Широкий kernel получает явный unavailable. Следующий
bounded шаг — expanded-state inference с ограниченной шириной factor history,
затем real calibration/validation. Обычный scalar HSMM для general joint log-sum
без factorization не подходит. Enumeration остаётся oracle малых задач. Новый
большой synthetic search и real replay не запускались.
