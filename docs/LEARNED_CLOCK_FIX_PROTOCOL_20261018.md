# Learned profile time-grid correction

Initial chronological holdout:12/13 matches,16 predictions versus baseline7/13,
17 predictions. This result remains preserved; no refitting/tuning of models.
Independent uniform-density/no-information120s-cycle test fails: a fixed100-state
MAP clock chooses1bin/s and produces100s cycles rather than120s.

Correct numerical time grid to round(period_s) states and interpolate the
unchanged learned100-bin density/onsets. No change to learned profiles, labels,
penalty sd0.5, data selection, period, heldout cut or evaluation. First verify
the independent clock test, then one corrected prediction on each of the3
unchanged saved models (120s/file,360s total). Seal predictions before scoring.
Preserve original models/predictions/evaluation. Compare identical heldout windows.
Ordinal fields on heldout subset are projected to canonical timestamp/kind for
the unchanged validator; no timestamp/label/tolerance is changed.
