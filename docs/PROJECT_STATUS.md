# Project status — 2B.2, 2026-10-13

Stages 1 and 2A are accepted as audit/planning and a reproducible offline baseline.
Stage 2B.1 is accepted as an engineering improvement in temporal evidence,
provenance and per-stream selection. Its event timing and lamp semantics have
not been independently validated. Accepted A–D and event-level recording-6
diagnostics are preserved; they were not repeated for 2B.2.

2B.2 adds conservative result semantics and abstention; it does not improve or
retrain phase discovery. Physical UNKNOWN is reported separately from model
history coverage. External vehicle-event and lamp validation remain open.
Known regressions (including recording 6 K 2→3 and degraded boundary results
after changed evidence ingestion) remain in the unchanged
`benchmarks/stage2b1_20261013/comparison.json`. No parameters were selected to
repair these results.

Production base: `afcfaa2b38e106201d7e819570425acfc4c5487f`.
Only uncertainty/structured-abstention code and its tests were taken from
`1207344bdcbc46edbf19bace65382ee0252d1f4d`; diagnostic runners/artifacts were
not used as the production base. Main remains unchanged.

Top-level `millis`: the historical consumer interprets it as a track-end anchor
for `millis - move_duration_millis`. This is a consumer assumption, not a verified
supplier definition or a measured crossing timestamp. `Инфо.docx` was not found
in the available workspace files or archive directories (only ZIP metadata was
inspected). Its exact description cannot be cited or substituted with a guess.
Provide that document to resolve the producer definition. Even a documented
definition would not establish camera/controller clock synchronization.
