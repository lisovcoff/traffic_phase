# Единый выход ядра и состояние готовности продукта

Base: `e6bf625023b05e20dd8357b513d599b72e8db8f5`.
Ветка: `feature/product-result-contract-20261016`.

## Готовность

Проект не завершён. Для прозрачного учёта выделены восемь инженерных контрольных
пунктов с одинаковым весом. Два приняты в указанном ограниченном объёме:
**2/8 = 25% закрытых пунктов**. Это не процент написанного кода, трудозатрат,
реальной точности или прогноз оставшегося времени. Частично работающий компонент
не считается принятым только из-за наличия кода. Финальная независимая приёмка
продукта ещё не проводилась; проценты по этому checklist её не заменяют.

| Контрольный пункт | Состояние | Что требуется до завершения |
|---|---|---|
| JSON/ZIP, ограничения ресурсов и покрытие входа | Частично | Приёмка единого публичного пути на реальных сеансах и ошибочных входах |
| Движения, подходы 3/4 и состав фаз | Частично | Независимая проверка геометрии/mapping, shared movements и неполного спроса |
| Ограниченный прозрачный поиск K | Принят как 2C | Инженерный поиск принят; это не гарантия правильного K каждого входа |
| Локальная история hold/shortening | FAIL, 2D.1 | Восстановление с проверенной observation model и отдельная validation |
| Типы светофоров и дополнительные секции | Не принят | Проверка hardware semantics; сохранение альтернатив/UNKNOWN при неидентифицируемости |
| Защитный общий state/query contract | Принят, 2B.2 | Продолжать использовать его во всех consumers |
| Согласованный сквозной HTML/API | Частично | Подключение существующего интерфейса к единому результату и проверка без ложных цветов |
| Независимая итоговая validation | Не проведена | Отдельные calibration/validation sessions, frozen protocol и результаты |

Приоритет остаётся прежним: JSON/ZIP → движения → K/состав → локальная история
→ возможные секции → HTML. Calibration не заменяет продукт обязательной ручной
разметкой каждого входа. Внешние материалы нужны для проверки точности;
инженерная интеграция может продолжаться параллельно без новых decoder experiments.

## Реализованный шаг

`app/core/product_result.py::build_product_result` создаёт detached product view
**существующего prediction**, без fitting/discovery и без изменения production
default. Это подготовленный выход для будущих HTML/API consumers, пока не новая
точка приёма сырых JSON/ZIP и не законченный пользовательский интерфейс.

- K, period, schedule, phase selection, period inference и anchors сохраняются
  точно в `invariant_payload`, с отдельным hash. Исторические predictions не правятся.
- Движения группируются по исходным zone labels, включая произвольные имена и
  3/4 источника. Это не подтверждённая полная topology; отсутствие движения
  не исключает подход. Непарсимые labels сохраняются в `unassigned_movements`.
- Все activity scores по фазам сохраняются без новых thresholds/argmax, включая
  shared signatures. Они не превращаются в разрешённое движение или вероятность лампы.
  Legacy physical plan сохранён только внутри явно помеченной непроверенной гипотезы.
- Аппаратный тип/число допсекций остаются UNKNOWN/null, а не выводятся из поворота.
  Physical state создаётся общим `physical_estimate`, без второго набора правил.
- Логические запросы используют один `prepare_logical_query`: полуоткрытые
  интервалы, invalid history fail-closed, gaps/out-of-range UNKNOWN. Accepted
  history — default export; experimental выбирается явно и не имеет fallback.
- Model-history coverage считается отдельно; camera/local-observation coverage
  UNKNOWN. Полная временная история не означает наблюдаемость сигнала.

Пример (секунды **от schedule anchor**, не от начала MP4):

```powershell
C:\Python314\python.exe scripts/export_product_result.py `
  benchmarks/stage2c_20261014/predictions/6_2025_2_14_20_v9.json `
  product.json --time-s 21 --time-s 3657
```

Export ограничен 32MiB prediction, 256 movements, 2048 запросами и 100000
сегментами каждого legacy history. Никаких архивов/траекторий/видео этот CLI
не открывает; исходный prediction запрещено использовать как output.

## Проверка

42 tests: новый product view/CLI/artifacts и существующие state/V9 renderer
регрессии. Контрпримеры: 3/4 origins, K4 без нового cap, переименование movements,
shared activity, нулевой спрос, неизвестный label, malformed overlap, gaps,
полуоткрытые границы, explicit unavailable experimental history, turn/arrow
proposal без физического доказательства, отсутствие мутации и resource limits.

Повторяемая проверка экспорта: `python scripts/check_product_exports.py`.
Только три сохранённых stage2C predictions, не новый benchmark/replay. На всех
трёх schedule/selection/period точно сохранены; queries в конце history UNKNOWN.
Исходные и выходные hashes: `evidence/product_result_20261016/invariants.json`.
CLI-команды и логи: `exports.log`, тесты: `tests.log` в той же папке.

| Запись | K до/после | Period до/после, с |
|---|---|---|
| 17 | 3 / 3 | 99.84281321021679 |
| 19 | 2 / 2 | 120.02849954941996 |
| 6 | 3 / 3 | 99.99524773335186 |

Runtime в manifest относится только к subprocess export, не к алгоритму.
Новых метрик accuracy нет: raw19/34 и K3/2/3 против truth3/2/2 остаются прежними.
2D.1 FAIL/opt-in, main, extraction, priors, mapping objective и evaluator сохранены.

Следующий доступный инженерный шаг — использовать этот result contract в
существующей offline точке входа и HTML consumer с ограниченным сквозным smoke
check, без нового decoder/подгонки. Независимый calibration/validation-пилот
остаётся отдельным обязательным условием приёмки точности; его входы перечислены
в `REAL_PILOT_READINESS_20261016.md`.
