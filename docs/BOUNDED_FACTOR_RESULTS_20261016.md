# Exact DP с ограниченной историей vehicle factors

Base: `9cfec60b8b7f1d9cef9d442f2c838be953a11d8c`.
Code/config freeze: `9a4584332e053f93bff7be4e9860e2e29ebcfc00`.
Ветка: `experiment/bounded-factor-history-20261016`.
[Протокол](BOUNDED_FACTOR_PROTOCOL_20261016.md).

## Что изменилось

Новый opt-in `infer_bounded_context` использует существующие context/query kernel
и совместные q автомобиля. Factor log(sum(lambda*q)) вычисляется один раз на
последней положительной q-cell. Prefix-state сохраняет последние W phase labels
и observed run length. При одинаковом state все незавершённые factors получают
одинаковую релевантную предысторию; их можно объединять суммированием масс.
Число переходов сохраняется отдельной forward-count осью. Это не scalar HSMM
для произвольного nonlocal likelihood и не approximate beam.

Initial residual и full durations берутся из прежних flat/soft priors. Survival
hazards до первого перехода используют residual distribution, затем full duration.
Run length=j+1 однозначно означает ещё не завершённую первую observed phase.
Так duration tails маргинализированы, а не максимизированы как скрытые totals.
MAP, count/phase posterior и existence каждой внутренней границы не требуют truth
count. Начало/конец context не объявляются переключениями.

Default span<=3 cells (6с), явный максимум5. Span=last-first+1, включая holes.
Значение1e−100 не отбрасывается. Более широкий kernel, превышение числа states,
memory allowance или deadline возвращают unavailable без partial posterior.
Только нулевая масса исключается точно. Production/local-only DP/default не менялись.

## Проверка

22 targeted tests до единственного technical run. С полным перебором на коротких
K2/K3 cases совпали normalizer, count/phase/boundary marginals, MAP-score; отдельно
проверена точная closure factorization с существующим path_loglik для всех small
paths. Проверены реальные observation-components с delay mixtures и парой
RELEASE/CROSSING_PROXY на support2/3/4 cells; sparse holes, structural zeros,
initial/right censoring, rename/immutability, эквивалентность local DP и resource
failure до/после накопления состояний. Часть q-fixtures искусственные для
алгебраической проверки: они не объявляются сгенерированными реальными trajectories.
После run добавлен отдельный guard-counterexample: одинаковые current phase/age
с разной релевантной history имеют разные closure values и не должны сливаться.
Итог:23 новых unit tests+3 artifact checks+152 регрессии, всего178 passed в4.55с.

Technical64с K3 example:5 vehicles/10 paired marks, delay atoms0/4с и transit2с,
support span3. Fixed rates/exposure/rounding supplied; recovery truth отсутствует.
Результат complete, max72 states/layer,1476 retained states; без enumeration
и truncation. DP self CPU.140625с/wall.154883с, conservative state allowance
6642592 bytes. Это не peak RSS и не end-to-end throughput большого JSON.
Не запускали старый hold+30 replay: его historical FAIL не заменяется этим примером.

Все обе-prior predictions, вход и hashes сохранены. Logical/physical UNKNOWN100%;
диагностическая temporal extent context64с, target10..56с — другая величина.
Posterior existence — вероятность внутри supplied grid model, не calibrated
lamp probability и не готовый publication threshold.

## Оставшиеся ограничения и следующий шаг

Теперь широкие до заданного span kernels не требуют перечисления всех paths.
Это снимает конкретный scaling blocker при ограниченной factor history, но не
делает произвольные kernels/часовые записи поддержанными. Context horizon80с,
K2/K3 fixed и duration support4..48с сохраняются. Нет skip/reorder/смены K/online.
Delay bounds, rates/demand/detection и полнота index по-прежнему supplied assumptions.
Реальная привязка RELEASE к сигналу не калибрована.

Core/HSMM/K solver/period/mapping/evaluator, extraction/selection, thresholds,
main и исторические artifacts сохранены.2D.1 остаётся FAIL; real K3/2/3 против
truth3/2/2 и raw19/34 не изменились. Никаких новых recovery suites/real replay.

Следующий шаг к продукту: зафиксировать применимость observation assumptions
и input/mapping на доступных данных, затем согласовать реальный calibration/
validation pilot с независимыми сигналами/sync. Не переносить synthetic nuisance
parameters в production и не запускать ещё один convenient synthetic recovery
вместо этого. Поддержку часов/скользящих context нужно спроектировать с сохранением
глобальных vehicle IDs и зависимостей, без независимого умножения overlap likelihoods.
