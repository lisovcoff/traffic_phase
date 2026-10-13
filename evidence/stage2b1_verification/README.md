# Проверка и диагностика 2B.1

Это bounded evidence package, без нового полного benchmark, настройки параметров
или перехода к 2B.2. Внутри `stage2b1_evidence.zip` (~1MB) находятся исходные
baseline_metrics/comparison, **полные predictions как файлы**, code snapshots,
diff, логи, selection manifest, восемь сырых треков и профиль. JSON не вставлены
в этот отчёт. `archive_sha256.json` проверяет ZIP; `manifest.json` — его компоненты.
Предыдущие predictions также доступны в `../../benchmarks/stage2b1_20261013/predictions/`.
Архив сохраняет точные run bytes.

## Версии и проверки неизменности

Цепочка коммитов (прямые родители):

```text
aa2c4a35862fe666db7c76b7b238dcdcaf00f3c0  2A artifacts
  -> 161f32fd42ce80cca01bb74c0a00988d6969382a  2B.1 producer
  -> afcfaa2b38e106201d7e819570425acfc4c5487f  2B.1 results
  -> 1207344bdcbc46edbf19bace65382ee0252d1f4d  uncertainty/abstention clarification
```

Main локально и в origin проверен как
`a005a2521f62ce3b2c9f9d52f9f0d73913754e01`; не изменён.
Commit сохранения evidence package следует после измеренного кода 1207344;
пакет фиксирует snapshot, не претендует знать собственный будущий commit SHA.

`producer_code.diff` — полный diff затронутых source/comparer/tests относительно
aa2c4a3 до 161f32f; `producer_source/` содержит точные Git blobs этой версии.
`changed_paths.txt` содержит все изменения aa2c4a3→afcfaa2, включая artifacts.
`implementation_without_prediction_json.diff` покрывает весь diff этих версий,
кроме трёх больших prediction JSON: сами JSON включены в ZIP отдельными файлами.
`contract_clarification.diff` — небольшая отдельная metadata/exception поправка.

Byte equality Git blobs подтверждена для evaluator/CLI, decoder, fit/K,
primitives/infer_period и V10 mapping между aa2c4a3, 161f32f и проверенным HEAD.
AST baseline/deviation/image solver в изменённом events.py идентичен исходному.
Production code между 161f32f и afcfaa2 идентичен. Source и annotation raw SHA256
для трёх записей проверены против файлов диска (только digest, без чтения labels
диагностическим worker); config одинаков:
`c1ca38484ba0033703cb44e49dcdb15d918345df3f9e909f2a59f2975cfab383`, ±2s.
Полные hashes находятся в manifest.

**Обнаружено отдельное ограничение воспроизводимости старых artifacts:**
Windows `write_text()` создал CRLF, а Git сохранил LF. Report raw hashes точно
совпадают с сохранёнными run files, но не с Git blob SHA256. Например before
baseline_metrics raw SHA `bafcb9955ea7388d2b0e5f9935115cad0bfaf404255d8c1e639b31e1bf603d41`,
Git LF blob SHA `82e476282afb8d1b3417c71cbaae30aa2377e8b8f13c0a7f63cc463f4fd81228`.
Отличие только newline; JSON и нормализованные bytes идентичны. Manifest показывает
оба digest, без ложного утверждения byte equality. Старые файлы/evaluator не
переписаны. ZIP binary сохраняет original CRLF bytes; новые evidence файлы
защищены от EOL normalization в `.gitattributes`. Fresh LF checkout исходных
benchmark JSON не проходит исторические raw-hash проверки без такого пакета.

## Команды и реальные логи

Оригинальный stdout прошлой сессии не был сохранён в репозитории. Вместо
выдуманных исторических логов выполнен **verification rerun** исходного
production кода afcfaa2 (идентичен 161f32f) до contract patch:

* `python -m scripts.verify_stage2b1 tests`: `logs/unit72.log` — **72 passed**,
  `logs/regression56.log` — **56 passed**. Полные команды, Python, SHA и exit codes
  в `logs/commands.json`; фактические времена 2,48 и 84,55s.
