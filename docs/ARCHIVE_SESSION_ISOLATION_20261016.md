# JSON/ZIP: отдельные источники и сеансы до анализа

Base: `13bc172de40c8f531ce174637e9d66aeb574aa18`.
Ветка: `fix/archive-session-isolation-20261016`.
Это продуктовая изоляция входов, не новый алгоритм фаз/локальной истории.

## Исправленный механизм

Раньше `discover_path` передавал все JSON одного ZIP в общий event bundle,
deduplication/selection и period/K model. Равные названия зон/ID не удостоверяют
общий источник. Для длинного массива V9 мог выбрать один представительный час;
это не восстановление остальных дней, сеансов или изменений режима.

Теперь `source_scope.py` выполняет два отдельных шага:

1. **Источник.** ZIP central directory перечисляется без распаковки members.
   Несколько JSON требуют явного `source_member` до extraction/fitting.
   Каждый member — отдельный, пока не проверенный source namespace. Даже если
   несколько файлов фактически принадлежат одной камере, автоматического union
   нет без проверенного capture manifest. Совпадающие/коллидирующие имена,
   unsafe paths и encrypted JSON отвергаются. Одноисточниковый вход работает
   без дополнительного выбора.
2. **Сеанс.** После обычного extraction временная поддержка целых usable tracks
   разделяется по существующему `DEFAULT_SESSION_GAP_SECONDS=1800`: следующий
   track начинается более чем через этот gap после конца текущей группы.
   Значение не настраивалось по разметке. Ровно1800с не создают новый сеанс.
   Порядок records не влияет на группы. ID сеанса зависит от source namespace
   и набора track fingerprints, а не от phase truth/ошибок модели.

Разрыв наблюдений **не доказывает** отключение камеры, отсутствие спроса, RED
или смену signal plan. Если один track сам пересекает такой internal detection
gap, возвращается `AMBIGUOUS_TRACK_SESSION_GAP`, а не произвольное склеивание.
Одинаковые timestamps/ID в разных members не дают основание объединять их.
География/идентичность всего перекрёстка остаются UNKNOWN без отдельного источника.

Список сеансов основан на tracks с usable temporal evidence. Пустые/непригодные
source records не получают выдуманного распределения по сеансам. Для выбранной
подгруппы diagnostic counters оставляют source-global discarded-track counters
отдельно, с явной областью действия; они не становятся likelihood weights.

## Сохранение алгоритма и UNKNOWN

При одном сеансе возвращается исходный bundle, без повторного selection.
Для явно выбранного сеанса тот же `_pack_temporal_events` вызывает прежний
`select_permission_events` только на его событиях. Типы, timestamps, uncertainty,
provenance и правила selection сохранены. Scope меняется до period/K fitting.
Применено к path и in-memory `discover_records`, чтобы второй вход не обходил
защиту. `legacy_v9` остаётся явным unpartitioned comparison path; новые scope
arguments в нём не игнорируются, а отвергаются. Он не используется web default.

У результата есть `input_scope` с выбранным source/session, extent, количеством
доступных источников/сеансов и `other_*_analysed=false`. При старом выборе
представительного часа выводится `REPRESENTATIVE_WINDOW_ONLY`: остальная история
не заявляется восстановленной. Границы самих фаз, HSMM/K objective, period
inference, mapping, offsets и thresholds не изменены.2D.1 FAIL/default-off.

Общий product/offline/spatial query contract сохранён. Для другого сеанса/вне
истории результат UNKNOWN, без periodic fallback. Аппаратные лампы/секции
остаются UNKNOWN. `input_scope` доходит до JSON, offline HTML и spatial HTML.

## Как пользоваться

Запуск: canonical `START_WEB.cmd`, `http://127.0.0.1:8017/visualization`.
Загрузить JSON/ZIP. Если источников/сеансов несколько, выбрать их из списков
и нажать анализ. При смене выбора предыдущий результат скрывается. Это выбор
области анализа, не ручная phase calibration. В HTML подписан выбранный scope;
автоматическая пакетная обработка всех members этим шагом не реализована.

Оба API поддерживают multipart `source_member` и `session_id`. Без нужного
выбора возвращают409 с `detail.choice_kind`, `choices`, `reason_code`,
`state=UNKNOWN`, `phase_count=null`, `fitting_performed=false`. Недостаток evidence
возвращает422 со structured `EvidenceUnavailable.to_dict()`, не фиктивный K.
Повреждённый JSON остаётся422 с текстовым parser error. `/api/v1/v9/analyze`
больше не распаковывает весь ZIP перед выбором источника.

