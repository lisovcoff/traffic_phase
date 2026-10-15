# Другие циклы и интеграция event-контракта, 2026-10-15

Base `f85690183080815cb3ee3278c2ff73406f95ed15`, ветка
`validation/restart-other-cycles-20261015`. Цель шага — проверить переносимость
vehicle timestamps перед использованием в фазах. Новый decoder/likelihood/prior,
phase replay, K search и production promotion не запускались.

## Зафиксированный протокол

До чтения новых данных/видео sealed plan: блокA media500–560s (08:20–09:20),
блокB1200–1260s (20:00–21:00), последний — withheld temporal block той же камеры/дня.
Это не независимый перекрёсток/день. Все243 прежде просмотренных track IDs исключены;
переходящие между окнами треки также подлежат исключению. Один streaming-проход
одной заранее известной записи `17_2025_2_27_10.json`:272,972,956 bytes/10.823s,
complete entry SHA совпал с историческим. Другие часовые entries не декодировались.

Получен61 N-origin raw track для двух окон. По прежнему permission selector
eligible RELEASE11 вA/8 вB. Выбраны первые4 хронологически на блок, до просмотра
видео; остальные7/4 явно отмечены как исключённые по бюджету. Не отбирали по
успеху, видимости или новому extractor output. Восемь целых raw tracks сохранены.
Новые event outputs/hash seal записаны до video sampling и review. Код/параметры
локализатора, relative thresholds, clock model и old selector не менялись.

Технический сбой до открытия ZIP: исторический manifest содержит mojibake в пути.
Старый plan сохранён; `archive_path_resolution.json` фиксирует единственный реальный
файл по дате, размеру, entry size/CRC. Неудачная попытка не прочитала entry;
успешных сканирований ровно одно. Лог ошибки сохранён.

Извлечены97 native ROI frames по заранее заданным правилам:26 coarse +39A +32B,
sampling29.348s суммарно,157,954,583 served-media bytes в трёх вызовах,
каждый ниже90s/128MiB. Whole-video SHA не заявляется: identity — прежние три1MiB
chunks. Большие кадры остались локально;21 компактный proof image имеет SHA/PTS.

Все8 onset brackets и оба H1 appearance brackets размечены по fixed-scene pixels,
затем sealed до сравнения результатов. Новый timing output при разметке не смотрели;
legacy seeds использовались для sampling/identity, поэтому reviewer не полностью
blind. Это assistant visual review без независимого второго человека. Identity
поддерживается классом/порядком/путём, но не сертифицирована поставщиком.

## Проверка переноса geometry/clock — без refit

Из12 предусмотренных anchors11 видимы; у одного верх автомобиля вышел за fixed ROI,
точку75% bbox не выдумывали. Использован frozen H/delta1.253838s и прежний50px
allowance. По полному declared delta domain[-5,5] проверена поддержка source samples;
граница доступности старого training track не превращена в новый clock prior.

ВA встречаются gaps1012ms в области clock anchors, тогда как прежняя интерполяция
разрешает300ms. Это **UNAVAILABLE_SOURCE_SUPPORT**, не опровержение часов. Missing
domains нельзя исключить как несовместимые clock values. Диагностические residuals
по пяти доступным nominal anchors3.71–42.07px, у шестого nominal prediction unavailable.
Измеренный clock interval дляA не выдаётся. Сами restart sampling intervals при этом
113–120ms: поздние gaps нельзя выдавать за объяснение каждой ошибки начала движения.

ВB source support достаточно для проверки5 anchors; nominal residuals5.63–21.01px.
Frozen-H conditional clock set **[0.812177,1.577803]s**, nominal delta внутри.
Это не joint calibrated clock confidence interval; geometry/identity/feature/shutter
uncertainty не измерены. Нового offset или H не выбирали.

## Все результаты, включая ухудшения

Расстояние = расстояние nominal event point до sampled video onset bracket.
Восемь selected RELEASE — не все автомобильные старты; population recall не измеряется.

