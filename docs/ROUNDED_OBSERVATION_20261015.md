# Rounded event-time observation — bounded scope

Base: `bd960ed5e17e23a689154822eb74b4f82816570c`.
До запуска зафиксирован scope: continuous latent vehicle time, supplied discrete
vehicle-to-release/transit delay atoms, supplied timestamp rounding resolution,
piecewise-constant rates/exposure на прежних2с latent cells. Рounding origin также
подаётся явно: ячейки обязаны образовывать одну partition timestamps, а не
произвольные перекрывающиеся интервалы. Это снимает ограничение
observed timestamps=250ms+2s*n, но не разрешение фазовых границ и не known-count
ограничение sequence prototype. Никаких новых sequence runs или реального replay.

Модель: marked Poisson vehicle process. Для каждого latent time u вероятность
joint observed pattern учитывает оба detection и supplied observation windows.
Один track — один term. Интеграл intensity*pattern probability берётся точно
по пересечениям half-open интервалов; compensator использует вероятность хотя
бы одного detection. Timestamp y означает supplied rounding cell
[y-resolution/2,y+resolution/2), не interval ошибки extractor/сигнала.
Это допущение требует calibration перед реальным применением. Delay atoms относятся
к latent vehicle activity, а не к GREEN: nonexclusive rates допускают движение
до GREEN. Heuristic confidence нигде не участвует в likelihood.

Ограничения до тестов: horizon<=80с, events<=512, delay-pairs<=64,
windows<=32, q cells<=50000, elementary integration pieces<=2000000.
Budget exhaustion — unavailable без частичного likelihood. Synthetic technical
tests, без seeds/search: closed-form integrals; normalization all rounded patterns;
same-track pair; arbitrary millisecond event; censoring/gap; no demand; rename;
immutable inputs и resource refusal. Point recovery/accuracy здесь не измеряется.
Старые priors, gate FAIL и production/default неизменны.

## Результат

87 targeted tests passed,2.53с в финальной проверке. Проверена нормировка суммы всех rounded joint
patterns в detection exposure, closed-form Poisson count likelihood, fractional
delays/windows, линейность смеси delay kernels и within-track зависимость.
При self-review явно добавлены rounding origin и проверка общей partition;
неизвестный origin не подменяется нулём. Поддержаны timestamps с1мс resolution,
но разрешение переключений фаз остаётся2с. Это technical model checks,
не новая synthetic recovery оценка и не реальная phase/lamp accuracy.

Opt-in bridge выбирает новый backend только при
`clock_model="continuous_latent_rounded_marks"`. Старый режим по умолчанию
сохранён. На вход нужны источники rates/demand/exposure/delay и точная семантика
округления времени. Heuristic event uncertainty не используется вместо неё.
Physical/logical output самого bridge остаётся UNKNOWN: sequence inference
здесь не запускается. Исходные события/provenance не изменяются.

Один снятый барьер: arbitrary supplied rounded event timestamps вместо
250ms+2s*n. Не сняты: неизвестные initial phase/start/count, калибровка параметров
на реальных RELEASE и непрерывное положение фазовых границ. Следующий bounded
шаг — marginalization неизвестного start/count при fixed K/order с явным
budget/truncation status, без подмены production алгоритма. После него нужна
проверка локальных hold/shortening на независимой truth, затем сквозная приёмка
K/состава/секций и существующего HTML. Текущий2D.1 всё ещё FAIL.
