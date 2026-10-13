# Conservative state and observability contract

The contract separates fitted event activity, anonymous logical phase and a
physical section. `StateEstimate` records estimated_state, level, source,
assumptions, observation_support, abstention_reason, provenance and mode.
`calibrated_lamp_probability` is null; activity occupancy probabilities and
heuristic event/mapping confidence are not lamp probabilities.

Vehicle-event uncertainty is separately serialized as sampling interval and an
unvalidated heuristic localization radius. Its event-to-signal-switch relation
is UNKNOWN. Neither 1.3 nor 3 seconds denotes a lamp-switch error bound.
Missing permission evidence raises typed `EvidenceUnavailable`, preserving
ValueError compatibility and returning UNKNOWN with no fabricated K or schedule.

`model.py` adds a `state_contract` sidecar after inference. Original K, period,
scores, raw and baseline segments remain unchanged. The automatic physical plan
is explicitly an unverified mapping/hardware hypothesis; existing plan catalog
data remain available for configured/simulated use, not lamp truth.

`logical_phase_at` uses seconds relative to schedule_base_timestamp_ms. In
reconstructed mode it reads only raw history segments with half-open intervals.
It never wraps outside that history or fills gaps. Within a segment it returns
the original latent-phase estimate, with local observation support UNKNOWN.
Model history coverage is not camera coverage or observable signal coverage.
Configured/simulated baseline queries may explicitly assume periodic repetition.

`signal_renderer.py` defaults to reconstructed physical UNKNOWN. Vehicle counts,
restart, inferred red/green and an additional-section layout do not identify a
lamp. Explicit mapping and hardware verification are required even for a
direct lamp observation; that observation must have source, support and
provenance. This API trusts such caller-supplied independent attestations; it
does not authenticate external truth. No verified attestations exist for the
three recordings. Unknown mapping, hardware or unidentified state gives a
machine-readable reason. Direct lamp observations, including observed yellow,
are different from fixed-duration modeled transitions.

`V10.signal_state_at` preserves anonymous logical output separately. A heuristic
A/B/C assignment appears only as mapping_candidate in reconstructed mode;
green/red/additional movement lists are empty and physical_section is UNKNOWN.
Configured mode retains the previous catalog behavior with explicit assumptions.
No mapping objective or threshold is changed.

Configured/simulated states may include YELLOW and RED_YELLOW; they are assumed
plan states, not reconstructed measured transitions. API callers that previously
expected unconditional colors must select this mode knowingly. FastAPI, HTML,
the visualizer and legacy estimators were not changed; they must not be used as
independent lamp validation or bypass the conservative core contract.

## Counterexamples and changed expectations

The new tests cover GREEN with no demand, blocked GREEN, indistinguishable
restart under GREEN or permissive RED, turn without verified arrow, history gaps
and out-of-range timestamps, unverified phase mapping, configured transitions,
and movement renaming. They require no numeric observability threshold.

The old renderer test treated four supporting vehicle events as observed GREEN.
The same events can occur with permissive movement or released obstruction:
vehicle support cannot identify the lamp. That expectation is retained only in
explicit configured mode and labelled INFERRED_MODEL. Its modeled yellow also
requires configured mode. The old V10 catalog test expected unconditional
green/arrow lists from an optimized anonymous mapping: an unverified turn need
not have an arrow. That test now requests configured mode; reconstructed-mode
abstention is checked separately. Physical-plan catalog tests are unchanged.

## Validation boundaries

Only targeted contract/renderer/semantic/temporal tests are run. Frozen predictions
from the same three recordings are postprocessed without inference. Full schedule,
selection and period dictionaries are compared exactly; input files remain
unchanged. The report records model history coverage and 100% physical abstention
on covered time independently. Hardware section count is unknown, so that
percentage describes the result policy, not measured per-lamp accuracy.

The evidence package includes the base SHA, protected source hashes, prediction
hashes, diff, test output and contract checks. No phase annotations, raw trajectory
records, fitting, benchmark or parameter search are needed. Independent event and
lamp validation and the missing `Инфо.docx` remain outstanding.
