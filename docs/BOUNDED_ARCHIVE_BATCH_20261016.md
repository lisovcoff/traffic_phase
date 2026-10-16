# Пакетная обработка архива и проверка результата

Base: `519e6ea94610d12f5c814721d993ca02f2015b29`.
Ветка: `feat/bounded-archive-batch-20261016`. Main сохранён:
`a005a2521f62ce3b2c9f9d52f9f0d73913754e01`.

Запуск: `START_WEB.cmd` → `http://127.0.0.1:8017/visualization/batch`.
Для одного сеанса с движущимися машинами остаётся `/visualization`.
Пакетный интерфейс показывает отдельные логические отчёты; пространственный
viewer не переписан и автоматически в каждый пакетный отчёт не встраивается.

CLI из корня репозитория:

```powershell
python -m scripts.archive_batch run input.zip --out batch_output --max-jobs 4 --total-seconds 180 --source-seconds 90
```

Каталог результата должен быть новым. На машине с заполненным системным диском
TEMP/TMP задать локально на свободном диске; `START_WEB.cmd` уже делает это.
Новые зависимости не установлены; `START_WEB.cmd --check` проходит.

## Что реализовано

ZIP directory inventory не распаковывает тела. Каждый JSON — отдельный source,
подтверждённая идентичность перекрёстка не выдумывается. Worker один раз извлекает
существующий temporal evidence, выделяет сеансы существующим правилом1800с и
передаёт **те же** scoped bundles в `_discover_bundle` с marks=None, dt=1,
permission_per_stream, experimental_local_history=False. HSMM/K/период/selector/
mapping/thresholds не изменены. Независимое окно сеанса не становится новым
сигнальным режимом. Длинный сеанс сохраняет старую representative-window логику,
явно помеченную `REPRESENTATIVE_WINDOW_ONLY`, а не полную локальную историю.

Каждый source выполняется последовательно в subprocess. Hard timeout убивает
и дожидается worker; завершённые checkpoint jobs сохраняются. Running/planned
при прерывании получают UNKNOWN с причиной; до окончания inventory число
сеансов неизвестно. Нет общего K архива и скрытой подстановки другого сеанса.
Один сеанс не используется для заполнения временных пробелов другого.

По умолчанию:4 попытки сеансов,180с на пакет вычислений,90с на source включая
import/extraction/все его сеансы; source не получает90с заново на каждый сеанс.
Кооперативный60с K-search сохранён, hard timeout — отдельная внешняя граница.
Загрузка до512МиБ, один распакованный JSON до512МиБ, сумма admitted JSON до1ГиБ.
Артефакты до64МиБ с резервом на HTML/manifest, prediction до16МиБ, HTML payload
до8МиБ. ZIP скачивания — дополнительная сжатая копия. Input metadata/git sealing,
загрузка/HTML/упаковка и ожидание планировщика не обещаются уложиться в180с.
**Hard RAM limit отсутствует.** Допуск размеров не является нагрузочным
сертификатом для любых файлов такого размера. Исторические logs не удаляются;
долговременное хранение/квоты и полноценная эксплуатационная приёмка открыты.

HTTP body ограничен **до multipart parser/spooling**, с учётом реальных байтов
при chunked/ложном Content-Length. Затем ограничен и файл при копировании.
Переполнение413, нехватка диска507; multipart временные файлы закрываются при
ошибке. Один активный batch на процесс приложения, конкурирующий запрос429;
это локальный сервис, не распределённая очередь/глобальный admission controller.
Синхронные single-session endpoints не превращены в новый job service.

HTML использует общий product/query contract. Физические лампы/секции UNKNOWN,
вероятность лампы отсутствует. Невыполненная задача не означает отсутствие фаз.
Все predictions и hashes доступны в скачиваемом ZIP; исходное медиа не включается.
Будущие manifests фиксируют commit, dirty flag и LF hashes исходников. Технический
smoke был до commit: его точный base и code hashes — в pre-run freeze/sidecar;
это не заявление, что родительский SHA уже содержал новый batch-код.

