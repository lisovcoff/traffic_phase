from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean

from app.core.event_cycle_estimator import estimate_event_cycle
from app.core.event_phase_discovery import EventPhaseDiscovery
from app.core.preprocessing import load_trajectory_file
from app.core.reconstruction import extract_events_from_trajectories
from app.core.signal_group_mapping import build_signal_group_model


def _load_trajectories(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        for key in ("trajectories", "data", "items", "tracks", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                items = value
                break
        else:
            raise ValueError(
                "JSON object does not contain a trajectory list "
                "(expected trajectories/data/items/tracks/results)"
            )
    else:
        raise ValueError("trajectory JSON must be a list or object")

    return [
        item
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("detections"), list)
    ]


def _build_stage_analysis(path: Path) -> dict[str, object]:
    """Run the authoritative Stage 1/2 pipeline for the viewer."""
    trajectories = load_trajectory_file(path)
    events = extract_events_from_trajectories(trajectories)
    cycle = estimate_event_cycle(events).estimate
    phase_model = EventPhaseDiscovery(bin_seconds=2.0).discover(
        events,
        cycle_seconds=cycle.cycle_seconds,
    )
    stage2 = build_signal_group_model(
        events,
        cycle_seconds=cycle.cycle_seconds,
        origin_timestamp_ms=phase_model.origin_timestamp_ms,
        bin_seconds=1.0,
    )
    phase_confidence = (
        sum(phase.confidence for phase in phase_model.phases)
        / len(phase_model.phases)
        if phase_model.phases
        else 0.0
    )
    return {
        "stage1": {
            "cycle_seconds": float(cycle.cycle_seconds),
            "cycle_confidence": float(cycle.confidence),
            "origin_timestamp_ms": int(phase_model.origin_timestamp_ms),
            "phase_confidence": float(phase_confidence),
            "phases": [
                phase.to_dict() for phase in phase_model.phases
            ],
        },
        "stage2": {
            "cycle_seconds": float(stage2.cycle_seconds),
            "origin_timestamp_ms": int(stage2.origin_timestamp_ms),
            "signatures_count": len(stage2.signatures),
            "groups": [
                group.to_dict()
                for group in stage2.discovery.groups
            ],
            "relations": [
                relation.to_dict()
                for relation in stage2.discovery.relations
            ],
            "insufficient_movements": list(
                stage2.discovery.insufficient_movements
            ),
            "mapping": stage2.mapping.to_dict(),
        },
    }


def _escape_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")


def _prepare_tracks(
    trajectories: list[dict],
) -> tuple[list[dict], dict[str, tuple[float, float]], int, int]:
    tracks: list[dict] = []
    zone_points: dict[str, list[tuple[float, float]]] = {}

    min_ms: int | None = None
    max_ms: int | None = None

    for index, trajectory in enumerate(trajectories):
        detections: list[list[object]] = []
        for detection in trajectory.get("detections", []):
            if not isinstance(detection, dict):
                continue
            timestamp = detection.get("millis")
            x = detection.get("centroid_x")
            y = detection.get("centroid_y")
            if not isinstance(timestamp, (int, float)):
                continue
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                continue
            timestamp = int(timestamp)
            x = float(x)
            y = float(y)

            zone = detection.get("zone")
            zone = zone if isinstance(zone, str) and zone else None
            detections.append([
                timestamp,
                round(x, 5),
                round(y, 5),
                zone,
            ])

            if zone in {"N", "S", "E", "W"}:
                zone_points.setdefault(zone, []).append((x, y))

            min_ms = timestamp if min_ms is None else min(min_ms, timestamp)
            max_ms = timestamp if max_ms is None else max(max_ms, timestamp)

        if not detections:
            continue

        detections.sort(key=lambda item: int(item[0]))
        tracks.append({
            "id": trajectory.get("id", index),
            "in": trajectory.get("zone_in"),
            "out": trajectory.get("zone_out"),
            "points": detections,
        })

    zone_centers = {
        zone: (
            mean(point[0] for point in points),
            mean(point[1] for point in points),
        )
        for zone, points in zone_points.items()
        if points
    }

    if min_ms is None or max_ms is None:
        raise ValueError("no usable detections with millis/centroid coordinates")

    return tracks, zone_centers, min_ms, max_ms


HTML_TEMPLATE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Traffic trajectory coordinate viewer</title>
<style>
  body { margin:0; font-family:system-ui,-apple-system,Segoe UI,sans-serif; background:#f4f4f4; color:#111; }
  .wrap { max-width:1200px; margin:20px auto; padding:0 16px 24px; }
  h1 { margin:0 0 8px; font-size:22px; }
  .sub { margin:0 0 14px; color:#555; font-size:14px; }
  .toolbar { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:12px; }
  button { padding:7px 11px; border:1px solid #aaa; border-radius:6px; background:white; cursor:pointer; }
  button:hover { background:#eee; }
  input[type=range] { width:100%; }
  .time { font-variant-numeric:tabular-nums; font-size:15px; margin:7px 0; }
  .panel { background:white; border:1px solid #ccc; border-radius:8px; padding:10px; }
  canvas { display:block; width:100%; height:auto; background:#fff; border:1px solid #aaa; }
  .legend { margin-top:8px; display:flex; gap:14px; flex-wrap:wrap; font-size:13px; }
  .stats { margin-top:8px; font-size:13px; color:#444; }
  .canvas-wrap { position:relative; }
  .stage-overlay { position:absolute; top:12px; left:12px; z-index:5; padding:8px 11px; background:rgba(255,255,255,.94); border:1px solid #999; border-radius:7px; box-shadow:0 2px 8px rgba(0,0,0,.12); font-size:16px; font-weight:700; pointer-events:none; max-width:70%; }
  .stage-overlay .stage-title { font-size:11px; font-weight:600; color:#666; margin-bottom:2px; text-transform:uppercase; }
  .stage-overlay .stage-movements { font-variant-numeric:tabular-nums; }
  label { font-size:13px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Визуализация траекторий Ленинский × Свердловский</h1>
  <p class="sub">Точки берутся напрямую из centroid_x / centroid_y исходного JSON. Это просмотр кинематики, а не распознавание цвета светофора.</p>

  <div class="panel">
    <div class="toolbar">
      <button id="play">▶ Пуск</button>
      <button id="back10">−10 с</button>
      <button id="back1">−1 с</button>
      <button id="forward1">+1 с</button>
      <button id="forward10">+10 с</button>
      <button id="markEW">Метка EW</button>
      <button id="markNS">Метка NS</button>
      <button id="markNArrow">Метка N+доп</button>
      <button id="downloadMarks">Скачать метки</button>
      <button id="clearMarks">Очистить метки</button>
      <label><input id="showIds" type="checkbox"> ID</label>
      <label><input id="showMoves" type="checkbox" checked> движение</label>
    </div>
    <input id="timeline" type="range" min="0" max="1" step="0.5" value="0">
    <div class="time" id="time"></div>
    <div class="canvas-wrap">
      <canvas id="view" width="1200" height="760"></canvas>
      <div class="stage-overlay" id="stageOverlay">
        <div class="stage-title">Сейчас</div>
        <div class="stage-movements">Не определено</div>
      </div>
    </div>
    <div class="stats" id="stats"></div>
    <pre class="stats" id="marks"></pre>
    <div class="legend">Слева сверху показано, для каких направлений текущая зелёная фаза восстановлена по траекториям.</div>
  </div>
</div>

<script>
const DATA = __DATA__;
const START_MS = DATA.start_ms;
const END_MS = DATA.end_ms;
const STEP_MS = DATA.step_ms;
const STALE_MS = DATA.stale_ms;
const tracks = DATA.tracks;
const zones = DATA.zones;

const canvas = document.getElementById("view");
const ctx = canvas.getContext("2d");
const timeline = document.getElementById("timeline");
const timeEl = document.getElementById("time");
const statsEl = document.getElementById("stats");
const playButton = document.getElementById("play");
const showIds = document.getElementById("showIds");
const showMoves = document.getElementById("showMoves");
const marksEl = document.getElementById("marks");
const stageOverlayEl = document.getElementById("stageOverlay");
const stageOverlayMovementsEl = stageOverlayEl.querySelector(".stage-movements");
const stage1 = DATA.stage1 || null;
const stage2 = DATA.stage2 || null;

timeline.min = 0;
timeline.max = Math.max(0, END_MS - START_MS);

let currentMs = START_MS;
let playing = false;
let timer = null;
let playStepMs = 500;
const marks = [];

function formatLocal(ms) {

  const d = new Date(ms);
  return d.toLocaleString("ru-RU", {
    timeZone: "Asia/Yekaterinburg",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }) + "." + String(d.getMilliseconds()).padStart(3, "0");
}

function binaryLatest(points, t) {
  let lo = 0, hi = points.length - 1, best = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (points[mid][0] <= t) {
      best = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return best;
}

function activeAt(track, t) {
  const i = binaryLatest(track.points, t);
  if (i < 0) return null;
  const point = track.points[i];
  if (t - point[0] > STALE_MS) return null;
  return point;
}

function xPx(x) { return x * canvas.width; }
function yPx(y) { return y * canvas.height; }

function drawGrid() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  ctx.strokeStyle = "#ddd";
  ctx.lineWidth = 1;
  for (let i = 1; i < 10; i++) {
    const x = canvas.width * i / 10;
    const y = canvas.height * i / 10;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
  }

  ctx.strokeStyle = "#888";
  ctx.lineWidth = 2;
  ctx.strokeRect(0, 0, canvas.width, canvas.height);
}

function drawZoneLabels() {
  ctx.font = "700 34px system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";

  for (const zone of ["N","S","E","W"]) {
    const center = zones[zone];
    if (!center) continue;
    const x = xPx(center[0]);
    const y = yPx(center[1]);
    ctx.fillStyle = "#fff";
    ctx.strokeStyle = "#111";
    ctx.lineWidth = 3;
    ctx.strokeText(zone, x, y);
    ctx.fillText(zone, x, y);
  }
}

function drawVehicles(t) {
  let active = 0;
  let zoneCounts = {N:0,S:0,E:0,W:0,none:0};

  for (const track of tracks) {
    const p = activeAt(track, t);
    if (!p) continue;

    active++;
    const zone = p[3];
    if (zoneCounts[zone] !== undefined) zoneCounts[zone]++;
    else zoneCounts.none++;

    const x = xPx(p[1]);
    const y = yPx(p[2]);

    ctx.fillStyle = "#111";
    ctx.beginPath();
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.fill();

    if (showIds.checked || showMoves.checked) {
      let text = "";
      if (showIds.checked) text += String(track.id);
      if (showIds.checked && showMoves.checked) text += " ";
      if (showMoves.checked && track.in && track.out) {
        text += String(track.in) + "→" + String(track.out);
        if (track.movement && stage2 && stage2.mapping && stage2.mapping.movement_to_group) {
          const groupId = stage2.mapping.movement_to_group[track.movement];
          if (groupId) text += " [" + groupId + "]";
        }
      }
      if (text) {
        ctx.font = "11px system-ui, sans-serif";
        ctx.textAlign = "left";
        ctx.textBaseline = "bottom";
        ctx.fillStyle = "#111";
        ctx.fillText(text, x + 7, y - 3);
      }
    }
  }

  return {active, zoneCounts};
}


function containsPhase(start, end, phase, cycle) {
  start = Number(start);
  end = Number(end);
  phase = Number(phase);
  cycle = Number(cycle);
  if (start === end) return true;
  if (start < end) return start <= phase && phase < end;
  return phase >= start || phase < end;
}

function renderStageOverlay(currentTimeMs) {
  if (!stage1) {
    stageOverlayMovementsEl.textContent = "Не определено";
    return;
  }

  const anchor = stage1.origin_timestamp_ms || START_MS;
  const cycle = Number(stage1.cycle_seconds) || 1;
  const cyclePosition = ((currentTimeMs - anchor) / 1000) % cycle;
  const normalized = (cyclePosition + cycle) % cycle;

  const activePhase = (stage1.phases || []).find(phase =>
    containsPhase(
      phase.phase_start,
      phase.phase_end,
      normalized,
      cycle,
    )
  );

  if (!activePhase || !(activePhase.active_approaches || []).length) {
    stageOverlayMovementsEl.textContent = "Не определено";
    return;
  }

  const activeApproaches = new Set(activePhase.active_approaches);
  const movements = [...new Set(
    ((stage2 && stage2.signatures) || [])
      .filter(signature => {
        if (!activeApproaches.has(signature.approach)) return false;
        return (signature.active_intervals || []).some(interval =>
          containsPhase(
            interval.start,
            interval.end,
            normalized,
            cycle,
          )
        );
      })
      .map(signature => signature.movement)
      .filter(movement =>
        typeof movement === "string" &&
        movement.includes("->") &&
        !movement.endsWith("->UNKNOWN")
      )
  )].sort();

  if (movements.length) {
    stageOverlayMovementsEl.textContent =
      "Зелёный: " + movements.join(", ");
    return;
  }

  stageOverlayMovementsEl.textContent =
    "Зелёный: " + [...activeApproaches]
      .sort()
      .map(approach => approach + "→*")
      .join(", ");
}

function render() {
  const t = currentMs;
  drawGrid();
  drawZoneLabels();
  const result = drawVehicles(t);

  timeline.value = t - START_MS;
  timeEl.textContent =
    formatLocal(t) + "   |   +" + ((t - START_MS) / 1000).toFixed(1) + " c";

  const z = result.zoneCounts;
  statsEl.textContent =
    "Активных траекторий: " + result.active +
    " | N: " + z.N +
    " | S: " + z.S +
    " | E: " + z.E +
    " | W: " + z.W +
    " | zone=null: " + z.none;

  renderStageOverlay(t);
}

function setTime(ms) {
  currentMs = Math.min(END_MS, Math.max(START_MS, ms));
  render();
}

function addMark(kind) {
  marks.push({
    kind,
    timestamp_ms: currentMs,
    timestamp_local: formatLocal(currentMs),
    offset_s: Number(((currentMs - START_MS) / 1000).toFixed(3))
  });
  marksEl.textContent = marks.map((mark, index) =>
    (index + 1) + ". " + mark.kind + "  " + mark.timestamp_local +
    "  (+" + mark.offset_s.toFixed(3) + " с)"
  ).join("\n");
}

function downloadMarks() {
  const blob = new Blob(
    [JSON.stringify({start_ms: START_MS, marks}, null, 2)],
    {type: "application/json"}
  );
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "trajectory_manual_marks.json";
  anchor.click();
  URL.revokeObjectURL(url);
}

document.getElementById("markEW").addEventListener("click", () => addMark("EW"));
document.getElementById("markNS").addEventListener("click", () => addMark("NS"));
document.getElementById("markNArrow").addEventListener("click", () => addMark("N_ARROW"));
document.getElementById("downloadMarks").addEventListener("click", downloadMarks);
document.getElementById("clearMarks").addEventListener("click", () => {
  marks.length = 0;
  marksEl.textContent = "";
});

function stop() {
  playing = false;
  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
  playButton.textContent = "▶ Пуск";
}

function play() {
  if (playing) { stop(); return; }
  playing = true;
  playButton.textContent = "⏸ Пауза";
  timer = setInterval(() => {
    if (currentMs >= END_MS) { stop(); return; }
    setTime(currentMs + playStepMs);
  }, 100);
}

playButton.addEventListener("click", play);
timeline.addEventListener("input", () => setTime(START_MS + Number(timeline.value)));

document.getElementById("back10").addEventListener("click", () => setTime(currentMs - 10000));
document.getElementById("back1").addEventListener("click", () => setTime(currentMs - 1000));
document.getElementById("forward1").addEventListener("click", () => setTime(currentMs + 1000));
document.getElementById("forward10").addEventListener("click", () => setTime(currentMs + 10000));

document.addEventListener("keydown", (event) => {
  if (event.code === "Space") {
    event.preventDefault();
    play();
  } else if (event.key === "ArrowLeft") {
    setTime(currentMs - (event.shiftKey ? 10000 : 1000));
  } else if (event.key === "ArrowRight") {
    setTime(currentMs + (event.shiftKey ? 10000 : 1000));
  } else if (event.key.toLowerCase() === "e") {
    addMark("EW");
  } else if (event.key.toLowerCase() === "n") {
    addMark("NS");
  } else if (event.key.toLowerCase() === "a") {
    addMark("N_ARROW");
  }
});

render();
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a browser viewer for trajectory coordinates."
    )
    parser.add_argument("path", type=Path, help="Trajectory JSON")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("trajectory_coordinate_viewer.html"),
    )
    parser.add_argument(
        "--stale-ms",
        type=int,
        default=1500,
        help="How long a track remains visible after its last detection.",
    )
    parser.add_argument(
        "--step-ms",
        type=int,
        default=500,
        help="Timeline step size.",
    )
    parser.add_argument(
        "--no-analysis",
        action="store_true",
        help="Skip Stage 1/2 analysis and build only the coordinate viewer.",
    )
    args = parser.parse_args()

    if args.stale_ms <= 0:
        parser.error("--stale-ms must be positive")
    if args.step_ms <= 0:
        parser.error("--step-ms must be positive")

    trajectories = _load_trajectories(args.path)
    tracks, zones, start_ms, end_ms = _prepare_tracks(trajectories)

    if not tracks:
        parser.error("no usable trajectory detections found")

    analysis: dict[str, object] | None = None
    analysis_error: str | None = None
    if not args.no_analysis:
        try:
            analysis = _build_stage_analysis(args.path)
        except Exception as exc:
            analysis_error = str(exc)

    data = {
        "start_ms": start_ms,
        "end_ms": end_ms,
        "step_ms": args.step_ms,
        "stale_ms": args.stale_ms,
        "tracks": tracks,
        "zones": {
            zone: [round(x, 5), round(y, 5)]
            for zone, (x, y) in zones.items()
        },
        "stage1": analysis["stage1"] if analysis else None,
        "stage2": analysis["stage2"] if analysis else None,
        "analysis_error": analysis_error,
    }

    output = HTML_TEMPLATE.replace("__DATA__", _escape_json(data))
    args.output.write_text(output, encoding="utf-8")

    print(f"Viewer: {args.output}")
    print(f"Trajectories: {len(tracks)}")
    print(f"Time range: {(end_ms - start_ms) / 1000:.1f}s")
    if analysis is not None:
        print(
            "Stage 1/2: "
            f"cycle={analysis['stage1']['cycle_seconds']:.2f}s, "
            f"phases={len(analysis['stage1']['phases'])}, "
            f"logical_groups={len(analysis['stage2']['groups'])}, "
            f"mapped_movements={len(analysis['stage2']['mapping']['movement_to_group'])}"
        )
    elif analysis_error:
        print(f"Stage 1/2 analysis error: {analysis_error}")
    print(
        "Controls: Space=play/pause, arrows=±1s, "
        "Shift+arrows=±10s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
