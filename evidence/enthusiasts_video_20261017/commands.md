# New video intake commands

Base8c49850d1c73a311b7d19ad56b95ffd150216d65, canonical audit_checkout, branch
calibration/enthusiasts-video-intake-20261017. Python C:/Python314/python.exe,
ffprobe/ffmpeg from existing WinGet installation. No dependencies installed.

Metadata: ffprobe -v error -show_entries format=duration,start_time,size:stream=codec_name,width,height,r_frame_rate,avg_frame_rate,time_base,start_time,duration,nb_frames -of json -i VIDEO.
Native context: ffmpeg -copyts -ss 0 -i VIDEO -vf showinfo -frames:v 1
-fps_mode passthrough -update 1 OUTPUT.png; likewise for9000/18000s.
First capture lacked -update1 and emitted a sequence-name warning; PNG/PTS
present and verified, later captures use the explicit single-image option.

Source fingerprint read exactly3×1MiB at start/middle/end, not whole6.8GB.
ZIP inventory via ZipFile.infolist. First record per6 entries via existing
_iter_json_records with1MiB limit/entry; stop/close after next(), not entire
archive consumption. Source record timestamps converted explicitly as Unix ms,
not asserted to be camera time. Prefix total720896bytes, full CRC not validated.

plan.json fixes coarse0..180/10s. Native crop=120:130:390:650, no interpolated FPS.
Additional fixed1s grids1..9,51..59,111..119,171..179 and61..79/2s locate image
changes; first dim/blinking crops were inconclusive, not labelled red by absence.
refined_plan.json fixes four2s windows before dense extraction:

```
python -m scripts.video_signal_brackets --video VIDEO --out FRESH_DIR --start 7 --end 9
# Similarly68..70,71..73,108..110.
```

Each refined frames.json contains exact actual ffmpeg command, integer PTS and
PNG hash. First integration ran before extra ffprobe format guard was added;
same source was already probed as2688×1520/90000Hz. The guard changes only input
validation, not extraction/PTS interpretation. No native extraction rerun.
All200 native frames and four sheets visually inspected; selected endpoints/
mixed frames additionally viewed as focused nearest-neighbour grids. Failed
attempts to view sheets before worker completion were subsequently retried
after files existed; no missing evidence was substituted.

Contact sheets: crop/scale(flags=neighbor)/hstack or tile10x5. They do not create
new observations. Native context PNGs moved to .web_runtime (own generated files),
hashes/paths saved; source video untouched. Context JPEGs are illustrative only.
Info.docx text extracted via zip XML for millis paragraphs only; SHA retained.

```
python -m pytest tests/test_video_signal_brackets.py tests/test_video_boundary_evidence.py tests/test_restart_video_review.py tests/test_frame_clock_links.py tests/test_calibration_sample.py tests/test_calibration_bundle.py -q -p no:cacheprovider
python -m pytest tests/test_video_signal_brackets.py -q -p no:cacheprovider
python evidence/enthusiasts_video_20261017/verify.py
```

Own Tee-Object logs normalized UTF16→UTF8 before sealing, no source normalization.
63 PASS plus one new format check; final subset12 PASS, total64 unique. No phase
labels/predictions passed to review; no fitting/decoder/replay/parameter search.
