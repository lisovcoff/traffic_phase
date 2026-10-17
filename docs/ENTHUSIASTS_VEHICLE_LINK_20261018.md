# Энтузиастов: источник видео подтверждён, clock link ещё открыт

Base `504103d8b3729287294c83a139c251fe5cf17ccf`, ветка
`calibration/enthusiasts-vehicle-link-20261018`. Продолжение после восстановления
сессии; первоначальный план подтверждён пользователем. Main и production code
не изменены. Phase fitting/replay/decoder/parameter search: **0**.

## Закрытый вопрос: откуда это видео

«Инфо.docx» прочитан полностью: 28 абзацев, включая пустые, hyperlinks и
единственное вложенное изображение. SHA документа совпадает с прежним intake:
`42559893c377a63f1ffcbabc32cda9510d82e16ad1008f8c5468c3e6db49f71c`.
В абзаце19 поставщик непосредственно связывает архив
«Ленина-Энтузиастов 05.10.24.zip» с
[этим видео ДТП](https://disk.yandex.ru/i/NwMsnq7xcOIn0A).
Ссылка подтверждена также OOXML relationship rId10, не только текстом URL.

Публичный API Яндекс Диска вернул имя
`len_ent_2024-10-05T12_00_00_2024-10-05T17_00_00.mp4`, размер6 792 283 598байт
и SHA256. Выполнен один полный последовательный read-only hash локального
`C:/Users/sheld/Downloads/lenina_entuziastov.mp4`: **SHA256 и MD5 совпали**.

```
SHA256 c574f9204abab0b2bd4dd88425e581da8d335c8e6be0cf4425c0ac7143bfa987
MD5    99c441fa7fdf5e3f9840587c76edde54
```

Таким образом, это точная копия supplier-linked video, а не только кандидат
по имени/дате. Проверка заняла31.442с, прочитано6 792 283 598байт; повторно видео
из интернета не скачивалось. Web reader не открыл публичную страницу; metadata
получены напрямую через public resource API. Источник/ответ сохранены.

Это **supplier association + media byte identity**, не независимая проверка
правильности каждого record архива и не PTS↔detection synchronization. Старая
проверка prefix timestamps2025-02-23 против video overlay2024-10-05 остаётся
фактом; она больше не основание считать пару неизвестной по происхождению.
Поставщик отдельно предупреждает об offline-processing timestamps, но не задаёт
offset, rate, drift или latency. Смещение дат не исправлялось.

Пользователь18.10 ответил, что соответствие предполагается при совпадении дат,
и направил к Инфо.docx. Это не превращено в подтверждение конкретных часов.

## Что проверено для vehicle matching

Один полный scan только малого entry `6_2025_2_23_13.json`:13 542 804байта,
CRC проверен, SHA256
`f71585ad7a887514d6fd254cdf86b3e08be54e915ca032f42ce08123efe501f6`.
**245 tracks/39 215 detections**:226 car,10 mini_bus,4 bus,4 mini_truck,
1 middle_truck. Detection extent1740300640994–1740301198973ms
(557.979с по этой шкале). Порядок records не считается временным порядком.
Остальные5 entries заново не декодировались.

В38 новых video contexts:9 native начальных кадров0..60с,21 coarse scaled JPEG
15..16200с и8 native уточнений100/110/130/220/230/250/310/330с. Реальные PTS,
ffmpeg commands и hashes сохранены; например requested100 даёт100.100000с,
requested110 —110.066667с. Не подменять их requested временем. Общий wall-time
38 ffmpeg calls75.234с, значительно ниже240с; ни одного интерполированного кадра.
Прежние full contexts0/9000/18000 также доступны и не перекодировались в source.

По native/scaled context sheets вручную рассмотрены начало потока и три
кандидатные последовательности крупных автобусов E→W: зелёный около90–150с,
красный троллейбус около220–250с и зелёный около300–360с. В JSON выделены bus
IDs258/441/652 по порядку/направлению. Это **provisional candidates**, не
подтверждённые индивидуальные соответствия: JSON не содержит appearance crop,
цвета/номера, frame ID или PTS. Разреженные context frames не подтверждают
непрерывную identity и не исключают другие машины между выборками. В250с,
например, видны два красных троллейбуса на разных траекториях.

Важное ограничение поставщика из абзаца16: рекомендована категория `car`, у
которой ниже погрешность обнаружения. Поэтому автобусные кандидаты не стали
calibration anchors. Это ограничение учтено в новых выводах, production selector
по нему не менялся. Вложенное в DOCX изображение показывает другой перекрёсток
как пример названий зон; его геометрия не переносилась на Энтузиастов.

Начальные автомобильные bbox/пути рассмотрены отдельно от native video start.
Гипотеза «первый JSON timestamp = media0» не принята. Геометрия raw image
coordinates не зарегистрирована с видео; другого H1 transform не использовали.
Подтверждённых car correspondences с независимыми контрольными машинами нет.

## Решение и дальнейший вход

**Source provenance: SUPPLIER_LINKED_MEDIA_HASH_VERIFIED.**
**Frame/detection clock: UNAVAILABLE_UNVERIFIED_CLOCK_LINK.**

Ни один кандидат не принят, clock/image fit не запускался, train/heldout split
не назначен постфактум. Offset, drift, calibrated uncertainty и paired metric
denominator остаются null/0. Это не доказательство несовместимости видео/JSON
или невозможности ручного matching. Ограниченная проверка пока не дала anchors,
удовлетворяющих первоначальному admission criterion; поиск по всем5 часам не
объявляется выполненным.

Для следующего clock шага есть два пути:

1. Небольшой producer export с кадром/ID исходной экспозиции/PTS и точным
   `detections[].millis` для нескольких `car`, разнесённых по записи. Уже готовый
   checker `scripts.check_frame_clock_links` переиспользован с пустым template;
   он честно выдаёт `UNAVAILABLE_NO_FRAME_LINKS`. Точный локальный запрос и
   конкретные record IDs подготовлены, никому не отправлены.
2. Более плотный ручной review автомобильных последовательностей с независимой
   регистрацией геометрии, явными альтернативами identity и заранее отложенными
   контрольными автомобилями. Одного класса/маршрута или сигнальных циклов мало.

Происхождение этой пары заново спрашивать не требуется. После admission anchors
нужно отдельно проверить clock rate/nonlinearity, не предполагать constant offset
и не выдавать оценку drift по одному короткому окну. Дальше остаются method-specific
event delay/demand calibration и отдельная validation-сессия; это не приёмка
локальной истории или аппаратных секций.2D.1 FAIL/default-off и UNKNOWN сохранены.

## Артефакты и проверка

`evidence/enthusiasts_vehicle_link_20261018/`: первоначальный план и отдельное
обоснование full source hash после находки supplier link, полный DOCX text/links,
public metadata, full hash result, inventory245 tracks, raw candidate buses,
38 frame records/commands/hashes, contact sheets, отдельные unresolved candidates,
пустой existing-schema frame-link template/check, supplier request и manifest.
Native PNG и полный13.5MB raw member лежат в task-local `.web_runtime`; исходники
не редактировались и не удалялись. Этого evidence недостаточно для clock fit.

**45 existing clock/video contract tests PASS**; прежние200 native frames/4
appearance brackets и protected source/main проверены сохранённым verifier.
Новый verifier проверяет38 frames, hashes, реальные PTS, admission/budget guards,
supplier link/hash result и неизменность production paths. Полный video hash
при этой проверке повторно не вычисляется. Логи и manifest записаны рядом.
Производственная точность и исторические predictions не переоценивались:
K3/2/3 против3/2/2, raw19/34, baseline17/34 остаются development результатами.
