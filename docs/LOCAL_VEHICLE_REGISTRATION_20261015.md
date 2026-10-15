# Локальная привязка и источник раннего restart

Base `3b4da7f37a08d8e52d935c088545a245d2da4a52`, ветка
`calibration/local-vehicle-registration-20261015`. Main/default/phase inference не менялись.

План зафиксирован до новых кадров и расчёта. Использованы все семь прежних машин;
три для одной локальной image/clock calibration, четыре исключены из fit.
15 training points на media318/324/326/328/330; 18 validation points из20:
у грузовика и задней белой машины при318s обрезана задняя часть, поэтому точку
75% высоты независимо не задавали. Пропуски сохранены с причинами.
318/324 кадры переиспользованы без изменения, добавлены только326/328/330.
Новые кадры: 2.395s, 14,728,029 media bytes при лимитах90s/128MiB.

Использована существующая `fit_training`, без изменения objective/инициализации:
одна homography + constant clock offset, одна попытка, max_nfev1000/15s.
Ручные video points получены по bbox, центр X/75% высоты Y, как в прежнем fit.
Семантика supplier centroid не сертифицирована. RELEASE/сигнальные timestamps
в fit не передавались. После seal модели размечены withheld vehicle points;
новый fit по ним не запускался. Сцена уже просматривалась ранее: это не untouched holdout.

Fit:8 evaluations,0.0295s, rank9, без active bounds; max training residual23.88px
при заранее установленном допуске30px. На четырёх исключённых из fit машинах:

| Track | Видимые points | Прежний max,px | Новый max,px | Допуск50px |
|---|---:|---:|---:|---|
| 9915797, грузовик | 4/5 | 45.55 | 20.54 | PASS |
| 9915806, передняя тёмная | 5/5 | 80.76 | 20.68 | PASS |
| 9915811, задняя белая | 4/5 | 87.78 | 12.05 | PASS |
| 9915830, SUV у остановки | 5/5 | 158.14 | 42.26 | PASS |

Это поддерживает локальные соответствия машин и эмпирическую регистрацию,
но не сертифицирует world geometry, units или общую синхронизацию.
Сдвиг часов изменился всего с1.288667 до1.253838s относительно09:59:55UTC+5.
Новая геометрия существенно уменьшила пространственную ошибку при почти тех же часах:
прежнее расхождение у края кадра нельзя было целиком трактовать как clock error.
Локальная проверка ограничена318–330s и этими траекториями.

Пересечение withheld frozen-H feasible clock sets при заранее заданных50px:
**[1.057448,1.534785]s**. Fitted delta внутри. Это условное множество при фиксированной
геометрии/заданных pixel allowances, **не calibrated clock confidence interval**;
оно не включает joint geometry, identity, feature-definition и shutter uncertainty.
Новая модель сохранена отдельно, старый profile и все прежние результаты неизменны.

## Сопоставление с RELEASE после seal validation

Пересчитана только арифметическая привязка семи прежних событий; новых extraction,
fitting фаз или оценки границ по phase truth не было. Прежний sealed video review
не редактировался. Шесть точечных RELEASE раньше video onset brackets, один внутри.
У5/7 даже новое условное clock set не пересекает bracket;2/7 пересекают.
Signed point differences находятся в диапазоне от−1.188 до+0.155s относительно
разных концов video brackets. Все vehicle timing statuses остаются UNAVAILABLE
для сертифицированной оценки: identity/совместная timing uncertainty не измерены.
Heuristic localization radius1300ms не превращён в calibrated interval.

H1 mapping теперь подтверждён пользователем по фото: нижний подъезд, основной прямо
вверх-вправо, допсекция налево вверх-влево. Это operator mapping; protected/permissive
semantics независимо не проверены. Физические состояния в output остаются UNKNOWN.
Нельзя обучать общую delay distribution по этим семи машинам одного цикла.

## Проверяемый механизм, без изменения production

После real comparison проверена одна фиксированная synthetic гипотеза, не parameter search:
world vehicle неподвижен до20.0s, затем x растёт0.01/s; deterministic detection jitter
1e−5·sin(3t), шаг0.1s,40s. Текущая `_kinematic_release_candidate` возвращает18.9s.
В `app/core/v9/events.py:565` симметричный `gaussian_filter1d` с sigma примерно0.65s
использует будущие скорости: движение распространяется назад по сглаженному ряду.
Это конкретный механизм раннего proxy в независимом техническом контрпримере;
не доказательство, что он один объясняет ошибку каждой реальной машины.
Тест сохраняет witness прежнего поведения, **не принимает extractor/recovery gate**.
Raw speed units для этого рассуждения не предполагались известными.

Следующий ограниченный инженерный шаг: отдельно локализовать restart без переноса
будущего движения в прошлое, сохраняя отсутствие точного STOP, sampling gaps и
vehicle-vs-signal uncertainty. До реализации зафиксировать synthetic onset/noise/gap
контрпримеры и критерии; не сдвигать события общим offset по этим семи машинам.
Затем — независимые циклы calibration и отдельная validation session. Production
promotion, 2D.1 decoder или новый likelihood в этом шаге не реализованы.

## Воспроизводимость

`evidence/local_vehicle_registration_20261015/`: plan/seal,15 training points,
fit/seal,18 validation points/2 missing, validation result/seal, seven-event CSV/JSON,
33 native proof crops с SHA/PTS, команды/логи, diff, hashes и компактный ZIP.
Новые полные кадры локально в `.annotation_runtime/local_registration_frames/`.
Исходные source/model/evidence hashes проверены, production producer files неизменны.

31 targeted test passed2.68s. Первоначальное ожидание одного unit-test было ошибочным:
200px residual при delta0 допускает другой feasible offset; тест исправлен так,
чтобы проверять непрохождение frozen candidate и отсутствие refit, а не пустоту
всего множества альтернатив. До real validation прошли29 tests; после добавления
mechanism witness и artifact-seal test прошли31. Один fit и одна real validation;
параметры после результатов не менялись. 2D.1 FAIL/default-off, прежние метрики
raw19/34 и новые экспертные0/11 не пересчитывались и сохранены.
