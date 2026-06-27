"""CLI entry point for the XHS Supervisor pipeline.

Usage:
    python scripts/run_pipeline.py "找一款租房好用的平价收纳好物"
    python scripts/run_pipeline.py "收纳好物" --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xhs_supervisor.supervisor import run_pipeline  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the XHS Supervisor pipeline.")
    ap.add_argument("prompt", help="选品指令, e.g. '平价收纳好物'")
    ap.add_argument("--json", action="store_true", help="emit final state as JSON")
    ap.add_argument("--source", default=None, help="optional constraint: source=taobao|pinduoduo")
    args = ap.parse_args()

    constraints: dict = {}
    if args.source:
        constraints["source"] = args.source

    def on_log(line: str) -> None:
        print(line, flush=True)

    final = run_pipeline(args.prompt, constraints, on_log=on_log)

    print(f"\n=== FINAL STATUS: {final.get('status')} ===", flush=True)
    if final.get("error"):
        print(f"ERROR: {final['error']}", flush=True)

    if args.json:
        safe = {k: v for k, v in final.items() if k != "messages"}
        print(json.dumps(safe, ensure_ascii=False, indent=2, default=str))
    return 0 if final.get("status") == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
