# Sparse stochastic duration validation: FAIL remains

Base: `41563f5852ec2708a0db6a590d04888b256baae9`.
Frozen code/config: `f55cf0d63b36694abc612b8a93310c511e88b250`.
[Протокол до запуска](SPARSE_DURATION_PROTOCOL_20261015.md).

Ни inference, ни likelihood, ни priors не изменены.76 целевых tests прошли до
одного sealed run.16 calls,27.984 CPU с/28.927 wall с всего worker; это не профиль
production pipeline.15 complete finite posterior,1 unavailable по path budget.
Повторов/настройки по результатам нет. Truth прочитана только после seals.

## Core12 cases, seeds7/23, K2/K3

| Metric | flat | soft |
|---|---:|---:|
| Per-case recall>=.8 PASS |8/12|7/12|
| matched / truth / predicted |29/34/30|29/34/32|
| boundary precision±2s |96.67%|90.63%|
| boundary recall±2s |85.29%|85.29%|
| matched MAE, s |.483|.552|
| conditional interval containment |33/34|33/34|
| conditional median / p95 width, s |2/8.7|2/8.7|
| conditional width<=4s |30/34|30/34|

Все case-level MAE/p95, nearest MAE, counts, count posterior, runtime и ranges
сохранены в comparison.json. Эти34 synthetic границы — другой набор, чем34
исторические real границы;29/34 нельзя назвать улучшением real raw19/34.
У intervals conditioning на **truth count только
в evaluator**:33/34 не означает восстановленный count или calibrated90% coverage.
Например P(truth count) в K3-shortening-seed23=.073/.265. Это не верхняя граница
точности и не lamp-switch interval. Matched MAE не включает пропуски; recall
и знаменатели обязательны. Gate на recall не гарантирует верное число фазовых
переходов: soft K3-stable-seed23 PASS с3 matched/3 truth/4 predicted.

## Конкретные провалы

- K2-hold10-seed7: truth boundaries8/28с, оба MAP10с;1/2 matched, одна граница
  пропущена. После28с есть одинm1 event31.690 и off-phase m0 event33.139.
  Count2 posterior=.137/.360; это неоднозначность данной event/prior модели,
  а не основание назначить движение доказательством GREEN.
- K3-shortening-seed23: truth4/10/20/30с. Flat MAP8/20 (2/4 matched), soft4/8/20
  (3/4). После30с в этом realization нет событий, а начальная фаза2 имеет лишь
  одно событие2.436с. Нельзя восстановление пустого хвоста объявить наблюдением.
- Supplied camera gap[10,18): оба MAP26с против truth8/18/28;1/3 matched.
  Скрытые переходы сохранены среди alternatives, но MAP их не выбрал.
- Hold+30, horizon64с: `PATH_BUDGET_EXHAUSTED_NO_POSTERIOR`;0/3/0, diagnostic
  extent0. Лимиты не увеличивали. Это конкретный computational blocker полного
  перечисления для целевого сценария, не доказательство невозможности задачи.

No-demand: posterior=prior, KL0; flat MAP без переходов, soft MAP с одним.
Случайное совпадение soft1/3 не означает reconstruction. Во всех cases published
logical/physical UNKNOWN100%. Complete diagnostic path extent100% относится
к модельному path, не к camera coverage и не к наблюдаемости лампы.

## Инженерное решение

Короткий deterministic witness не был достаточен: новый заранее зафиксированный
набор выявил point/count ошибки и path explosion.2D.1 остаётся FAIL. Не выбираем
flat/soft по этим результатам и не переносим supplied synthetic rates/delay на
реальные RELEASE. Старые K3/2/3 vs truth3/2/2, raw19/34 и production/default
сохранены; real replay/K search не выполнялись.

Полное перечисление оставить как small-input reference. Следующий шаг —
независимый review модели и выбора scalable inference, а не ещё один запуск
с увеличенным budget. Для joint-track log-sum likelihood нельзя без обоснования
объявить ordinary HSMM/DP точным: требуется factorization или честная approximate
search с truncation diagnostics. Одновременно reviewer должен предложить
минимальный путь к полезному trajectory-only output с assumptions/UNKNOWN,
отдельно от аппаратной lamp calibration и полного продукта.

Промпт: `EXTERNAL_REVIEW_PROMPT.md` в корне. Evidence ZIP содержит код,
объявленные assumptions, inputs/truth/seals, все compressed predictions и логи;
реальные видео/архивы в него не копируются. Не нужно снова калибровать те же8 ТС.
