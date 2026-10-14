# Аудит готовности к конечному продукту, 2026-10-15

Base `fc3f5f51c8c9d4c0aa7f83d5b7d67d17df290190` (checkpoint после
`c99268b700b2b46bc0202a2a37f635e3af93f70d`). Цель: PRODUCT_GOAL.md.
Проверены текущие V9/V10, event ingestion, spatial/HTML путь, API, CI,
сохранённые результаты и компактные контрактные тесты. Без decoding, fitting,
replay, больших архивов и новых prior/likelihood experiments. UI не менялся.

## Насколько близко завершение

Есть работающий исследовательский pipeline и существенная инженерная основа.
До промышленного продукта остаются незакрытые основные функции, а не только
интерфейс. Процент готовности и срок по числу файлов/тестов необоснованны:
независимая реальная приёмка ключевых результатов ещё не пройдена.

| Требование | Что есть | Что не доказано / не закончено |
|---|---|---|
| JSON/ZIP одного перекрёстка | CLI/API, streaming JSON extraction, provenance | Сквозной ресурсный контракт архива/веб-запроса; потоки и fingerprints всё ещё накапливаются в памяти |
| Подходы и направления | Streams из zone_in/out; spatial anchors; отдельный T-intersection test | Произвольная геометрия и неверные/неполные зоны; automatic physical ориентирован на N/S/E/W |
| Число и состав фаз | Bounded K search, альтернативы, event support, phase activity | На development K3/2/3 вместо truth3/2/2; composition не проверена независимой hardware truth |
| Тип светофора/допсекции | Automatic physical hypothesis builder и ручной plan | Heuristic turn selectivity не доказывает аппаратную стрелку; shared turns ограничиваются |
| Локальная история/продления | Принятый raw/reference; отдельные experimental пути | 2D.1 FAIL; finite synthetic feasible prototype не подтверждает реальные продления |
| Безопасная семантика | Принятые activity/logical/physical и UNKNOWN core contracts | HTML содержит собственный несовместимый цветовой путь |
| HTML/FastAPI | Уже реализованы upload/analyze/render и логи | Семантическая согласованность, эксплуатационные лимиты и итоговая приёмка |

2C принят как исправление допуска кандидатов и прозрачности поиска, а не как
доказательство правильного K на любом перекрёстке. 2B.2 принят как защитный
контракт, а не как доказательство физических ламп.

## Проверяемые препятствия

1. **Смысл evidence и точность времени.** Принятый event contract сохраняет
   происхождение, но RELEASE/геометрия/units и signal-to-event delay независимо
   не откалиброваны. Реальные raw границы: 19/34 в +/-2с (55.9% recall), по
   записям 17/19/6 — 15/17, 1/8, 3/9. K ошибочен в записи 6. Это development,
   не untouched holdout и не lamp accuracy. Источник:
   docs/PHASE_SEARCH_2C_RESULTS.md, benchmarks/stage2c_20261014/.
   Следующий шаг: пилот calibration/validation, а не новые параметры по этим
   трём файлам. Согласованный synthetic event-time prototype сохраняет FAIL
   point-gate у обоих priors; Nominal10 не выбран.

2. **Аппаратные секции подменяются гипотезой из активности.**
   `app/core/v10/automatic_physical.py::infer_physical_signal_plan` принимает
   только канонические N/S/E/W, отождествляет straight с main, turns с
   дополнительными секциями и назначает поворот максимум одной доминирующей
   фазе. `_head_states` конструирует GREEN/RED всех четырёх подходов.
   `app/core/v9/model.py` добавляет этот plan в результат. Отдельный
   `v10/semantic_mapping.py::signal_state_at` уже корректно abstains по умолчанию,
   но сам plan остаётся heuristic. Нужны независимая topology/section validation,
   hypothesis provenance и сохранение shared/permissive alternatives.