CLI `v9_phase_discovery.py`, `v9_spatial_visualizer.py`, `v9_offline_visualizer.py`
поддерживают `--source-member` и `--session-id`. Без необходимого выбора печатают
машиночитаемые choices и завершаются с code2. Выбор member использует точное имя
из списка, включая путь внутри ZIP. Saved-prediction offline режим не fitting.

Лимиты этого шага:512 JSON choices/сеансов,512MiB выбранного uncompressed JSON.
Другие members не декодируются. Это не строгий лимит всего upload/RAM/demuxer
I/O и не приёмка многогигабайтной batch-обработки. Oversized/ambiguous вход
отказывается явно. Обычный accepted K-search budget прежний.

## Фактические проверки

**219 tests PASS**: source/session guards, два API, выбор до fitting, одинаковые
ID/time в разных namespaces, exact gap, internal gap abstention, stale IDs,
перестановка input records, source budgets, безопасные ZIP paths, in-memory
bypass, scoped raw tracks, escaped source label, старые readers/evidence/
product/spatial/offline/registry regressions. Два старых ожидания уточнены:
empty evidence теперь structured UNKNOWN; mocked inference-result envelope
получает additive input_scope. Старые sidecar/selection assertions сохранены.

По Browser skill runtime сообщил `No browser is available`; troubleshooting и
список подтвердили отсутствие подключённых browsers. Использован isolated
headless Edge, отдельный профиль наD, без пользовательских сессий. Один ordinary
V9 synthetic discovery вызов на заранее sealed40-track fixture. Два источника,
у выбранного `b.json` два сеанса (второй — исходная fixture со сдвигом ровно сутки).
Никаких real replay/benchmark, labels, tuning или prior experiments.

| Проверка | Факт |
|---|---|
| HTTP без member / без session / окончательный анализ |409 /409 /200|
| Выбранный source/session |b.json,2/2|
| Trajectory/event count модели |40/40; остальные не попали в модель|
| K/period technical fixture |2 /120.00208155391648с|
| Upload→готовый результат выбранного scope |9.603с, не CPU profile|
| Browser/common Python queries |12 совпали:6 initial+6 saved replay|
| Другой сеанс / физические состояния |UNKNOWN /UNKNOWN|

Первый automated overflow predicate пропустил mobile defect: native select
расширял layout до465px при viewport390. Visual review это обнаружил; первый
автоматический PASS сам по себе не принят. После width constraints, переноса
provenance text и удаления абсолютного внутреннего log path проверка на
**сохранённом prediction** дала root/iframe без overflow, scroll/client390/390.
Desktop/mobile screenshots просмотрены. При смене сеанса iframe очищается.
Нового fitting для layout fix не было; saved replay0.631с. Первые screenshots
и visual finding сохранены. Browser JavaScript errors отсутствуют.

После smoke при review закрыт in-memory bypass тем же session helper; новый
targeted test гарантирует отказ до fit. Это изменение entry-point guard, а не
подбор алгоритма по synthetic result; fitting-функции остались AST-identical.

На небольшом прежнем односеансовом1.32MB input input-parity checker сравнил
events module из base с текущим: packed streams, temporal events, выбранные
indices, quality/methods и provenance **точно совпали**, SHA
`228684981be3d2b6add9f11eaa36fabe92019c4268c74e4562bee4991ebb7423`.
Это input regression, не повторная оценка смысла этих vehicle events.
Saved three-file predictions/benchmarks неизменны через Git. Старые реальные
K3/2/3 vs truth3/2/2, raw19/34 сохранены. Synthetic K2 не real/lamp accuracy.

Артефакты: `evidence/archive_session_isolation_20261016/`: freeze, input, selected
prediction/HTML, оба browser reports, screenshots, raw logs, final invariants,
tests/commands и небольшой ZIP. QA servers/profiles изолированы; серверы
остановлены, пользовательский annotation server не трогали. Runtime `/logs/`
теперь ignored в Git; пользовательские результаты не удалялись.

## Что осталось до завершения продукта

Шаги8/9 продвинулись: выбранный архивный сеанс действительно проходит до HTML
с правильной областью действия. Это не приёмка всей цели. Остаются independent
calibration/validation, реальная точность K/composition, непринятая duration
history2D.1 и аппаратные альтернативы. Continuous mode changes не определяются
этим gap partition. Нужны также bounded batch jobs для всех выбранных sources
и общие upload/RAM/time limits. Никаких обещаний полной готовности или99%.
