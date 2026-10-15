# Совместная модель на автомобиль: протокол до реализации и оценки

Base: `59cb228516b40ad41c52334b826286500714e4b1`.
Цель: использовать раздельные vehicle channels в согласованном likelihood без
двойного счёта автомобиля. Production/default, исторические gates, evaluator,
HSMM/K/period/mapping и реальные predictions не изменять. Real replay: 0.

## Декларированная конечная модель

Только synthetic. Известны K2/K3, cyclic order, phase start в t=0 и **ровно четыре
наблюдаемых сегмента**. Последний сегмент правосторонне цензурирован. Число
сегментов — supplied design assumption, не найденное алгоритмом. Неизвестное
число переходов/anchor должно давать unavailable. Прототип не решает discovery,
hidden-cycle count или смену K и не применяется к реальным неизвестным anchors.

Граница на сетке 2с, полные durations 4..48с с шагом 2с. Латентные vehicle
opportunities возникают в центрах grid cells (offset250мс), Poisson counts
с параметром lambda[m,phase]*2с*supplied demand/exposure multiplier[m,t].
Все основные marks неэксклюзивны: off-phase intensity >0. Shared movement
может иметь большую интенсивность в нескольких фазах.

Для каждой машины R=U+D, C=R+T. Synthetic D={0,2,4}с с mass{.25,.5,.25},
T={2,4,6}с с mass{.25,.5,.25}. R/C условно независимо detected с p=.8/.9
только внутри supplied observation windows. Их времена совместно зависят
от U,D,T; вероятности одного/двух пропущенных detections учитываются явно.
Timestamp resolution1мс; supported observations лежат на grid+250мс. Никакой
интерполяции off-grid времени: неподдерживаемый clock/delay -> unavailable.
Эти distributions описывают генератор, а не измеренные реальные RELEASE.

q_i(u)=P(весь observed pattern автомобиля i | u), включая missing/censoring.
p_det(u)=P(хотя бы одно наблюдение | u). Для fixed phase path z likelihood:

    log L(z) = -sum_m,u lambda[m,z(u)] * exposure[m,u] * dt * p_det(u)
               +sum_tracks_i log(sum_u lambda[m_i,z(u)] * exposure[m_i,u] * dt * q_i(u))

Это marginal likelihood thinned Poisson cluster process, с точностью до
path-independent measure factors. Каждый track даёт один log-term. Нули
occupancy других movements не подставляются как наблюдения RED. Silence может
информировать о path только при supplied rate/exposure assumptions.

## Интервалы и prior

Выбран один тип: **model-conditioned posterior** на полной конечной сетке.
Два заранее заданных duration priors, без выбора победителя:

- flat: uniform на {4,6,...,48}с;
- soft: discrete Laplace(center12с, scale8с) на том же support.

Последний duration использует survival mass. Приоры условны на известное число
сегментов и observation horizon; параметры не оцениваются по test truth.
Выдать diagnostic MAP path, ordinal posterior masses и equal-tailed90% intervals,
phase posterior и влияние prior. Это не feasible sets, не lamp probabilities и
не доказанная nominal coverage. Logical/physical publication остаётся UNKNOWN
до validation observation model; точечный путь диагностический.

## Suite до inference

Seeds2027 и4099, без retries/search. Независимый generator не импортирует decoder.
12 cases: stable_K2, stable_K3, hold10_K2, hold30_K3, shortening4_K3,
unequal_demand_K2, shared_K3, observation_gap_K3, no_demand_K2,
all_observations_missing_K2, changed_rate_K3 (misspecified), blockage_K2
(misspecified). Durations четырёх фаз [10,10,10,10], средняя вторая меняется
на +10/+30/-4 в соответствующем случае. Horizon=sum(durations)-2с: конец
не является последней boundary. Truth создаётся до decoder.

Неравный спрос задаётся known multipliers, shared mark — известной rate matrix;
no-demand case имеет supplied zero demand, без вывода zero demand из тишины.
Gap закрывает observation times12..24с; all-missing имеет пустые windows.
Changed rate и blockage меняют generator exposure, но не supplied inference
exposure: detection любого misspecification не обещается. Permissive/off-phase
events уже присутствуют в каждом обычном случае как положительный background.

## Критерии и лимиты

До suite: joint likelihood normalization; paired redundant mark не удваивает
evidence; counts/exposure/missing patterns корректны; unknown metadata и resource
exhaustion -> unavailable; rename invariance; immutability; supplied structural
zeros; same-car correlation; UNKNOWN common state contract.

Максимум24 inference calls, одновременно вычисляют оба declared priors по одному
и тому же likelihood. CPU suite60с, call5с, максимум10000 paths, horizon80с,
512 observed tracks, 50000 nonzero q-cells; массивы <=32MiB по declared bound.
Один внешний timeout90с, без retries. Любое усечение -> unavailable; нельзя
называть усечённый результат полным posterior. Генератор и результаты запечатать
до evaluation, truth не передавать inference.

Point: прежний evaluator ±2с, matched/truth/predicted, precision/recall, MAE/p95,
nearest MAE, coverage. Сохранить original per-case point criterion recall>=.8
отдельно для обоих priors на stable/hold/shortening. Не заменять его interval
containment. Posterior: truth containment, median/p95 width, доля<=4с, unissued
boundaries с знаменателями. Prior dependence и UNKNOWN отдельно. Ни один gate
не является приёмкой реальных lamp states. Старые 2D.1 FAIL, 0/11 и19/34 сохранить.
