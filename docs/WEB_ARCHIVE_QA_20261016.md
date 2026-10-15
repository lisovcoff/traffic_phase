# Настоящая проверка ZIP → обработка → пространственный HTML

Base: `e3e4cde27f1bab89198a0040bbb9592571ab4306`.
Ветка: `fix/verified-web-archive-flow-20261016`.

Запуск после перезагрузки: `START_WEB.cmd` в корне canonical repo, затем
`http://127.0.0.1:8017/visualization`. Launcher использует task-local TEMP/TMP
на диске проекта, не заполненный системный C. `START_WEB.cmd --check` проверяет
импорт приложения и temp path без запуска сервера; зависимости не устанавливает.

## Подтверждённые дефекты и исправления

Основной `/visualization` использует другой spatial renderer, который оставался
в обход общего контракта: activity threshold и inferred physical plan назначали
цвета, время сворачивалось по периоду, вне истории подставлялся сегмент. Теперь
reconstructed spatial view использует подготовленные интервалы общего
`build_report_payload`/`prepare_logical_query`, учитывает отдельный schedule/display
anchor и сохраняет gaps/out-of-range UNKNOWN. Physical heads UNKNOWN, без
выдуманных дополнительных секций; вопросительный знак отличает это от OFF.
Движение автомобилей сохранено. Схема подписана условной, не подтверждённой геометрией.

Старое configured поведение доступно только при явном `render_html(mode='configured')`
или simulated. Оно не включается наличием inferred plan. Тест, ожидавший физические
цвета, теперь явно выбирает configured: .9/.1 activity и предполагаемая стрелка
не являются наблюдением лампы. UI больше не называет длину первого обрезанного
сегмента длительностью фазы цикла: показывает число интервалов истории.

Применена существующая минимальная правка из `cb104669384fc67af05723854568fe5206d4380c`:
explicit physical plan (включая disabled) не перезаписывается auto plan. Mapping
objective не менялся. JSONL экспорт веб-результата тоже переведён на общий
logical query и UNKNOWN hardware, без fabricated RED или modulo-phase fallback.
Corrupt ZIP возвращает422; ENOSPC возвращает явный507 вместо непрозрачного сбоя.

## Метод и фактические запуски

Bundled browser skill прочитан, bootstrap снова не запустился: kernel assets,
os error3. Применён fallback: установленный Edge в отдельном headless-процессе,
с собственным временным профилем, без подключения к пользовательским сессиям.
CDP-драйверы без новых зависимостей: `scripts/qa_web_archive.mjs`,
`scripts/qa_saved_web_reports.mjs`. Это настоящий browser DOM/canvas/network,
не прежний Node DOM mock. Screenshots просмотрены вручную ассистентом.

В браузере открыта форма `/visualization`, выбран файл через file input,
нажата кнопка анализа, дождались ответа/iframe и распаковки trajectories.
Проверены play/pause/reset, изменение времени, canvas, desktop1440px/mobile390px,
отсутствие горизонтального overflow и JavaScript exceptions.

| Вход | Размер ZIP | Траектории / события | K | Период, с | Browser upload→ready |
|---|---:|---:|---:|---:|---:|
| Existing fixed synthetic smoke, с иллюстративными координатами | 1223B | 40 / 40 | 2 | см. сохранённый prediction | 7.006с |
| Existing calibration sample27.02, без новой выборки | 4166427B | 243 / 238 | 2 | 100.814 (округлённо) | 10.304с |
| Corrupt ZIP | 14B | неприменимо | unavailable | unavailable | 422,0.264с |

Real sample: прежние243 whole tracks из уже сохранённого calibration JSON.
Изначально выбраны по временному окну10:04–10:07, но целые tracks расширяют
display extent до10:02:42.148–10:07:23.301. Это честно показано на странице,
не новый signal anchor. Пять same-origin/destination tracks (E→E/W→W) по
существующему extractor/compact contract не дают movement evidence; raw243
не уничтожены. Не утверждается, что эти пять треков физически ошибочны.

Первая real upload не дошла до готового результата из-за C: free0B/ENOSPC.
Повторена только эта infrastructure-failed загрузка с temp на D:, без изменения
настроек модели. Завершённых discovery запусков2: synthetic и real. Никаких
parameter search/tuning сверх обычного принятого K-search pipeline. После них
страницы только повторно рендерились из saved prediction; fitting не повторялся.
Реальные большие архивы не распаковывались. Новые source truths не читались.

## Проверка правильности и пределы

В реальном браузере111 phase queries (71 synthetic,29 real,11 gap/anchor
counterexample) совпали с Python common query. Проверены непосредственно
границы±.01с, gaps, отрицательное время и время за историей. Все physical states
UNKNOWN, стрелок не придумано. Отдельно прежний offline report проверен вне
диапазона: логическая фаза и лампа UNKNOWN.66 targeted/regression tests проходят.

Это **согласованность реализации**, не independent phase/lamp accuracy. Real
subset дал K2; независимый complete phase plan для этого subset не установлен.
Результат не объявлен правильным K, не заменяет прежние development метрики
K3/2/3 vs truth3/2/2, raw19/34 и не принимает2D.1. Продления/сокращения остаются
FAIL/experimental opt-in. Hardware validation и полный продукт не завершены.

Артефакты: `evidence/web_archive_qa_20261016/`: browser_results,
saved_browser_results, expectations, input/output seals, server predictions,
HTML, desktop/mobile screenshots и tests.log. ZIP пакует также JSONL timelines;
сырые14MB trajectories и4MB real ZIP повторно не упаковываются. Raw source
идентифицируется ссылкой/entry hash; готовый real HTML можно открыть без сервера.

Для воспроизведения локальной проверки нужен свободный TEMP/TMP. В этом запуске
из-за заполненного C использован только task-local temp на D, без очистки чужих
файлов и без изменения постоянных системных настроек. Рабочий пользовательский
annotation server8011 не трогали; QA server8017 останавливается после проверки.
Процессные/профильные файлы не входят в commit.
