# Unknown initial phase/count: bounded result

Base: `2a039c8173396c60e70ee5ea863186bc0fe00292`.
Code/config freeze: `058678d88138df77a2e8fdede96b857a57b22c8b`.
[Протокол до запуска](UNANCHORED_SEQUENCE_PROTOCOL_20261015.md).

Реализован opt-in `infer_unanchored`: fixed supplied K2/K3/order; неизвестны
initial phase и число внутренних переходов. Начальный возраст маргинализирован
по явно заданной grid-stationary renewal модели. Это допущение, а не измеренная
стационарность перекрёстка. Начало/конец записи не объявляются переключениями.
Все допустимые paths сохранены; при исчерпании paths/memory/time — unavailable
без posterior по префиксу поиска. Прежние flat/soft priors показаны рядом.

105 targeted tests прошли до запуска. Первый тестовый проход выявил один FAIL:
Windows process CPU clock не различал sub-tick timeout. Wall-clock deadline
закрывает этот дефект; CPU и wall time отчётны отдельно. Сохранены оба лога.
Memory allowance — консервативная оценка retained objects, не измеренный RSS;
time limit проверяется между bounded blocks, не hard OS preemption.

## Один запуск пяти engineering cases

Worker прочитал только sealed inputs, не truth. Outputs/hash зафиксированы до
оценки.5 inference calls;0.125 CPU с всего worker, не production profile.
Полный finite posterior:68 paths для каждого K2 case,102 для K3, без timeout.

| Case | flat matched/truth/predicted | soft matched/truth/predicted | State semantics |
|---|---|---|---|
| Informative K2 |4/4/4|4/4/4|diagnostic path exact|
| Informative K3, order2→0→1 |4/4/4|4/4/4|diagnostic path exact|
| Partial observation gap |4/4/4|4/4/4|prior/order-conditioned diagnostic|
| Zero supplied demand |0/4/0|0/4/0|prior-only, UNKNOWN|
| All observation missing |0/4/0|0/4/0|prior-only, UNKNOWN|

Неизменный `match_boundaries`, допуск±2с. Для первых трёх случаев precision/recall1,
matched MAE/p950. Эти5 коротких cases не являются population/lamp accuracy:
counts/marks deterministic, supplied rate model известна, phase grid2с. В16с
четыре перехода — максимально допустимое число, и min-duration constraints при
таком count фиксируют границы2/6/10/14с. Поэтому exact result не доказывает
произвольную temporal recovery; partial-gap успех тоже зависит от prior/order.
Не выдаём это за принятие hold/shortening или старого2D.1 gate.

No-demand и all-missing: KL(posterior||prior)=0, initial phase=.5/.5;
P(count0) flat=.511706, soft=.229257. Различие priors сохранено, production prior
не выбран. MAP no-transition не является утверждением об отсутствии переключений.
Diagnostic path extent100%; published logical UNKNOWN100%, physical UNKNOWN100%
во всех случаях. Temporal extent не camera coverage и не lamp observability.
Conditional ordinal boundary distributions выдаются отдельно для каждого count;
их нельзя смешивать в один интервал. Это posterior под supplied моделью, не
calibrated lamp interval. При numeric zero count mass conditional не выдаётся.

## Что снято и что остаётся

Снята обязательная передача initial phase/start и observed count. Hidden cycles
входит в пространство paths без специального наблюдаемого события. Полнота —
только относительно duration support/grid и stationarity assumptions. На длинных
окнах полное перечисление может исчерпать budget; отказ явно тестируется.

Не изменены core/HSMM/K solver/period/mapping/extraction/default/evaluator,
исторические predictions. Реальных fitting/replay и phase-label чтения нет.
2D.1 FAIL, K3/2/3 vs truth3/2/2 и raw19/34 сохранены.

Следующий bounded scope: независимые **sparse stochastic** hold/shortening и
разные начальные возрасты на более свободных horizons; rates/exposure assumptions
и критерии до запуска. После этого — проверка переносимости observation model
по имеющимся video/event evidence, без synthetic parameters по умолчанию на
реальных RELEASE. Для продукта ещё нужны K/состав, аппаратные альтернативы и
сквозная приёмка существующего HTML. Calibration не заменяет эту цепочку.

Артефакты: `evidence/unanchored_sequence_20261015/` — inputs/truth отдельно,
manifest, sealed predictions, comparison, команды/логи, diff и компактный ZIP.
