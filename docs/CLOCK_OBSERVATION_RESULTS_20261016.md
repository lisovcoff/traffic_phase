# Результат проверки времени и смысла vehicle evidence

Base: `d4be0f1dbff24003cdb88ad9794f413777940930`.
Протокол: [CLOCK_OBSERVATION_PROTOCOL_20261016.md](CLOCK_OBSERVATION_PROTOCOL_20261016.md).
Его SHA256 до запуска: `60782c2f4a084dada5881658f1bb67aaf4f8132ae5da7868f8b8a640e9ad66df`.
Один запуск checker, без fitting/decoding/нового извлечения событий и кадров.

## Что установлено

Три сохранённых overlay readout за media326.033333–330.033333с дают одинаковую
арифметическую разность с прежним candidate: **+1.287171с**. Ответ пользователя
«Из часов камеры» включён как provenance, без нулевой погрешности синхронизации.
Origin прежний1740632395000ms; delta прежняя1.253838016с.

| Условный механизм display | Допустимая delta, с | Candidate внутри | Пересечение с прежним frozen-H set |
|---|---|---|---|
| Усечение до секунды | [-0.033333, 0.966667) | Нет; расстояние до замыкания0.287171с | Пустое |
| Округление до ближайшей секунды | [-0.533333, 0.466667) | Нет; расстояние0.787171с | Пустое |

**Обе** проверки предполагают одинаковый момент timestamping display/detection,
нулевую неизвестную latency, supplied UTC+5 и постоянный clock offset.
Эти предположения не подтверждены. Интервалы — условные feasible sets,
не calibrated confidence/switch-error intervals. Ни один режим не выбран.
Новый offset не вычислялся и старый не исправлялся.

Прежний frozen-H set `[1.057448,1.534785]`с получен при объявленных50px allowances
и той же фиксированной геометрии. Его несовместимость с обеими display-моделями
означает, что всю совокупность предположений нельзя считать подтверждённой.
Причина не локализована до одного параметра: возможны feature/geometry/identity
error, timestamp-stage или overlay latency/rounding assumptions.

Все4 прежних geometry anchors сохранены,18 видимых точек,2 unavailable. Старые
max residuals12.05–42.26px не переоценивались и не превратились в ошибку времени.
Raw mappings остаются proposals, supplier centroid definition/units UNKNOWN.
Saved scaled-Jacobian singular values2.181236…0.002039 (ratio≈1069.7) описывают
старый fit, не задают uncertainty или доказанную неидентифицируемость всех данных.
На участке равномерного движения `p(t+δ)=p(t)+vδ` изменение времени может
компенсироваться пространственным переносом. Несколько разных траекторий
могут уменьшить эту зависимость; низкий pixel residual сам по себе её не снимает.

## Полная таблица восьми video associations

Взяты все8 прежних наблюдений A/B, без отбора по знаку/ошибкам. H1 reference
привязан по capture+window, не ближайшему переключению. Все8 proxy ID совпали
по существующим identity hypotheses; это не новая identity validation.

| Track hypothesis | Окно | Vehicle-onset − H1 appearance, с | Отношение |
|---|---|---|---|
|9916410|A|[-1.266666,-0.233334]|До|
|9916373|A|[0.233334,1.000000]|После|
|9916450|A|[1.000000,1.766666]|После|
|9916436|A|[1.000000,2.000000]|После|
|9918413|B|[-1.500000,-0.500000]|До|
|9918426|B|[-1.000000,0.000000]|Касание|
|9918377|B|[0.500000,1.500000]|После|
|9918416|B|[0.733334,1.766666]|После|

Знаменатель8, два H1 references, один capture; media extent наблюдений
517.766667–1220.533333с, **не непрерывное coverage** этого промежутка.
Это sampled image motion и appearance H1 в одной шкале video PTS; их разности
не зависят от JSON offset. Поэтому исправление JSON clock не устранит эти два
отрицательных same-video отношения. Это не доказательство разрешения/нарушения,
причины старта, реакции водителя или истинного lamp switch time. Не подтверждены
полная permission semantics, независимое review и world-motion localization.
Модель «каждый RELEASE = H1 GREEN + неотрицательная реакция» не обоснована этими
наблюдениями; такую модель не запускали и отрицательные значения не обрезали.

## Проверки и артефакты

50 targeted/regression tests PASS: half-open display sets, несовместимые clocks,
nonfinite times, отсутствие readout, missing/ambiguous H1 association без nearest
fallback, нулевая fabricated probability, immutability/resource guards, все8
реальных development associations и старые seals/registration checks.

Checker прочитал115562B небольших JSON; runtime0.013с — время bounded checker,
не профиль inference и не новый runtime benchmark. Исторические confirmation,
model/registration и bundle seals проверены. `result.json`, CSV, freeze/manifest,
commands/tests/run logs находятся в `evidence/clock_observation_check_20261016/`.
Freeze содержит protocol/code/source hashes до вычислений. Повторный запуск
в тот же output запрещён; все прежние artifacts оставлены неизменными.

## Решение и следующий конкретный вход

Joint calibrated transform/error model **UNAVAILABLE**, не автоматически PASS.
Vehicle-signal delay/prior не выбраны; calibrated lamp probability=null;
physical states UNKNOWN. Никакой новой real phase accuracy не измерено.
2C/state contract остаются приняты;2D.1 FAIL/default-off; исторические
K3/2/3 против truth3/2/2, raw19/34 сохраняются.

Чтобы отделить время от геометрии, нужен timestamp correspondence, независимый
от положения движущейся машины: описание формирования detection timestamp и
camera overlay (rounding, update/exposure latency) либо оригинальный экспорт,
где detection timestamp связан с конкретным camera frame ID/PTS. По нему можно
зафиксировать clock range **до** проверки spatial residuals, не выбирая offset
по фазовым ошибкам. Полезны также supplier centroid feature definition/transform
и независимое review существующих соответствий. Если этих сведений нет,
uncertainty joint model остаётся открытой; это не запрет trajectory-only оценки
логической активности, а ограничение утверждений о точном времени ламп.

Для итоговой validation нужен отдельный capture того же перекрёстка с JSON и
независимо видимыми сигналами/журналом контроллера. Текущие A/B и три известные
записи development; новые параметры/допуски по ним не подбирались.
