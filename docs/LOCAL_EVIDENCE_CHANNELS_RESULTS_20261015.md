# Результат: локальное evidence сохранено, lamp timing ещё не исправлен

Base: `b96f81f04d533cf0f721041460db727eb662539d`.
Протокол до реализации: commit `55be614`,
[LOCAL_EVIDENCE_CHANNELS_20261015](LOCAL_EVIDENCE_CHANNELS_20261015.md).
Code/config freeze: `2058fa6d03a093b6ccb78607649ae6e40ca4f10c`.

## Реализовано

Изолированный `app.experimental.local_evidence` принимает существующие
TemporalEvent и строит неизменяемый индекс. Query возвращает полузакрытое окно,
раздельные каналы movement/type/method, source indices, исходные timestamps и
uncertainty, eligibility/exclusion и корреляционные группы по fingerprint.
Дубли событий объединяются с сохранением происхождения. Недостоверная identity
не восстанавливается из одного numeric ID. Новый объект не импортируется core
или API и не меняет production/default.

Remote RELEASE не удаляет локальные события даже для того же track fingerprint.
Это доказанная инварианта нового представления, а не приёмка всей reconstruction.
ENTRY остаётся demand; STOP не становится RED; no events не становится no-demand.
Exposure UNKNOWN без отдельного supplied source. Событие внутри явно supplied
gap сохраняется как противоречие данных, не заполняет gap. Физические и
логические состояния UNKNOWN; calibrated lamp probability отсутствует.

## Однократная проверка сохранённых sidecar

Никакой разметки, извлечения trajectories, fitting, period/K search, decoder,
нового likelihood или boundary evaluation. Использованы sealed predictions
предыдущего этапа и provenance hashes, техническое окно первых 180с.

| Запись | Старые selected events | Новые eligible vehicle events | Из них возвращены | Группы треков с eligible events | Runtime, с |
|---|---:|---:|---:|---:|---:|
| Свердловский 17_2025_2_12_7 | 16 | 114 | 98 | 98 | 1.048 |
| Чичерина 19_2025_2_25_8 | 61 | 211 | 150 | 150 | 0.431 |
| Энтузиастов 6_2025_2_14_6 | 3 | 11 | 8 | 8 | 0.350 |

Все 80 старых selected events сохранены; возвращены 256 CROSSING_PROXY.
336 событий не являются 336 независимыми автомобилями: eligible evidence относится
к 256 известным группам треков. Это сохранение данных, не увеличение точности.
На Свердловском E→W: 0→5, W→E: 0→15. Нельзя считать это 20 точными зелёными
сигналами или автоматически добавить 20 независимых Bernoulli observations.
Из входных событий ничего не удалено кроме exact duplicates (в этих sidecar их 0).
ENTRY и прочие каналы тоже доступны для анализа, но не получают permission role.

49 tests прошли до применения к сохранённым файлам: locality для того же/другого
треков, no-stop, paired evidence, duplicates/reused ID/unknown identity, permissive,
blockage, no-demand/gaps, rename/shared movement, immutability, resource exhaustion,
запрет annotations/fitting, прежние temporal contract regressions. Все три worker
завершились без retry/timeout. Исходные prediction hashes и production paths
остались прежними. Полные views с provenance и comparison находятся в
`evidence/local_evidence_channels_20261015/`.

## Как это приближает точность и что дальше

Устранён конкретный способ потерять локально наблюдаемое движение. Включать
этот объект в прежний Bernoulli HSMM как объединение timestamps сейчас некорректно:
likelihood предполагает отдельные occupancy columns, не описывает общую машину,
method-specific delay и неизвестный спрос. `legacy_streams()` поэтому выдаёт
structured unavailable `METHOD_DEPENDENCE_AND_EVENT_SIGNAL_DELAY_UNMODELLED`.
Это ограничение конкретного adapter, не утверждение о невозможности проекта.

Следующий алгоритмический scope — **одна совместная модель наблюдений на трек**,
где restart и crossing — связанные наблюдения с разными временными задержками,
а permissive/off-phase движение допускается моделью. Начать с заранее заданного
synthetic генератора с paired событиями, различным спросом, пропущенными detection,
заданной exposure и delay distributions; зафиксировать параметры до decoding.
Нельзя переносить exclusive-mark constraints из старого идеального прототипа.

Проверяемые критерии следующего шага: добавление второго события того же автомобиля
не удваивает независимую evidence; нет ложной уверенности без спроса/в gaps;
точечные ошибки оцениваются отдельно от interval coverage/width и UNKNOWN;
неоднозначные delay/exposure сохраняются как неоднозначность, а не нулевой offset.
Параметры на synthetic задаёт генератор; на реальных данных источник параметров
должен быть calibration, не эти 11 экспертных границ. Из trajectories можно
измерять совместные наблюдаемые времена автомобиля; задержку до реального
переключения без независимого сигнала подтвердить нельзя.

Production metric новых записей остаётся **0/11**, исторических — **19/34**;
2D.1 остаётся FAIL. K/period/raw/baseline не пересчитывались и не изменялись.
Для дальнейшего независимого signal validation сохраняется потребность в
синхронизированном видео/журнале, mapping и отдельном validation session.
