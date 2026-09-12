"""Command-line entry points."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .dashboard import serve
from .pipeline import DEFAULT_SESSION_ROOT, load_newest_store


def _format(value: object) -> str:
    if value is None:
        return "Unknown"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return f"{value:,}" if isinstance(value, int) else str(value)


def print_snapshot(root: Path, as_json: bool = False) -> None:
    path, store = load_newest_store(root)
    payload = {"source_file": str(path) if path else None, "snapshot": store.snapshot()}
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print("\033[2J\033[H", end="")
    print("Token Usage Monitor — read-only")
    print("=" * 72)
    print(f"Source: {path or 'no rollout file found'}")
    for session in payload["snapshot"]["sessions"]:
        print(f"\nSession {session['session_id']}")
        print(f"  Total Tokens : {_format(session['total_tokens'])}")
        print(f"  Requests     : {_format(session['request_count'])}")
        print(f"  Turns        : {_format(session['turn_count'])}")
        print(f"  Input        : {_format(session['input_tokens'])}")
        print(f"  Cached       : {_format(session['cached_tokens'])}")
        print(f"  Output       : {_format(session['output_tokens'])}")
        cache = session["cache_hit_percent"]
        print(f"  Cache Hit %  : {_format(cache)}%" if cache is not None else "  Cache Hit %  : Unknown")
        print(f"  TTFT         : {_format(session['ttft_ms'])} ms")
        print(f"  TPS          : {_format(session['tps'])}")
        print(f"  Latency      : {_format(session['latency_ms'])} ms")
        print(f"  Cost         : {_format(session['cost_usd'])}")
        print(f"  Quotas       : {json.dumps(session['quotas'], ensure_ascii=False)}")
    print("\nPress Ctrl-C to exit.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Codex usage monitor")
    parser.add_argument("--root", type=Path, default=DEFAULT_SESSION_ROOT)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args(argv)

    if args.serve:
        serve(args.host, args.port, args.root)
        return 0
    if args.once or args.as_json:
        print_snapshot(args.root, args.as_json)
        return 0
    try:
        while True:
            print_snapshot(args.root)
            time.sleep(max(args.interval, 0.2))
    except KeyboardInterrupt:
        return 0
