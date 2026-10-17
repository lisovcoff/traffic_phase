# Bounded review reproduction

Working directory: canonical `audit_checkout`; Python via `py -3`, existing
ffmpeg/ffprobe and installed matplotlib/Pillow. No dependency installation.
All extraction scripts require fresh output/cache paths; do not rerun them over
this preserved evidence. Read-only `verify.py` is safe to repeat.

Initial plan committed to disk before scan. `inspect_entry.py` reads only
`6_2025_2_23_13.json` once (13,542,804 bytes, ZIP CRC and raw SHA256); caches full
raw member locally. `geometry_preview.py` uses that cache and the old native
start context, with NO inferred transformation or simultaneous-start claim.

```
py -3 evidence/enthusiasts_vehicle_link_20261018/inspect_entry.py
py -3 evidence/enthusiasts_vehicle_link_20261018/geometry_preview.py
py -3 evidence/enthusiasts_vehicle_link_20261018/sample_context.py
py -3 evidence/enthusiasts_vehicle_link_20261018/sample_coarse.py
py -3 evidence/enthusiasts_vehicle_link_20261018/sample_refinement.py
```

Exact ffmpeg argument arrays are saved per frame in context/coarse/refinement
JSON. Each call uses -copyts/-ss/showinfo, actual integer native PTS, no fps
filter/interpolation, 20s subprocess timeout. Coarse scale/JPEG is explicitly a
search aid, not a native timing/localization measurement. Decode wall75.234s.

User directed full Info.docx review. Read-only .NET ZipFile + XML extraction:
`word/document.xml` paragraphs, `word/_rels/document.xml.rels` external links,
and raw `word/media/image1.jpg`. The embedded image was visually inspected;
it is the other-intersection compass-zone example. No DOCX authoring or edit.

Web reader could not access the public share. Direct read-only public API:

```
GET https://cloud-api.yandex.net/v1/disk/public/resources?public_key=https%3A%2F%2Fdisk.yandex.ru%2Fi%2FNwMsnq7xcOIn0A
```

Only whitelisted public metadata fields saved, no signed download URL/account
details. Following the separate source_identity_plan, full local media SHA256
and MD5 computed once; no remote video download, no full video decode:

```
py -3 evidence/enthusiasts_vehicle_link_20261018/verify_source_identity.py
py -3 evidence/enthusiasts_vehicle_link_20261018/prepare_review_result.py
py -3 -m scripts.check_frame_clock_links --input evidence/enthusiasts_vehicle_link_20261018/frame_clock_links_template.json --out evidence/enthusiasts_vehicle_link_20261018/frame_clock_check.json
```

The final prep copies the existing frame-link schema, preserving empty rows.
Bus records copied unmodified from local cache, canonical raw hashes saved;
producer lookup examples are car detections, not guessed video timestamps.

```
py -3 -m pytest tests/test_frame_clock_links.py tests/test_vehicle_clock_alignment.py tests/test_video_signal_brackets.py tests/test_calibration_sample.py -q -p no:cacheprovider
py -3 evidence/enthusiasts_video_20261017/verify.py
py -3 evidence/enthusiasts_vehicle_link_20261018/verify.py --seal
py -3 evidence/enthusiasts_vehicle_link_20261018/verify.py
git diff --check
```

45 existing tests passed; prior 200 native frames/four appearance brackets and
protected source/main verified. Earlier recovery attempts emitted a few read-only
missing-path/rg errors before resolving actual paths; no data was substituted.
No fitting, predictions, decoder, clock solve, phase alignment, production or
historical evidence edits, deletes, or rollbacks. Local supplier request NOT sent.