| Метрика | A old → new | B old → new |
|---|---:|---:|
| Треков/выданных events | 4/4 → 4/4 | 4/4 → 4/4 |
| Point внутри sampled video bracket | **2/4 → 1/4** | 0/4 → 2/4 |
| Среднее расстояние до bracket | 0.190 → 0.155s | 0.588 → 0.205s |
| UNKNOWN localizer | 0 | 0 |
| Сертифицированная timing validation | UNKNOWN | не calibrated; conditional only |

ВA у9916373 и9916436 прежняя точка внутри sampled bracket, новая позже него;
это ухудшение не скрыто. Нельзя полностью приписать его extractor: joint clock
validationA unavailable и визуальный onset имеет собственное разрешение.
Номинальные event results — development diagnostics, не real lamp accuracy.
`sampling_interval_diagnostics.json` дополнительно показывает raw sampling widths/
elapsed confirmation. Это не замена point gate и не calibrated world-onset intervals;
исходный comparison и его отрицательные результаты сохранены.

## Существенный контрпример для фазовой модели

H1 main+lateral green appearance:
A[518.766667,519.033333], B[1218.766667,1219.033333] media seconds.
По одному ТС в **каждом** окне sustained image motion начинается раньше:
9916410: onset−H1 в[−1.267,−0.233]s;
9918413:[−1.500,−0.500]s. Это сравнение двух наблюдений на **том же видео**, без
JSON clock conversion. Геометрия стоп-линии неизвестна; проезд на запрещающий
не утверждается. Подкат/реакция/иная причина независимо не установлены.

Следствие: даже улучшенный RELEASE нельзя считать переключением GREEN либо
обязательной положительной задержкой после него. Universal positive reaction-time
offset/распределение по этим8 машинам не обучали. Исходные независимые наблюдения
не означают, что весь проект невозможен: они задают требования к event roles,
nonexclusive observation model, demand/exposure и UNKNOWN.

## Безопасная часть интеграции выполнена

Новый opt-in `build_localized_evidence_view` подключён к **существующему**
`build_local_evidence`/LocalEvidenceIndex, без нового likelihood. Он:

- переносит доступный localized TemporalEvent в method-specific vehicle channel;
- сохраняет исходные events отдельно как reference, без двойного счёта;
- при неизвестной/отсутствующей локализации сохраняет UNKNOWN и alternatives,
  без скрытого fallback к старому timestamp;
- сохраняет ENTRY/zone channels, track dependence, sampling/provenance и heuristic
  uncertainty; не выводит exposure из отсутствия автомобилей;
- запрещает изменение source/movement/quality и превращение vehicle proxy в
  signal observation; сохраняет запрет implicit timestamp union в legacy likelihood.

На sealed8 outputs построены два query artifacts:4 events/4 vehicle groups каждый,
exposure UNKNOWN, logical/physical UNKNOWN. `.legacy_streams()` возвращает structured
unavailable `METHOD_DEPENDENCE_AND_EVENT_SIGNAL_DELAY_UNMODELLED`, без fabricated K.
Это интеграция **event-контракта**, не переключение HSMM или промышленного default.

Следующий конкретный шаг — использовать этот интерфейс в ограниченной проверке
фазовой observation model с возможностью движения до зелёного, неизвестным спросом
и зависимыми событиями одного ТС. Не повторять calibration тех же машин и не
подставлять universal delay. Для принятия default нужны независимые sessions и
end-to-end K/composition/history metrics; прежние raw19/34, экспертные0/11 и2D.1 FAIL
остались без изменений. Смена приоритетов decoder/likelihood требует отдельного
явного scope; этим заданием paused experiments не возобновлены.

## Проверки и артефакты

76 targeted tests passed2.58s: новый single-scan sampler, missing-aware frozen clock
check, artifact seals/disjointness/видимость регрессии, adapter contracts и существующие
local evidence/restart tests. До source scan прошли33 preflight tests. Нет tuning/retries
ради результата. Code/config/source/output/review hashes, команды/логи, CSV/JSON,
целые8 tracks,21 native proof image, diff и compact ZIP сохранены в
`evidence/restart_multicycle_validation_20261015/`. Main/default/UI не изменены.