* Contract clarification: `logs/contract45.log` — **45 passed**, 2,14s.
  Полная команда в `logs/contract45_command.json`. Это пять новых target cases
  плюс прежние vehicle/offline tests, а не ещё 45 новых сценариев.

Диагностические команды:

```powershell
python -m scripts.verify_stage2b1 select
python -m scripts.verify_stage2b1 analyze
python -m scripts.verify_stage2b1 profile
python -m scripts.verify_stage2b1 contract
python -m scripts.package_stage2b1_evidence
```

Worker открывает только сохранённые predictions и trajectory JSON. Он не
использует evaluator, annotation paths, phase marks и не вызывает phase fitting.
Packager отдельно сверяет
report integrity metadata, не передавая их worker/модели. Sample manifest записан
до анализа треков и оценки candidate diagnostics; `record6_diagnostics.json`
ссылается на его SHA256. Заранее известный общий K regression не использовался
в выборе track IDs. Фазовые ошибки/метки не являются критерием выборки.

## Uncertainty и отсутствие evidence

Старый temporal_uncertainty_ms в 161f32f имел общий name и heuristic 1,3/3s.
Это **не calibrated CI и не интервал ошибки включения лампы**. Уточнённая
serialization сохраняет этот alias, но добавляет явные независимые компоненты:
sampling bracket/width, unvalidated vehicle-localization radius и
`event_to_signal_switch.status=UNKNOWN, uncertainty_ms=null`.
Исходные measurements/timestamps/thresholds/selection не меняются.

`uncertainty_and_unknown.json` показывает representative selected RELEASE и
CROSSING_PROXY с original provenance, prediction SHA и точным selected_event_index,
а рядом — clarified serialization. CROSSING_PROXY действительно selected в
записи 17; в записи 6 selected proxies отсутствуют, выбраны RELEASE. Нельзя
называть arbitrary crossing proxy из 6 «selected».

Отсутствие permission теперь даёт `EvidenceUnavailable(ValueError)` с
`reason_code=NO_PERMISSION_EVIDENCE`, `status=unavailable`, `state=UNKNOWN`,
`phase_count=null`, `schedule=null`. Нет K/phase fitting (проверено запрещающим
spy). Empty demand имеет отдельный code. Это backward-compatible exception,
которую library consumer может сохранить через `to_dict()`. Неизменённый
offline CLI всё ещё классифицирует исключение как inference_failed; structured
exception не следует выдавать за новую успешную prediction/изменение evaluator.

## Локализация K2→K3 на записи 6

Нет нового phase fitting: ниже saved diagnostics и streaming диагностика
**только записи 6**, чтобы восстановить legacy per-movement counts/ranges.
Проход повторён для дополнения legacy selected-method counters; результаты
phase model не пересчитывались, manifest выборки не менялся.
Никакие ZIP не читались. Результат в `record6_diagnostics.json`.

| Movement | Legacy selected RELEASE | New selected RELEASE |
| --- | --- | --- |
| E->N | 4 | 7 |
| E->S | 145 | 145 |
| E->W | 8 | 26 |
| N->E | 33 | 31 |
| N->S | 216 | 204 |
| N->W | 86 | 85 |
| S->N | 0 | 1 |
| S->W | 16 | 18 |
| W->E | 405 | 386 |
| W->N | 165 | 155 |
| W->S | 48 | 49 |

Legacy gate этой записи выбирал release-only: **здесь K regression не вызван
глобальным fallback на entry**. Было 1126 release/10 непустых permission streams;
стало 1107/11. В новой версии все selected RELEASE — image-space proxies,
metadata dwell был отвергнут. Есть изменения времени/состава кандидатов, а не
только удаление 19 событий. Их диапазоны/methods и main counts сохранены в JSON.
Отдельное различие call-site: старый image solver ограничивался первым
outgoing-zone observation, новый — track end. Stop/restart support/cleanup
guards также меняются, хотя сам solver и phase model сохранены.

| Version | K2 selection score | K3 selection score | K3−K2 |
| --- | --- | --- | --- |
| Before | 7575,747982 | 7583,755569 | +8,007587 (K2 выигрывает) |
| After | 7716,181510 | 7676,898412 | −39,283098 (K3 выигрывает) |

