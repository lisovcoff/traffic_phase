# Car registration: кандидат отвергнут, ложная экстраполяция блокируется кодом

Base `b9233dc`, ветка `calibration/enthusiasts-car-registration-20261018`.
Пользователь попросил ускорить продолжение. Сделан ограниченный empirical
car-registration шаг, затем устранён обнаруженный пробел в допуске геометрии.
Это не улучшение фазовой точности и не завершение синхронизации.

## Результат реальной проверки

Переиспользован сохранённый13.5MB entry:245tracks/39215detections; новый архив
не сканировался. Добавлены18 native contexts, реальные PTS и hashes сохранены.
Сигналы/phase predictions в расчёты не передавались, H1 transform не переносился.

Принятые до запуска gates: train30px, distinct-vehicle control50px. Обучение
по6 точкам двух кандидатных W→E машин дало малую ошибку, но не обоснованную
привязку всей сцены. Первая ручная ассоциацияID6 с белым SUV была ошибочной:
source lane ordering указывает на следующий синий седан в полосеID2.
До annotation/scoring контрольных машин сделан один документированный repeat
с исправлением bbox. Исходные code/points/model/seal сохранены.

| Проверка исправленного кандидата | Результат |
|---|---:|
| Train max,6 points IDs2/6 |3.595px|
| Train RMSE |2.049px|
| Jacobian rank |9/9|
| Control ID7,5 points, max |13 048px — FAIL|
| Control ID19,5 points, max |18 339px — FAIL|

Прямые наблюдения других машин размечены после seal исправленной модели.
Identity остаётся candidate, а не producer-certified; поэтому ошибки выше —
**проверка гипотезы регистрации**, не измерение ошибки трекинга/часов/ламп.
Наблюдались ранее просмотренные development scenes, это не untouched session.
По control labels повторной подгонки этого кандидата нет. Кандидат отвергнут.

Причина ложной уверенности воспроизведена численно: знаменатель homography
меняет знак на реально наблюдаемой road support. Между подходами есть линия,
на которой projection undefined. Даже конечные projections отдельных точек,
малые train residuals и полный Jacobian rank не исключают это нарушение.
Два почти однонаправленных трека недостаточны для допуска всей сцены.

Отдельно проверена альтернативная static geometry по четырём стоящим кандидатам
IDs7/12/14/19. Эти ранее контрольные машины **явно переведены в development
calibration**, не объявлены новой validation. Один линейный H также пересёк
road horizon. Две exploratory альтернативы (перестановка12/14 и affine LS)
сохранены: первая имеет тот же дефект, вторая нарушает30px train gate.
После этого новые controls36/116 не размечались и clock estimation не запускалась.
Это не доказательство, что исходное видео и JSON не соответствуют друг другу.

Budget deviations указаны явно:2 joint clock optimizer calls вместо исходного1
(один annotation correction до control scoring);3 static linear solutions вместо1.
Новых clock fits после контрольного FAIL нет. Gates не ослаблялись. Все
отрицательные результаты сохранены; phase fitting/replay/decoder calls —0.

## Исправление инструмента

В `app/experimental/vehicle_clock_alignment.py` добавлен
`inspect_registration_support(model, records)`. Он проверяет **весь переданный
scope наблюдаемых координат**, нормирует projective gauge и ищет пересечение
знаменателем нуля внутри convex hull. Пустой scope остаётся unavailable.
Результат не подтверждает identity, coplanarity или clock accuracy и не выдаёт
production permission даже при конечной геометрии.

`scripts.vehicle_clock_calibration` теперь проверяет все tracks supplied sample,
а не только train IDs. При score плохая геометрия даёт
`REJECTED_ROAD_HORIZON_CROSSING` **до** pixel scoring/conditional clock-set;
никакого accepted clock transform или fallback. При fit результат и причина
отказа сохраняются. Алгоритм phase discovery и inference defaults не менялись.

Реальный CLI smoke на frozen corrected model и всех39215 source points подтвердил
отказ без scoring и без нового fitting.17 новых независимых tests включают
конечные projections по обе стороны от скрытого horizon, perfect local fit,
смену знака/масштаба H, пустые/невалидные данные и CLI fail-closed путь.
**53 tests PASS** вместе с существующими clock/local registration checks.

Следующий admission требует пространственно разнесённых однозначных source/image
соответствий и проверки coordinate/preprocessing semantics. Установленная в
предыдущем шаге supplier/video SHA identity остаётся действительной. По этой
проверке нельзя назначить offset, drift, event delay или lamp error: принятых
clock transforms0,2D.1 FAIL/default-off и physical UNKNOWN сохраняются.

## Воспроизведение

`evidence/enthusiasts_car_registration_20261018/` содержит планы, native PTS/logs,
ручные bbox/proof crops, оба joint fits с seals, independent results, rejected
static alternatives, CLI result и tests. Полные native frames task-local в
`.web_runtime/enthusiasts_car_registration_20261018`; прежние inputs/evidence
не редактировались и не удалялись.

```
py -3 -m pytest tests/test_registration_support.py tests/test_vehicle_clock_alignment.py tests/test_local_registration_validation.py tests/test_frame_clock_links.py -q -p no:cacheprovider
py -3 evidence/enthusiasts_car_registration_20261018/verify.py
```

Verifier не повторяет model fitting/decoding. `fit_candidate.py` и
`refit_corrected_annotation.py` запускаются только с fresh outputs; повторять
их поверх сохранённых результатов нельзя. Main/core/config/benchmarks и прежние
artifacts сохранены; историческиеK3/2/3,raw19/34 не переоценивались.
