# Проверка clock/geometry и H1 vehicle associations

Base: `d4be0f1dbff24003cdb88ad9794f413777940930`.
Ветка: `calibration/clock-observation-check-20261016`.
Протокол фиксируется до запуска нового checker. Старые наблюдения и два
vehicle-onset-before-H1 примера уже известны: это development diagnostics,
не пререгистрация независимого эксперимента и не новая validation.

## Неизменные входы и расчёты

Использовать только sealed H1 confirmation, saved local model/registration
result и calibration bundle, а также user clock provenance. Не читать большие
JSON, MP4/PNG/ZIP и phase labels; operator phase intervals из bundle не передавать
расчётам. Не вызывать optimizer, event extractor, inference, evaluator или decoder.

1. Сопоставить три overlay readouts с прежним clock candidate. Для проверки
   арифметики рассмотреть **обе**, без выбора лучшей, условные модели display:
   floor с residual `[0,1)` с и nearest с residual `[-0.5,0.5)` с. Условные
   предположения: supplied UTC+5, один и тот же момент camera timestamp и JSON
   detection, отсутствие overlay/processing latency, единичный clock scale.
   Они НЕ подтверждены ответом «Из часов камеры». При неизвестном механизме
   display/latency численный calibrated clock interval не выдавать.
2. Для каждой display-модели вывести допустимый constant-delta set и пересечение
   с ранее сохранённым frozen-H/50px set. Пустое пересечение — несовместимость
   **совокупности** предположений, не доказанная причина ошибки часов, координат
   или identity. Параметры, homography и allowances не менять; не выбирать delta.
   Drift не оценивать по четырём секундам; min singular value/rank брать из
   старого fit только как диагностические свойства, не calibrated uncertainty.
3. Перенести все четыре ранее проверенных geometry anchor и их support, без
   переоценки/отбора. Установленные локальные residuals не подтверждают units,
   centroid semantics, стоп-линию или calibration joint geometry/clock error.
4. Для всех восьми video-motion records A/B сопоставить ровно один H1 appearance
   того же capture/window, не nearest-подбор. Вывести разность интервалов
   `[vehicle_lo-H1_hi, vehicle_hi-H1_lo]`, counts и временной extent. Если
   association отсутствует/неоднозначна — explicit unavailable. Proxy ID/method/
   sampling interval допустимы как provenance, но не переносятся в video time.
   Никакого delay fit, допуска, positive-only отбора или исправления extractor.

## Критерии и лимиты

- Проверяемый результат: source/protocol/code/output hashes, каждый из 8 records
  сохранён, все 3 clocks и 4 geometry anchors учтены; UNKNOWN и причины явные.
- Оба условных clock result публикуются рядом, вне зависимости от результата.
  Никакого gate «добиться совместимости» и никакой настройки после расчёта.
- Vehicle association — sampled video appearance, не calibrated onset или
  lamp switch interval; до/после не означает нарушение/реакцию/причину.
- Один checker run, до 10 с, не более 2 MiB входных JSON, каждый до 512 KiB;
  ограничение количества readouts/anchors/records — 100/100/1000. При превышении
  явная ошибка, результаты не повышаются до usable. Никаких тяжёлых запусков.
- Все исходные predictions, модели и sealed evidence неизменны. Main/default,
  2D.1 FAIL, исторические K3/2/3 и raw19/34 сохраняются. Physical states UNKNOWN.

После этого достаточно либо назвать условия допуска observation calibration,
либо конкретные недостающие данные. Новый decoder не входит в этот шаг.