## Проверки и самопроверка

249 tests: archive/source scope/input/parser/events/API/export. Ещё68 tests:
logical/physical contract, реальные V9 renderer queries, configured transitions,
явный K config. Всего317, единственное предупреждение — существующая
Starlette/httpx deprecation, зависимости ради него не заменялись.
Полные команды: [commands.md](../evidence/bounded_archive_batch_20261016/commands.md),
логи лежат рядом. Старый K-config stub возвращал tuple(), а не event bundle;
заменён настоящим lossless fixture, mock оставлен только у fitting. Прокидывание
самого PhaseSearchConfig проверяется по identity, K5–8 не фитились.

Ровно один frozen technical browser batch на прежнем маленьком synthetic ZIP:
2 JSON,3 сеанса,40 tracks/events каждый;3 вызова неизменного discovery.
Все K2,period120.00208155391648с. Package wall16.7826с, HTTP ready16.996с;
это elapsed time, не CPU profile и не измерение реальной точности.

Найдены и исправлены:

- На mobile фиксированная высота вложенного отчёта обрезала содержимое.
  Высота теперь следует естественному body size; финальные390/348/306px
  уровни iframe не имеют горизонтального переполнения. Screenshots просмотрены.
- Browser `stateAt(10)` возвращал state с `timestamp_s` от начала сегмента.
  Состояние/границы были верны, provenance запроса неверен; теперь копируется
  prepared state и обновляются только timestamp/query_position. Усилен старый
  тест с двух полей до полного JSON-normalized contract. Initial15 metadata
  mismatches сохранены; final15 full states exact Python. JSON tuple/list
  нормализуются только в сравнении, правила UNKNOWN/сегменты не меняются.
- Plain ValueError из body guard FastAPI превращал в generic400. Новый actual
  chunked multipart counterexample потребовал HTTPException413; проверено
  закрытие spooled file до входа в handler. Большой файл не загружался.

После единственного batch были **два UI-only replay** сохранённых predictions,
без extraction/fitting. `download.zip` — исходный technical run;
`layout_download.zip` — тот же набор prediction bytes с исправленными reports.
Saved replay server — отдельный QA process, production не патчится.
`verify_results.py` проверяет ZIP CRC, artifact hashes,15+15 browser queries,
точное сохранение всех schedule/period и selected event extraction против
предыдущего результата. Все selection diagnostics совпадают, кроме12 runtime
полей. Исходные benchmark/config/core V9/uncertainty/mapping/evaluator Git-неизменны.
Фазовые метки/большие JSON/архивы/real replay не использовались.

## Готовность к цели

Вход→несмешанные сеансы→существующая оценка→HTML/скачивание работает и проверен.
Это продвижение шагов8/9 ROADMAP, не завершение проекта и не приёмка всех режимов РФ.
2C и защитный контракт приняты. 2D.1 остаётся FAIL/default-off. Реальные прежние
показатели K3/2/3 против truth3/2/2,raw19/34±2с не пересчитаны и не улучшены этим UI.
Физическая конфигурация, точная локальная история и независимая validation открыты.

Критический следующий вход уже определён, повторная разметка тех же траекторий
его не заменяет: supplier camera-frame/PTS↔detections.millis связь с uncertainty
([точный request](../evidence/frame_clock_intake_20261016/SUPPLIER_REQUEST.md)),
затем отдельный сеанс JSON+независимые состояния сигналов того же перекрёстка,
без overlap с известным development. Использовать существующий independent-review
template, подтвердить mapping/геометрию там, где они нужны, источник prior/delay.
До этого нельзя обоснованно принять точность локальной истории или секций.
Дальше — заранее зафиксированный calibration experiment и frozen validation,
без переноса exclusive synthetic assumptions или выбора Nominal10 по известным данным.