Внутриверсионный objective перевернулся; абсолютные scores между версиями
не сопоставимы как log-likelihood на одном dataset (evidence/dimension изменены).
Проверяемые гипотезы: новый sparse S->N меняет размерность occupancy/emissions;
рост E->W 8→26 и изменения timestamps меняют профили; расширение candidate span
до track end допускает дополнительные acceleration episodes. Без отдельно
предобъявленной абляции невозможно приписать K regression одному фактору.
Абляции/правила по фазовой разметке здесь не подбирались.

## Восемь фиксированных треков

Выбор: первые четыре fingerprint lexicographic в каждой группе sign(delta),
где delta = RELEASE−observed zone transition; только выбранные моделью RELEASE.
Population: 552 after и 555 before/at; sample: 4+4. Raw выбранные треки лежат в
`tracks/`. Manifest фиксирует IDs/fingerprints/indices/исходный prediction hash.

After IDs: **4637850, 4636198, 4637003, 4632228**, delta соответственно
17,034 / 5,998 / 11,280 / 0,381s. На ближайшей detection зона unnamed (None);
outgoing zone наблюдается позже. Поэтому «после зоны» не означает «после
стоп-линии», red violation или ДТП. Existing first-outgoing и track-end image
solver на этих восьми треках дали одинаковый candidate: span difference не
объясняет именно эту sample, хотя остаётся гипотезой для остальных records.

Control IDs: **4633111, 4635538, 4634400, 4632215**, delta −1,315 / −4,684 /
−0,118 / −0,814s. У 4635538 candidate ещё раньше первой incoming-zone detection
примерно на 0,479s, в unnamed зоне. И старый, и новый image solver это допускают:
кандидат не обязательно пространственно локализован в incoming zone.

У четырёх из восьми median raw speed перед candidate составляет приблизительно
15 / 28 / 32 / 21 неизвестных units и затем растёт. Это поддержка acceleration,
а не независимо доказанной остановки. STOP не выдаётся. В других sample raw speed
низка, но нулевая скорость/остановка также не подтверждена независимо.
Centroids находятся в диапазоне 0..1; lat/lng выглядят географически допустимыми.
Это наблюдение формата, **не подтверждение units/calibration/метрической точности**.
В доступных materials нет независимых stop/restart descriptions и line geometry.
Нельзя отличить permissive turn/очередь/внутреннюю блокировку по одному restart.

## Малый профиль, отдельно от общего runtime

Фиксированный input: **8 tracks / 1001 detections / 24 events**, hashes raw files
в `small_input_profile.json`. Parsing/IO/fitting исключены, warmup=1, measured
repeats=5; median perf_counter, включая overhead instrumentation.

| Компонент | Median, ms |
| --- | --- |
| Sanitization | 13,202 |
| Fingerprinting | 8,779 |
| Extraction exclusive | 8,755 |
| Extraction inclusive (сумма первых трёх) | 30,551 |
| to_dict serialization | 0,249 |
| JSON encoding | 0,258 |

На этой sample sanitization/fingerprint доминируют над serialization; это не
доказательство причин общего runtime ×1,78 или extrapolation на большие архивы.
Profile измерен с clarified serialization; historical prediction timing не
пересчитан. Отдельно хранится 5 repeats, serialized size и code digest.

## Рекомендация и остановка

Следующий отдельный эксперимент: независимо описанные остановки/ускорения с
проверенными coordinate/speed units и относительным положением vehicle events,
затем predeclared абляция влияния sparse stream/extra candidates. Не называть
low-speed run остановкой и не ставить input-zone restriction как stop-line
правило без geometry. Для portable artifacts заранее определить canonical bytes
или binary retention и hashes, сохраняя исходные run files.

В этом задании только diagnostics, уточнение metadata uncertainty и structured
abstention. HSMM/K/period/baseline/mapping, thresholds, offset, ±2s tolerance,
evaluator и baseline artifacts не изменены; новый full benchmark отсутствует.
К 2B.2 не переходили.
