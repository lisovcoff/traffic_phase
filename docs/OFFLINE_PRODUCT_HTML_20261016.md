# Offline-вход и HTML используют общий контракт

Base: `fd2cb6f35a689b4673d1d091ee5370eeaf8d8b68`.
Ветка: `fix/offline-product-contract-20261016`.

Подтверждён дефект: JavaScript прежнего `scripts/v9_offline_visualizer.py`
игнорировал исправленный Python-renderer. Он независимо сравнивал activity с
threshold, рисовал GREEN/RED и фиксированные переходы, а при отсутствии подходящего
сегмента возвращал последний. Поэтому UNKNOWN мог исчезать именно в HTML.

Теперь existing offline CLI передаёт результат в `build_product_result` и общий
`prepare_logical_query`. Python один раз валидирует историю и подготавливает
полуоткрытые интервалы/логические оценки, включая explicit abstention reasons.
JavaScript лишь находит подготовленный интервал; никакого отдельного discovery,
периодического fallback, activity→lamp threshold или искусственных переходов нет.
Prepared snapshots описывают интервал; время ползунка показано отдельно относительно
schedule anchor, не времени MP4. Model-history coverage отделено от UNKNOWN
camera/local-observation coverage. Hardware type/count и лампы UNKNOWN.

HTML показывает K/period, наблюдаемые source zones, движения, текущие activity
scores, временную шкалу, причину UNKNOWN, управление временем/проигрыванием.
Legacy physical plan/colors и сырые event arrays в HTML не передаются.
Это reconstructed report, не configured/simulated signal viewer. Полная геометрия,
видео/автомобили и hardware reconstruction этим шагом не реализованы.

## Запуск

Сохранённый prediction, **без fitting**:

```powershell
C:\Python314\python.exe -m scripts.v9_offline_visualizer `
  benchmarks/stage2c_20261014/predictions/6_2025_2_14_20_v9.json `
  --prediction --output report.html
```

Исходный JSON/ZIP/directory по-прежнему поступает в существующий `discover_path`:

```powershell
C:\Python314\python.exe -m scripts.v9_offline_visualizer input.zip --output report.html
```

Вторую команду на реальных данных в этом задании **не запускали**. Маршрут JSON/ZIP
проверен с подменённым discovery, а не объявлен новой end-to-end проверкой fitting.
`--history experimental` явно выбирает experimental history без fallback.
Старые `--yellow`, `--red-yellow`, `--activity-threshold` сохранены как compatibility
arguments: reconstructed HTML не использует их для назначения ламп. Algorithms,
event selection, thresholds и production inference default не изменены.
Сохранённый prediction ограничен32MiB, embedded payload8MiB; output не может
совпасть с input. Labels экранированы при embedding JSON, DOM заполняется textContent.

## Проверки и артефакты

52 tests прошли: новый HTML/payload/CLI/JS, existing offline test, product result,
state contract и V9 renderer. JavaScript выполнен локально в Node с минимальным
DOM для проверки seek/slider и совпадения state/reason с Python на границах,
в пробелах и вне истории. Это не browser rendering/screenshot QA.

Браузерное подключение и попытка прочитать troubleshooting завершились ошибкой
`failed to write kernel assets ... os error 3` до исполнения кода. Визуальная
браузерная приёмка **не выполнена**; интерфейс не объявлен окончательно принятым.

Изменение прежнего теста цветов обосновано конкретным контрпримером: fixture
содержит только baseline_segments и scores. Это не reconstructed history;
score .90 не доказывает GREEN, .01 не доказывает RED. Новый результат UNKNOWN,
без fabricated YELLOW/RED_YELLOW. Отдельно проверены overlap, explicit experimental
gap, отсутствие вызова discovery при `--prediction`, immutable input и script injection.

Проверена существующая ветка `origin/fix/respect-explicit-physical-plan-20261012`,
commit `cb104669384fc67af05723854568fe5206d4380c`. Исправление касается другого
renderer; его physical-plan логику здесь не дублируем и не меняем.

Три готовых HTML, manifest исходных/выходных hashes и commands.log:
`evidence/offline_product_html_20261016/`. Predictions сохранены точно;
invariant hashes совпали с предыдущим product export. K остаётся3/2/3,
period99.84281321021679/120.02849954941996/99.99524773335186с.
Реальные raw19/34, неверный K3 записи6 и 2D.1 FAIL сохранены. Нового benchmark,
real replay, новых calibration labels или tuning не было. Main не менялся.

Следующая приёмка: проверить вид страницы в доступном браузере, затем независимая
calibration/validation реальных сигналов по существующему протоколу. Интеграция
не является доказательством точности, а восемь инженерных критериев по-прежнему
имеют2 принятых пункта; UI остаётся частичным до сквозной приёмки.
