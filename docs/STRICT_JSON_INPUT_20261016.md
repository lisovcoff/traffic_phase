# Надёжное чтение JSON/ZIP: исправление рамки массива и закрытия ZIP

Base: `1a4e0c656baf004f09a6632abf91922772e6b2b4`.
Ветка: `fix/strict-v9-json-input-20261016`.
Пункт9 ROADMAP: корректность входа и отказов. Независимая clock calibration
ожидает внешний producer input; повторного исследования тех же vehicle timings нет.

## Подтверждённые дефекты

В `app/core/v9/events.py::_iter_json_records` и существующем
`app/core/preprocessing.py::iter_trajectory_payload_stream` одинаково нарушена
ветка закрытия массива, когда parser ожидает значение:

| Вход | Раньше | Теперь |
|---|---|---|
|`[]` и `[]` с whitespace|Ошибка «unterminated»|Корректный пустой массив|
|`[{},]]`|Принимался один record|Отказ: trailing comma|
|`[],{}]`|Принимался record за пределами массива|Отказ: unexpected data|
|`[{},]`|Ошибка «unterminated»|Отказ: trailing comma|
|Корректный массив объектов|Records выдавались|Те же records|

Причина: первая `]` потреблялась без завершения документа; следующая `]`
могла завершить неправильный документ. Теперь empty array разрешён только до
первого значения, закрытие проверяет весь хвост вплоть до EOF. Пробелы хвоста
сбрасываются после каждого chunk, а не копятся в памяти. Кавычки/escaped brackets
и split UTF-8 не трактуются как структурные delimiters вручную: используется
прежний JSONDecoder.

Подтверждён также обход существующего `max_object_chars`, если oversized object
целиком декодировался в очередном chunk. Размер проверяется и после успешного
decode. Default16Mi chars и chunk64KiB не менялись. Это не новый общий budget
ZIP/uncompressed bytes/upload size и не приёмка многогигабайтных архивов.

Первичная HTTP-проверка обнаружила отдельный Windows failure: ошибка parser
внутри ZIP оставляла suspended source generator/ZipFile открытым. При выходе
из TemporaryDirectory возникал WinError32, подменявший исходный JSON error.
В canonical `load_event_streams` file-source iterator теперь обёрнут `closing`;
in-memory records используют `nullcontext`. Event loop, selection и параметры
extractor не менялись. Отдельный тест проверяет закрытие и при ошибке extractor.
Это гарантия canonical default ingestion, не заявление о полном аудите lifetime
каждого исторического caller частного `_iter_source_records`.

## Проверки

172 targeted/regression tests PASS за3.42с. Проверены оба readers, chunk1/2/7/
65536, пустой массив, trailing comma/лишние скобки/данные после массива, длинный
whitespace tail и поздний garbage, UTF-8/escaped quotes, object limits, JSON/ZIP
source, архивные streaming/evidence regressions и существующий web contract.

Четыре настоящих multipart HTTP requests через ASGI TestClient проверили
`/api/v1/v9/analyze` и `/visualization/analyze`, каждый с JSON и ZIP. Неправильный
документ получает422 с исходной причиной; sentinel подтверждает, что построение
V9 модели не началось. Для пустого JSON ещё2 requests дают422 с evidence UNKNOWN,
без fabricated phase_count и без ложной ошибки синтаксиса. Пустой массив не
означает наличие наблюдений или камеры с подтверждённым покрытием.

Это HTTP/core verification; нового браузерного screenshot review не было и
изменений HTML/JS/API endpoint code нет. Один установленный Starlette/httpx
deprecation warning сохранён; зависимости ради него не устанавливались.

До исправления записаны `before.json` и красный regression log. В ходе проверки
исправлены две ошибки новых test assertions: `{}` — валидный JSON с недопустимым
root type для этого контракта; `[{},]]` может быть отвергнут раньше, как trailing
comma. Эти исправления ожиданий не меняли требования отказа. Сбой WinError32
сохранён отдельно и устранён в коде, не ослаблением HTTP assertion.

## Неизменность корректных данных и моделей

Без нового extraction проверен небольшой1.32MB source:7 целых tracks,
3851 detections. Структуры нового V9 reader для JSON и ZIP точно равны
`json.loads` того же источника, со всеми полями/порядком/timestamps.
Это проверка reader, не повторный vehicle onset/clock calibration.

Три saved2C predictions неизменны относительно полного base через Git. Их
K3/2/3, periods99.842813/120.028500/99.995248с и прежние invariant SHA взяты из
неизменённого historical manifest. Новые большие prediction JSON не разбирались:
первоначальный verification guard4MiB остановил такое чтение, затем checker
переведён на маленький прежний manifest и Git content comparison. Бюджет не
увеличивался. Это не новый fitting/benchmark или пересчёт accuracy.

Новых изменений K solver/HSMM/period inference/mapping/offset/thresholds нет.
State/query UNKNOWN semantics и experimental default-off сохранены. Исторические
K3/2/3 vs truth3/2/2, raw19/34 остаются;2D.1 FAIL не принят. Main неизменён.

## Артефакты и границы следующей работы

`evidence/strict_json_input_20261016/` содержит before/after, тестовые логи,
`input_invariants.json`, воспроизводимый `verify_inputs.py`, commands/hashes/diff
и компактный ZIP. Реальные raw tracks/predictions повторно не пакуются.
Iterator гарантирует валидность всего документа после полного исчерпания;
частично прочитанный префикс не является сертификатом корректности всего JSON.

Этот шаг закрывает конкретный input defect. Шаг9 целиком не принят: остаются
общие archive/upload budgets, изоляция разных sessions/intersections, нагрузка
и независимая сквозная приёмка. Следующий независимый от camera log приоритет —
проверить, как canonical archive route сохраняет границы сеансов и происхождение
входов, чтобы разные дни/режимы не стали одним циклом. Новый phase experiment
не запускать под видом такого input check. Clock-пилот по-прежнему требует
соответствия exposure/PTS/millis от producer или документированного механизма.
