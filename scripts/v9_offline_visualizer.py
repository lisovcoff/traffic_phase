from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.v9.signal_renderer import (
    DEFAULT_ACTIVITY_THRESHOLD,
    DEFAULT_RED_YELLOW_DURATION_SECONDS,
    DEFAULT_YELLOW_DURATION_SECONDS,
)
from app.core.v9.v9_discovery import discover_path
from app.core.v9.source_scope import ScopeChoiceRequired


from app.core.offline_product_report import render_product_html


def render_html(result, *, yellow_duration_seconds=DEFAULT_YELLOW_DURATION_SECONDS,
                red_yellow_duration_seconds=DEFAULT_RED_YELLOW_DURATION_SECONDS,
                activity_threshold=DEFAULT_ACTIVITY_THRESHOLD, history_source="accepted"):
    # Compatibility arguments no longer synthesize physical colors in reconstructed HTML.
    return render_product_html(result, history_source=history_source)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a self-contained HTML visualization from V9 archive analysis."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="JSON file, ZIP archive or directory with JSON trajectory files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("v9_offline_report.html"),
    )
    parser.add_argument("--dt", type=float, default=1.0)
    parser.add_argument('--source-member')
    parser.add_argument('--session-id')
    parser.add_argument(
        "--yellow",
        type=float,
        default=DEFAULT_YELLOW_DURATION_SECONDS,
        help="compatibility option; reconstructed HTML does not synthesize transitions",
    )
    parser.add_argument(
        "--red-yellow",
        type=float,
        default=DEFAULT_RED_YELLOW_DURATION_SECONDS,
        help="compatibility option; reconstructed HTML does not synthesize transitions",
    )
    parser.add_argument(
        "--activity-threshold",
        type=float,
        default=DEFAULT_ACTIVITY_THRESHOLD,
        help="compatibility option; HTML displays scores without lamp thresholds",
    )
    parser.add_argument("--prediction", action="store_true", help="input is a saved V9 prediction; no discovery")
    parser.add_argument("--history", choices=["accepted", "experimental"], default="accepted")
    args = parser.parse_args()

    if args.yellow < 0 or args.red_yellow < 0:
        raise SystemExit("transition durations must be non-negative")
    if not 0 <= args.activity_threshold <= 1:
        raise SystemExit("activity threshold must be in [0, 1]")

    if args.input.resolve() == args.output.resolve():
        raise SystemExit("output cannot overwrite input")
    if args.prediction:
        if args.input.stat().st_size > 32 * 1024 * 1024:
            raise SystemExit("prediction exceeds 32 MiB limit")
        result = json.loads(args.input.read_bytes())
    else:
        try:
            result = discover_path(args.input, dt=args.dt,
                                   **{k: v for k, v in {'source_member': args.source_member,
                                      'session_id': args.session_id}.items() if v is not None})
        except ScopeChoiceRequired as exc:
            print(json.dumps(exc.to_dict(), ensure_ascii=False, indent=2))
            return 2
    page = render_html(
        result,
        history_source=args.history,
        yellow_duration_seconds=args.yellow,
        red_yellow_duration_seconds=args.red_yellow,
        activity_threshold=args.activity_threshold,
    )
    args.output.write_text(
        page,
        encoding="utf-8",
    )
    print("[V9] offline visualization complete")
    print("  input:", args.input)
    print("  output:", args.output)
    print("  phases:", result["schedule"]["phase_count"])
    print(
        "  period_s:",
        round(float(result["schedule"]["period_s"]), 3),
    )
    print(
        "  duration_s:",
        round(float(result.get("recording_duration_s", 0)), 3),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
