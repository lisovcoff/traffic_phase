# Field semantics: consumer operations versus producer definitions

No independently identified trajectory producer specification/calibration was supplied or found in the relevant repository code/docs. Old workspace consumers are additional implementation evidence, not supplier specifications. Exact source excerpts and content hashes are in semantic_sources.json.

| Field | Established operation and source | Producer meaning / units |
|---|---|---|
| detections.millis | events.py:550 divides by 1000 to obtain seconds; geometry.py:46 validates integer | Consumer uses milliseconds. Frame synchronization, epoch origin and producer accuracy UNKNOWN. UTC+5 supplied by user is not video synchronization. |
| raw detection/track speed | geometry.py:125 casts track speed without conversion; vehicle_evidence.py:110-113 explicitly avoids dimensional thresholds | Definition (instantaneous/filtered/aggregated), units, calibration and meaning of exact zero UNKNOWN. Track and detection fields must not be assumed equivalent. |
| centroid_x / centroid_y | events.py:545-567 uses Euclidean differences divided by seconds | Relative coordinate motion per second is computed; pixel/normalized units, axis orientation, bounding box/reference point, camera transform UNKNOWN. |
| lat / lng | geometry.py parser checks geographical ranges; haversine_distance_m treats them as degrees | Consumer geographic assumption is established. Supplier projection/accuracy/calibration UNKNOWN; not a verified independent geometry source. |
| line_in / line_out | No timing-extractor use found; old V8 report line 23 claims line_in is an ID | Meaning, units, ID registry and association with physical lines UNKNOWN. Historical claim alone does not verify producer semantics. Never interpret as time or verified stop line. |
| stay_duration_millis | geometry.py:128 divides by 1000 and assigns wait_s; old consumer adds duration to first observation | Consumer interprets milliseconds; producer definition of stationary/dwell interval, threshold and anchor UNKNOWN. Does not prove stop. |
| move_duration_millis | geometry.py:132 divides by 1000 and assigns move_s; old preprocess subtracts from top-level millis | Consumer interprets milliseconds; producer movement threshold, window and anchor UNKNOWN. Subtraction is documented proxy. |
| zone_in/out, detection zone | norm_zone strips underscores; extractor observes categorical transition | Zone polygons, location/camera semantics and relationship to physical stop line UNKNOWN. |
| top-level millis | old preprocess interprets track end and computes virtual-entry proxy | Verified producer endpoint definition UNKNOWN. Detection track end can be measured separately. |

No numerical range was used to assign units. Available code is downstream consumption code. A StopLineProvider interface is not configured, verified recording-6 geometry. No associated original video or producer calibration was found by filename search; archives were not opened for this audit. Independent review remains blocked until the materials listed in the unfilled template are provided.
