# Возврат к цели продукта и локализация restart

Base `73b017d01693ed47e8ac5a8a0341cd3560d4ea4a`.
Ветка `fix/restart-time-localization-20261015`.

## Почему этот шаг нужен конечному продукту

Цель: автоматический JSON/ZIP → подходы/движения → K/состав фаз → история
продлений/сокращений → возможные основные/дополнительные секции → HTML/API.
Последняя работа с видео выявила реальный механизм искажения входных timestamps,
но повторная калибровка тех же семи машин сама по себе не завершает ни один из
основных результатов. Критический путь уточнён в начале корневого ROADMAP.md.

Сейчас есть загрузка, bounded discovery, защитный query contract и основа HTML.
Правильность K/composition ещё не принята на независимых данных; local history2D.1
FAIL, hardware mapping остаётся гипотезой без достаточного внешнего evidence.
Поэтому мы ещё не на этапе «осталось оформить интерфейс». Процент готовности
по количеству файлов/тестов не используется. Общая точность фаз в этом шаге
не пересчитывалась и не объявляется улучшенной.

Режимы/секции РФ должны быть проверяемой матрицей сценариев, а не обещанием
распознать любые причины по траекториям. Обнаружить удлинение и назвать его причиной
спецтранспорт — разные задачи. Один поворот не определяет аппаратную стрелку;
для неразличимых вариантов нужны альтернативы/UNKNOWN, при этом обычный вход
готового продукта остаётся JSON/ZIP без обязательной ручной разметки.

## Реализованное изменение

`app/core/v9/events.py::_kinematic_release_candidate` сохраняет прежний выбор,
tuple и default timestamps. Добавлен только opt-in диагностический выход с уже
рассчитанными raw speeds, относительным threshold и confirmation guards.
Численные guards не изменены; вынесены в локальные переменные, чтобы эксперимент
использовал те же значения. Старый код clustering/discovery не скопирован.

`app/experimental/restart_localization.py::localize_restart` принимает исходный
трек и **уже выбранный** TemporalEvent. Legacy seed остаётся reference; локальная
область поиска ограничена конечной поддержкой существующего Gaussian kernel.
Время нового proxy берётся с правой границы первого несглаженного наблюдаемого
интервала перехода low→high при полной исходной confirmation window. Энергия
будущего движения больше не используется как измерение скорости прошлого интервала.

Это offline localizer: дальнейшие наблюдения подтверждают событие, threshold и
seed всё ещё используют весь трек. Он **не online/causal detector**, не абсолютный
STOP и не точное world-motion/signal onset. При двух поддержанных raw transitions
оба сохраняются как альтернативы, публикуемый event отсутствует и estimate UNKNOWN.
Нет выбора лучшего перехода по видео. Gaps, conflicts, короткий/обрезанный support,
неверное происхождение и ресурсный предел имеют отдельные abstention reasons.

Используются общие StateEstimate/TemporalEvent/physical_estimate и существующая
sanitization. Heuristic confidence и radius наследуются с прежней некалиброванной
семантикой; sampling bracket относится к threshold-displacement evidence, не к
гарантированному моменту первого физического движения. Event→signal uncertainty
остаётся UNKNOWN, calibrated lamp probability отсутствует. Production selector,
default, HSMM, K/period/mapping и старые predictions не изменены.

## Сначала независимые контрпримеры

До реализации зафиксированы plan SHA,21 cases, seeds7/23, generation truth,
noise/exposure, критерии и30s CPU budget. Генератор отдельно от inference создаёт
координаты автомобиля: abrupt onset, ускорение, два sampling steps, no-motion,
nonstop, единичный spike, gap, обрезанный tail, одинаковые/противоречивые duplicates,
пустой вход и прежний sine witness. Ни один threshold не выбран по реальному видео.

Все21 criteria выполнены:9 ожидаемо восстановимых proxy получены,12
неидентифицируемых случаев abstain. На9 recoverable случаях point MAE относительно
независимого world-onset: legacy0.811s → new0.167s. Это synthetic vehicle metric.
У ускорения новая точка отстаёт на0.450s: она отмечает относительный threshold,
а не первое ненулевое движение. Для7 abrupt cases sampling intervals содержат
generation onset; такую гарантию для acceleration/реальных данных не заявляем.
Все physical states UNKNOWN. Synthetic suite runtime0.297s при бюджете30s.

Дополнительные структурные tests проверяют multiple alternatives, смену names,
неразличимые причины движения, resource limit, source mismatch, одинаковые legacy
результаты с/без diagnostics и запрет argument annotations. Исходный recovery
gate2D.1 этим vehicle gate не заменён и остаётся FAIL.

## Один development check после code/config seal

После synthetic gate зафиксированы код/config и хеши входов. Один проход всех
семи прежних треков, без новых видео, архивов, clock fit или phase replay.
Outputs и SHA сохранены **до** загрузки video onset review для оценки.
После результатов ни код inference, ни thresholds не изменялись.

| Показатель | Прежний seed | Новый opt-in proxy |
|---|---:|---:|
| Всего треков | 7 | 7 |
| Выданные события | 7 | 6 |
| UNKNOWN/abstention | 0 | 1 |
| Point внутри сохранённого sampled video bracket | 1/7 | 6/7 |
| Независимых циклов | 1 | 1 |

UNKNOWN у9915811: два поддержанных raw transitions; обе альтернативы сохранены,
по truth ни одна не выбрана. Отсутствующее новое событие не исключено из знаменателя.
Runtime семи событий0.142s. Все7 старых timestamps, duration, capped heuristic
confidence и separation точно воспроизводятся в unchanged default path.

Это **не оценка lamp accuracy**, не независимый holdout и не приёмка общей
точности restart. Привязка часов и identities условны; сравнение сохраняет
UNAVAILABLE для сертифицированной timing validation. Новые proxy нельзя сразу
объявить переключением GREEN или реакцией на него. Старые phase metrics raw19/34
и новые экспертные0/11 сохранены; новый fitting/benchmark не запускался.

## Выход из этого шага

Локальное искажение от сглаживания имеет отдельное проверенное исправление;
production promotion пока отсутствует. Не продолжать бесконечно калибровать те же
семь машин. Следующий bounded шаг — независимые циклы/отдельный validation для
vehicle localization и method-specific signal relation, затем явная интеграция
проверенного event contract в основную цепочку K/composition/local history.
Если проверки провалятся, требуется конкретная модель ошибки, а не общий offset
или выбор удачного prior по знакомым записям. Decoder/likelihood/prior experiments
не возобновлены этим заданием.

## Воспроизводимость

Артефакты в `evidence/restart_localization_20261015/`: preregistered plan,
отдельные synthetic inputs/truth/output seals/metrics, code/config seal, все7 real
outputs с альтернативами, отдельный comparison, команды/логи, хеши/diff/ZIP.
Большое видео и прежние predictions повторно не упакованы.

Итог: **81 targeted tests passed2.86s**, включая затронутые trajectory/evidence
regressions и проверки сохранённых артефактов. Основные команды — commands.log.
Main и production default сохранены. Для portable проверки исходников дополнительно
сохранены canonical-LF hashes/Git blob IDs; первоначальный byte-exact seal до
inference не переписан. Это устраняет различие CRLF/LF при checkout без изменения
алгоритма или параметров после real check.
