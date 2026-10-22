"""Extract CT/T observations from one real demo; no model, network, or knowledge ingestion."""

import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.parser_service import TacticalDemoParser


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("demo", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-rounds", type=int)
    args = parser.parse_args()
    if not args.demo.is_file():
        parser.error("demo must be an existing file")
    if args.output_dir.exists():
        parser.error("output directory already exists; use a new run directory")
    if args.max_rounds is not None and args.max_rounds < 1:
        parser.error("max-rounds must be positive")
    with args.demo.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    result = TacticalDemoParser(str(args.demo)).parse_opening_snapshots(max_rounds=args.max_rounds)
    result.update(source_demo=args.demo.name, source_demo_sha256=digest,
                  sample_scope="limited_prefix" if args.max_rounds else "completed_match_rounds",
                  max_rounds=args.max_rounds,
                  source_commit=subprocess.check_output(
                      ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1], text=True
                  ).strip(),
                  source_dirty=bool(subprocess.check_output(
                      ["git", "status", "--porcelain"], cwd=Path(__file__).resolve().parents[1], text=True
                  ).strip()),
                  parser_version=importlib.metadata.version("demoparser2"))
    sides = {}
    for side in ("CT", "T"):
        records = [r for r in result["rounds"] if r["side"] == side]
        sides[side] = {"eligible": len(records), "used": sum(r["status"] == "ok" for r in records),
                       "skipped": dict(Counter(r["reason"] for r in records if r["reason"]))}
    summary = {"map_name": result["map_name"], "source_demo_sha256": digest,
               "sample_scope": result["sample_scope"], "tick_rate_status": result["tick_rate_status"],
               "time_alignment": result["time_alignment"], "sides": sides,
               "claim": "snapshot extraction only; no model or tactical-intent validation"}
    # Create only after successful parsing; refuse to overwrite prior evidence.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for name, value in (("snapshots.json", result), ("quality.json", summary)):
        (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all(sides[s]["used"] for s in sides) else 1


if __name__ == "__main__":
    raise SystemExit(main())
