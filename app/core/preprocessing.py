from __future__ import annotations

import codecs
import json
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator

import numpy as np
import pandas as pd

from app.core.models import Trajectory, TrafficWindow
from app.core.trajectory_geometry import build_trajectory_model

STOP_THRESHOLD_S = 5.0
DEFAULT_WINDOW_S = 10.0
DEFAULT_JSON_STREAM_CHUNK_BYTES = 64 * 1024
DEFAULT_JSON_MAX_OBJECT_CHARS = 16 * 1024 * 1024


def _trajectory_from_dict(item: dict) -> Trajectory | None:
    if item.get("category_name") != "car":
        return None
    if not item.get("zone_in"):
        return None
    if item.get("millis") is None:
        return None

    return build_trajectory_model(item)


def iter_trajectory_payload_stream(
    stream: BinaryIO,
    *,
    chunk_size: int = DEFAULT_JSON_STREAM_CHUNK_BYTES,
    max_object_chars: int = DEFAULT_JSON_MAX_OBJECT_CHARS,
) -> Iterator[Trajectory]:
    """Incrementally decode a trajectory JSON array.

    At most the current JSON object plus a bounded input buffer is retained.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if max_object_chars <= 0:
        raise ValueError("max_object_chars must be positive")

    decoder = json.JSONDecoder()
    utf8 = codecs.getincrementaldecoder("utf-8")()
    buffer = ""
    eof = False
    started = False
    expect_value = True

    def fill() -> bool:
        nonlocal buffer, eof
        if eof:
            return False
        chunk = stream.read(chunk_size)
        if not chunk:
            if isinstance(chunk, str):
                buffer += chunk
            else:
                buffer += utf8.decode(b"", final=True)
            eof = True
            return False
        if isinstance(chunk, str):
            buffer += chunk
        else:
            buffer += utf8.decode(chunk, final=False)
        return True

    while True:
        if not started:
            while True:
                buffer = buffer.lstrip()
                if buffer:
                    if not buffer.startswith("["):
                        raise ValueError("Trajectory JSON root must be a list")
                    buffer = buffer[1:]
                    started = True
                    break
                if not fill():
                    raise ValueError("Trajectory JSON root must be a list")

        buffer = buffer.lstrip()
        if not buffer:
            if eof:
                raise ValueError("unterminated trajectory JSON array")
            fill()
            continue

        if expect_value:
            if buffer[0] == "]":
                buffer = buffer[1:]
                expect_value = False
            else:
                while True:
                    try:
                        value, end_index = decoder.raw_decode(buffer)
                        break
                    except json.JSONDecodeError as exc:
                        if eof:
                            raise ValueError(
                                f"invalid trajectory JSON: {exc.msg} at char {exc.pos}"
                            ) from exc
                        if len(buffer) > max_object_chars:
                            raise ValueError(
                                "trajectory JSON object exceeds bounded streaming size"
                            ) from exc
                        fill()
                buffer = buffer[end_index:]
                expect_value = False
                if isinstance(value, dict):
                    trajectory = _trajectory_from_dict(value)
                    if trajectory is not None:
                        yield trajectory
                continue

        buffer = buffer.lstrip()
        if not buffer:
            if eof:
                raise ValueError("unterminated trajectory JSON array")
            fill()
            continue
        if buffer[0] == ",":
            buffer = buffer[1:]
            expect_value = True
            continue
        if buffer[0] == "]":
            buffer = buffer[1:]
            while not eof:
                if not buffer.strip():
                    if not fill():
                        break
                else:
                    raise ValueError(
                        "unexpected data after trajectory JSON array"
                    )
            if buffer.strip():
                raise ValueError(
                    "unexpected data after trajectory JSON array"
                )
            return
        raise ValueError("expected ',' or ']' in trajectory JSON array")


def load_trajectory_payload(data: object) -> list[Trajectory]:
    """Normalize one decoded trajectory JSON payload through the production loader."""
    if not isinstance(data, list):
        raise ValueError("Trajectory JSON root must be a list")

    trajectories: list[Trajectory] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        trajectory = _trajectory_from_dict(item)
        if trajectory is not None:
            trajectories.append(trajectory)
    return trajectories


def load_trajectory_file(path: Path) -> list[Trajectory]:
    with path.open("r", encoding="utf-8") as stream:
        return load_trajectory_payload(json.load(stream))


def load_trajectory_files(paths: Iterable[Path]) -> list[Trajectory]:
    trajectories: list[Trajectory] = []
    for path in paths:
        trajectories.extend(load_trajectory_file(path))
    return trajectories


def trajectories_to_frame(trajectories: Iterable[Trajectory]) -> pd.DataFrame:
    frame = pd.DataFrame(
        [trajectory.to_record() for trajectory in trajectories]
    )
    if frame.empty:
        raise ValueError("No usable car trajectories found")

    frame["t_s"] = (
        frame["timestamp_ms"] - frame["timestamp_ms"].min()
    ) / 1000.0
    frame["stopped"] = frame["wait_s"] >= STOP_THRESHOLD_S
    frame["release_weight"] = np.maximum(
        frame["wait_s"] - STOP_THRESHOLD_S,
        0.0,
    )
    return frame


def build_traffic_windows(
    trajectories: Iterable[Trajectory],
    *,
    window_s: float = DEFAULT_WINDOW_S,
) -> list[TrafficWindow]:
    if window_s <= 0:
        raise ValueError("window_s must be positive")

    frame = trajectories_to_frame(trajectories)
    frame["window_start_s"] = (
        np.floor(frame["t_s"] / window_s) * window_s
    ).astype(float)

    grouped = (
        frame.groupby(["window_start_s", "movement"], as_index=False)
        .agg(
            flow=("vehicle_id", "count"),
            mean_speed=("speed", "mean"),
            mean_wait=("wait_s", "mean"),
            stopped_count=("stopped", "sum"),
            release_weight=("release_weight", "sum"),
        )
        .sort_values(["window_start_s", "movement"])
    )

    return [
        TrafficWindow(
            start_s=float(row.window_start_s),
            duration_s=float(window_s),
            movement=str(row.movement),
            flow=int(row.flow),
            mean_speed=(
                float(row.mean_speed)
                if pd.notna(row.mean_speed)
                else None
            ),
            mean_wait=(
                float(row.mean_wait)
                if pd.notna(row.mean_wait)
                else None
            ),
            stopped_count=int(row.stopped_count),
            release_weight=float(row.release_weight),
        )
        for row in grouped.itertuples(index=False)
    ]
