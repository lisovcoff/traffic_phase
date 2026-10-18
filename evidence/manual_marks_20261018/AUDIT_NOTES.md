# Evidence notes

The first browser harness failed because it expected arrow objects while the
viewer debug API exports strings such as `N->E=GREEN`. The corrected harness
then exposed a real seek defect: inherited button padding caused short timeline
segments to overlap. That failure and screenshots are preserved under
`browser_corrected.txt` and `browser_verified/`. Padding was removed; fresh
viewers and a fresh isolated Edge run pass under `browser_final/`.

`viewer_sources.json` records SHA-256 of the UTF-8 **render string with LF** in
`page_sha256`; Windows text output translated LF to CRLF on disk in this run.
Consequently those fields are not the SHA-256 of the saved Windows files.
`delivered_viewers.json` contains the authoritative byte hashes and sizes of
the actual delivered files, which are exact copies of the browser-tested files.
The rebuild script was corrected to hash file bytes for future builds.
Original manifests are preserved; no predictions were regenerated or shifted.

`SHA256.json` seals the initial evidence files, excluding itself and this
subsequent clarification. `SHA256_final.json` seals all final files except
itself, including that original manifest and this note.
