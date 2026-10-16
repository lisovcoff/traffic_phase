# Timestamp ↔ frame: проверка доступных входов

Base: `145b7a04e86d1430dfdf94c04cd4fc9dab0e4962`.
Ветка: `calibration/frame-clock-intake-20261016`.
Fitting, decoding, новый phase replay и изменение offset не выполнялись.

## Что проверено

В исходном сохранённом семитрековом cohort проверены **все3851 detections**,
1,322,708B JSON. Source SHA совпал с ранее sealed raw-anchor source.
В track/detection fields нет `frame_id`, `frame_number`, `pts`, `dts`, `time_base`
и перечисленных в source inventory aliases. Полные key/count tables сохранены.
В detections есть `millis`, bounding box, centroid, speed, lat/lng и zone.
Числа координат сами по себе не подтверждают их supplier semantics/units.
Вывод об отсутствии frame-link ограничен этим cohort, не всеми архивами.

Проверено, что `scripts/build_restart_video_review.py` копирует целые raw records
из ранее подготовленного sample; `app/core/calibration_sample.py` также сохраняет
track целиком. Новые frame IDs этими consumers не создаются. В проверенных
canonical app/scripts нет реализации timestamping исходной камеры/экспортера.
Никакие исторические producer-пакеты не приняты как текущая production-основа.

Один `ffprobe`-запуск прочитал metadata существующего MP4, без `show_frames`,
`show_packets` или декодирования. `probesize=1048576`, `analyzeduration=0`,
subprocess timeout15с. Probesize **не** является верхней границей всего I/O
demuxer; фактические bytes read не измерялись. Размер исходника совпал с saved
metadata3,089,546,077B; это не новая full-content identity validation.

Получено:

- `start_time=0`, `time_base=1/90000`, `nb_frames=180650`;
- `r_frame_rate=30/1`, `avg_frame_rate=541950/21649` (около25.03);
- duration7216.333333с; tags содержат `encoder=Lavf58.76.100`, container brands,
  language/handler, но не связь absolute camera timestamp с JSON detection.

Это не доказательство режима переменной частоты само по себе и не проверка всех
MP4 atoms. Разные rate fields нельзя использовать как основание для
`PTS=frame_number/30`; нужен реальный PTS и учёт происхождения/редактирования
записи. Encoder tag описывает muxer, не источник detection clock. Файловый mtime,
имя MP4 и container start_time не подставлены вместо camera clock.

В Инфо.docx проверены только относящиеся к timestamp/frame/centroid поля:
текст содержит прежние определения millis и offline warning; нового текстового
frame-ID/PTS определения не найдено. Это не утверждение о расшифровке embedded
screenshots или наличии внешней vendor documentation. Старый excerpt не изменён.

## Готовый приёмник поставляемой привязки

`app/experimental/frame_clock_links.py` и CLI работают отдельно от production:

```powershell
C:\Python314\python.exe -m scripts.check_frame_clock_links --input config/frame_clock_links_template.json --out frame_clock_check.json
```

Текущий template содержит0 строк и незаполненные source IDs. Реальный запуск
вернул `UNAVAILABLE_NO_FRAME_LINKS`, offset/uncertainty=null, лампы UNKNOWN.
Шаблон не следует заполнять временами, угаданными по движению.

Нужен JSON такого же schema от producer или документированной frame-identity
связи; поля строки:

| Поле | Содержание |
|---|---|
|frame_id|Идентификатор исходного exposure; связь с кадром экспортированного MP4 должна иметь источник|
|video_pts_ticks|Реальный presentation timestamp этого кадра, integer; signed PTS допустим|
|video_time_base|Пара положительных integers numerator/denominator, не FPS|
|detection_timestamp_ms|Значение именно detections[].millis для этого exposure|
|frame_identity_reference|Ссылка на exporter row/log/source, подтверждающий тот же кадр|
|timestamp_uncertainty_ms|Предоставленная граница relevant timestamp/exposure error либо null|
|uncertainty_source|Источник/смысл этой границы; не heuristic restart radius|

На уровне документа нужны capture/video/trajectory source IDs, source_reference
и `association_basis=producer_frame_identity`. Предпочтительны несколько пар
в разнесённых частях записи, а не повторения одного кадра. Если переданы только
clock-origin сведения без таких пар, это сохраняется как provenance, не sync.

Checker использует точные rational PTS arithmetic. Для полностью supplied error
bounds выдаёт пересечение **условных** constant-offset sets с закрытыми концами.
Clock scale/drift не подбираются; противоречие даёт
`INCONSISTENT_DECLARED_CONSTANT_CLOCK`. Missing uncertainty или provenance
сохраняют UNAVAILABLE. Повторные/несортированные frame identities, bool/nonfinite
uncertainty отвергаются; равные integer millisecond timestamps разных frames
допустимы при возрастающих PTS. До1000 rows/512KiB, свежий output обязателен.

Даже статус `DECLARATIONS_READY_FOR_INDEPENDENT_REVIEW` не является scientific
validation или автоматическим promotion transform в inference. Во всех случаях
`production_usable=false`, accepted transform/calibrated uncertainty=null.
Ни phase labels, ни vehicle motion не принимаются как association basis.

## Проверки и следующий конкретный вход

53 targeted/regression tests PASS (включая rational/signed timestamps, no input,
unsourced uncertainty, conflicting frames, immutability/resource limits и
предыдущие clock/bundle seals). Metadata/полный key inventory, template result,
commands и tests сохранены в `evidence/frame_clock_intake_20261016/`.
Core/default/main, старые predictions и scientific gate не менялись.

**Нужен один внешний материал:** небольшой исходный exporter/log fragment с
соответствием `camera frame/exposure → MP4 PTS + detections[].millis` либо
vendor-описание, как это соответствие и его погрешность формируются. Точный
вопрос поставщику сохранён в `SUPPLIER_REQUEST.md` рядом с evidence. Самостоятельно
создать такую ground truth из этих же траекторий нельзя. Новый interface для
повторной разметки тех же машин не требуется.

2D.1 FAIL/experimental/default-off остаётся; historical K3/2/3 vs truth3/2/2,
raw19/34 не пересчитывались. Trajectory-only logical activity остаётся доступной
со своим UNKNOWN contract; этот конкретный independent clock-validation шаг
ожидает вход, а не блокирует весь проект навсегда.