3. **HTML обходит принятый UNKNOWN contract.** В
   `scripts/v9_spatial_visualizer.py::movementState` activity threshold/ratio
   задают GREEN/RED и фиксированные YELLOW/RED_YELLOW; `physicalSectionState`
   преобразует UNKNOWN в RED. `_physical_visual_model` использует головы plan
   напрямую. JS `ACTIVE_APPROACHES` при enabled physical plan берёт все четыре
   подхода, даже если projection имеет три. Микропроверка существующих JS
   функций: на одном и том же metadata case core выдаёт UNKNOWN, JS — GREEN
   в t=10 и YELLOW в t=29; UNKNOWN section становится RED. Это контрпример
   согласованности, без нового model inference. Исправление нужно отдельным
   заданием, сохраняя configured/simulated режим и общий контракт.

4. **Исправление explicit physical plan не интегрировано.**
   В текущем `build_spatial_visualization` прочитанный `physical_plan_path`
   перезаписывается `result.get("physical_signal_plan")` (строка около 1140).
   Проверена существующая remote-tracking ветка
   `origin/fix/respect-explicit-physical-plan-20261012`, SHA
   `cb104669384fc67af05723854568fe5206d4380c`: она уже сохраняет explicit plan,
   включая disabled. Diff показывает отсутствие этого исправления в текущей
   линии. Повторная независимая реализация не нужна; потребуется осознанная
   интеграция существующей правки с тестами. Main/UI в аудите не изменены.

5. **Нет проверенной общей модели режимов и нестандартных перекрёстков.**
   T-проекция уже протестирована; говорить, что 3 подхода вовсе не поддержаны,
   неверно. Но `v9/spatial.py` нормализует только N/S/E/W, physical builder и
   HTML предполагают cardinal topology, а основной SignalState enum содержит
   GREEN/YELLOW/RED/RED_YELLOW/UNKNOWN. Это не каталог всех специальных режимов.
   Большой архив выбирает recurring regime/window; это не доказательство
   локальной истории всех смен режима. Требуются явная topology, независимые
   группировки/полосы и сценарная матрица с причинами UNKNOWN/unsupported.

Дополнительно: `app/api/visualization.py::visualization_analyze` выполняет
синхронный анализ внутри async handler; streaming входа не ограничивает весь
CPU/RAM/время запроса. K-search budget не равен бюджету архива. Это статическая
находка, нагрузочный тест не проводился. `.github/workflows/tests.yml` запускает
push CI только для main/v9-integration, также PR/merge_group; сам push текущей
experimental ветки не доказывает зелёный CI. Полный CI в аудите не запускался.

## РФ: что означает «все нюансы»

Сверен текст раздела 6 ПДД: мигающие сигналы, дополнительные/направленные
секции, специальные сигналы и регулировщик требуют отдельной семантики.
Это шире текущего набора цветов. Источник:
https://www.consultant.ru/document/cons_doc_LAW_2709/4b7a10a56ed37080fc96999db5f3db6f3aa58cc6/
Это ограниченная сверка перечня, не исчерпывающий нормативный/ГОСТ-аудит.
Адаптация длительности, приоритет, вызов, смена плана, no-demand и блокировка
должны стать измеримыми сценариями. Движение спецтранспорта само по себе не
устанавливает действие контроллера или причину временного изменения.

## Путь к завершению

1. Независимый calibration-пилот + отдельный validation session: закрыть
   event/signal timing, mapping, геометрию и необходимые определения supplier.
   Это материалы разработки, не обязательная ручная разметка каждого будущего
   пользовательского входа. Перечень уже задан VALIDATION_PROTOCOL.md §8.
2. После фиксации допущений — ограниченная проверка реальной локальной истории,
   K/composition и hardware hypotheses. Успех должен измеряться на независимых
   сеансах, с отдельными coverage, UNKNOWN и ошибками по типам сигналов.
3. Отдельно закрыть уже подтверждённые интеграционные дефекты UI/explicit plan;
   для этого не требуется изобретать новый decoder. Тот же контракт применяется
   от core до HTML, ложная определённость недопустима.
4. Приёмочная матрица трёх-/четырёхподходных перекрёстков и режимов РФ,
   затем end-to-end resource/error checks. Интерфейс переиспользовать, не писать
   FastAPI заново. Экспериментальные задачи принимаются только если закрывают
   конкретный пробел этой продуктовой цепочки.

69 целевых тестов прошли, 2 discovery-call-site теста сознательно deselected
(не запускать model paths). Изменений алгоритма нет. Логи и микропроверка:
evidence/product_audit_20261015/. Это не новый benchmark/evidence pack.
