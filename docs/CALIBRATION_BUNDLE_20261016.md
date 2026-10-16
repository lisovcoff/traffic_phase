# Критерии приёмки и подготовленный calibration-набор

Base: `5038b7eb0a0eb7ba4ddebaf1376e2b0943b96d8b`.
Ветка: `calibration/acceptance-bundle-20261016`.
Это подготовка данных и критериев, без нового decoder/fitting/оценки predictions.

## Что зафиксировано

Машиночитаемый `config/calibration_acceptance_v1.json` задаёт требования к truth
для K, состава/shared movements, period/order, фазовых границ, аппаратных секций
и hold/shortening. Для point boundaries сохранён прежний допуск±2с и неизменный
evaluator; обязательны matched/truth/predicted counts, precision/recall, matched
MAE/p95, nearest MAE и coverage/UNKNOWN. Интервалы, их ширина/containment и
зависимость от prior оцениваются отдельно. Никаких новых thresholds для модели.

Прежние цели MAE≤1с,p95≤2с,coverage≥80%,known macro-F1≥.90 сохранены именно как
**предложения**, а не выбранная по development данным промышленная SLA. Риск
false GREEN и окончательная SLA остаются незаданными; этот набор не принимает
проект и не смягчает прежний FAIL/gate. Без independent truth знаменатель для
соответствующей точности нулевой, а не условные100% или нулевая ошибка.

## Состав данных

Повторяемая команда: `python -m scripts.prepare_calibration_bundle`.
В `evidence/calibration_bundle_20261016/` сохранены JSON, компактный CSV,
metric eligibility, source/code/output seals и очередь independent review.

| Тип записи | Количество | Семантика |
|---|---:|---|
| Видимое изменение H1 в video PTS | 9 | 7 прежних переходов и2 reference observations A/B; только sampled appearance |
| Начало видимого движения автомобилей | 8 | Старые sampled onset intervals; identity hypothesis сохранена |
| Vehicle RELEASE proxy в JSON millis | 8 | Исходный контракт, timestamps, heuristic confidence, uncertainty и provenance без изменения |
| Операторские интервалы групп | 5 | Уточнённые пользователем записи; не continuous lamp truth |

Все30 записей принадлежат **одному** capture27.02.2025. Initial/A/B не становятся
независимыми calibration/test sessions. Все материалы уже использованы при
разработке. Формальная роль — development/calibration candidate, не untouched holdout.

Сохранено следующее:

- Первый операторский маркер не стал придуманным выключением на границе окна;
  конец каждого интервала не объявлен переключением. Неоднозначная group2
  не размножена в непрерывный YELLOW. A/B/C logical mapping не назначен.
- Изолированное потемнение допсекции остаётся `candidate_blink_cessation_not_certified_final_off`.
  Широкий MAIN_RED_ON_2 bracket не обрезан ради точности.
- Video presentation brackets не названы физическими switch-error intervals.
  Жёлтый не игнорируется при описании источника, но не конвертируется автоматически
  в отдельную логическую фазу всего перекрёстка.
- Кандидат clock origin/delta сохранён как диагностика с явной формулой; ни один
  media bracket не переведён в «истинное JSON-время». Sync certificate отсутствует,
  calibrated uncertainty=null. Frozen-H set B не повышает этот статус.
- Два наблюдения движения до H1 GREEN сохранены как same-video association;
  это не оценка причинной задержки, не нарушение ПДД и не причина отклонения.
  Нет выбранного duration prior и synthetic nuisance parameters.

14 оригинальных endpoint frame files проверены по SHA; для2 H1 refs A/B и8
автомобилей добавлены10 уже существующих derived review images с проверкой их
hash и frame lineage. Эти изображения — crops/contact sheets, не новая
независимая разметка. Исходные frame blobs A/B отдельно не объявлены проверенными.
Никакие видео, trajectory JSON или архивы при сборке не открывались; прочитаны
только ограниченные сохранённые JSON и перечисленные небольшие PNG.

## Пригодность к оценке

`metric_eligibility.json` показывает для каждой недоступной метрики value=null,
eligible observations=0, range=null и причину. Сейчас нельзя независимо оценить
K всего перекрёстка, composition, boundaries в JSON-clock, vehicle localization
в JSON-clock, per-second физические секции или extension episodes. Девять
H1 appearance records доступны для review в video time, не для lamp accuracy.
Ни predictions, ни сравнение ошибок модели сборщику не передаются.

Переиспользован существующий independent-review template. В нём17 source-bound
карточек с доступными frame/crop references: 9 signals и8 vehicle observations.
Independent event, reviewer, interval и uncertainty оставлены пустыми. Выводы
extractor не заполняют truth. Это не просьба повторно размечать те же восемь
машин для настройки алгоритма; это подготовленные утверждения для независимого
подтверждения, если они будут использоваться как calibration ground truth.

31 targeted tests проходят: типы evidence, отсутствие clock promotion и
continuous truth expansion, сохранение proxy provenance/units, immutability,
NaN/zero intervals, несоответствие frame/bracket, duplicates и одинаковые timestamps
разных автомобилей, source/output hashes и blank independent fields.
Inference calls0; core algorithms/defaults, evaluator, historical results и main не менялись.

Следующий содержательный шаг — отдельный calibration-протокол проверки joint
clock/geometry uncertainty и raw movement↔H1 mapping по независимым anchors,
используя эти источники без phase-error alignment. Затем можно заранее определить
bounded observation-model эксперимент. Для конечной validation нужен отдельный
сеанс с независимой truth; текущие данные его не заменяют. 2D.1 остаётся FAIL.
