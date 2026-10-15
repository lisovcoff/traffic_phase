# Локальные каналы evidence: протокол до эксперимента

Base: `b96f81f04d533cf0f721041460db727eb662539d`.
Цель этого шага — устранить remote-event loss в отдельном представлении данных
и проверить пригодность входа для будущей observation model. Никаких изменений
production selector/default, нового fitting, K search, period inference,
boundary offsets, likelihood или real replay.

## Контракт и фиксированные проверки

Сохраняются отдельные каналы (movement, event_type, evidence_method), а не
смешанный поток timestamps. ENTRY=спрос, STOP=стационарность автомобиля,
RELEASE=restart proxy, CROSSING_PROXY=zone-transition proxy. Даже подтверждённый
геометрией CROSSING описывает автомобиль, а не цвет лампы. Используются прежние
eligibility guards; не вводятся новые thresholds/weights/gap-fill.

Идентичные события дедуплицируются с сохранением source indices. RELEASE и
CROSSING_PROXY одного track fingerprint не являются независимыми автомобилями.
Неизвестная идентичность остаётся UNKNOWN; совпавший numeric ID не объединяет
разные fingerprint. Метод, timestamp, vehicle uncertainty и неизвестная связь
с сигналом сохраняются. Ключ source namespace задаётся SHA256 input session.

До обработки реальных артефактов фиксируются детерминированные случаи, без seeds
или random search: remote RELEASE другого автомобиля; remote RELEASE того же
автомобиля; no-stop crossing; restart + crossing одного автомобиля; идентичные
дубликаты; reused track ID; missing fingerprint; permissive turn; blocked queue;
no-demand при потенциальном GREEN; supplied observation gap; неизвестная exposure;
shared/arbitrary movements и bijective rename; неверные timestamps; ресурсный лимит.

Критерии: remote-event addition не меняет содержимое локальных каналов;
перестановка входа и rename не меняют counts/семантику; каждый eligible event
сохранён, кроме exact duplicates; distinct-track count не удваивается; supplied
gaps не заполняются; no events не доказывает RED/no-demand; все физические состояния
UNKNOWN. Original event bytes/provenance не мутируют. Лимиты явно возвращают
unavailable без частичного «полного» результата.

## Проверка на сохранённых данных

Только три sealed predictions `benchmarks/expert_intervals_20261015/predictions`.
Вход — их temporal_events и hashes. Разметку, adapters/comparison и группы фаз
runner не читает. Окно фиксировано: первые 180с от recording_start_timestamp_ms,
как техническое окно представления, а не обучающая выборка по truth. Runtime
до 30с/файл, максимум 20000 событий/файл, 32MiB prediction JSON/файл, три файла,
без retries; query до 1800с и 100000 returned events. Исходные predictions
сохраняются; повторного inference и новых boundary metrics не будет.

Отчёт: old selected vs eligible per channel counts, unique known tracks,
восстановленные движения, duplicates/exclusions, local fingerprint/provenance,
UNKNOWN/no-exposure reasons и runtime. Рост числа событий — не рост точности.

## Граница использования

Legacy occupancy Bernoulli likelihood принимает один timestamp-поток на movement,
не знает зависимости нескольких событий одного track и method-specific delay.
Новый объект не имеет неявного преобразования в такой вход. Экспортирует counts
и source-group identifiers, пригодные для отдельной модели наблюдений.
Совместимость с legacy likelihood должна сообщаться как unavailable, а не
вводить произвольные веса или calibrated lamp probability. Следующее испытание
наблюдательной модели требует явно заданных demand/exposure и delay assumptions;
для synthetic они задаются генератором, для реальных RELEASE нужна calibration.
Старый 2D.1 FAIL и результаты 0/11/19/34 сохраняются отдельно.
