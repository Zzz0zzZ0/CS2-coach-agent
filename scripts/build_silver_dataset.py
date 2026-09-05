"""Build a versioned, AI-assisted silver annotation dataset from local demos."""

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.parser_service import TacticalDemoParser  # noqa: E402
from app.services.tactical_annotation_service import annotate_match, summarize_annotations  # noqa: E402


def _match_id(path: Path) -> str:
    match = re.search(r"[-_](\d{5,})[-_]", path.stem)
    return match.group(1) if match else path.stem


def _manifest(path: Path, match_id: str) -> dict:
    manifest_path = path.parent / "manifests" / f"{match_id}.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _quality_markdown(report: dict) -> str:
    label_rows = "\n".join(
        f"| {name} | {count} |" for name, count in report["label_types"].items()
    ) or "| none | 0 |"
    limitations = "\n".join(f"- {item}" for item in report["limitations"])
    return f"""# CS2 Silver Annotation v{report['schema_version']}

This dataset contains AI-assisted silver labels generated from deterministic demo facts and explicit weak-supervision rules. It is not presented as expert gold annotation.

## Coverage

- Matches: {report['matches']}
- Demos: {report['demos']}
- Maps: {', '.join(report['maps'])}
- Rounds: {report['rounds']}
- Canonical events: {report['events']}
- Labels: {report['labels']}
- Player ID coverage: {report['player_id_coverage']:.1%}
- Actor team coverage: {report['actor_team_coverage']:.1%}
- Actor area coverage: {report['actor_area_coverage']:.1%}
- Bomb site coverage: {report['bomb_site_coverage']:.1%}
- Mean label confidence: {report['mean_label_confidence']:.3f}
- Missing evidence references: {report['integrity']['missing_evidence_refs']}
- Duplicate event IDs: {report['integrity']['duplicate_event_ids']}
- Tick boundary violations: {report['integrity']['tick_boundary_violations']}

## Label distribution

| Label | Count |
|---|---:|
{label_rows}

## Method

- `OPENING_DUEL` and `POST_PLANT` are direct event facts; `TRADE_KILL` is a deterministic five-second temporal rule.
- `UTILITY_BURST` uses an eight-second same-team utility cluster followed by a kill or plant within ten seconds.
- `EXECUTE_CANDIDATE` is added only when a T-side utility burst is followed by a plant.
- `RETAKE_CONTACT` records the first post-plant CT-on-T kill and does not claim a complete retake strategy.
- Every label stores its rule version, confidence, review status, and evidence event IDs.

## Limitations

{limitations}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build CS2 silver tactical annotations")
    parser.add_argument("--demo-dir", type=Path, default=PROJECT_ROOT / "data" / "demos")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "datasets" / "silver" / "v0.2")
    parser.add_argument("--tick-rate", type=int, default=64)
    args = parser.parse_args()

    records = []
    for demo_path in sorted(args.demo_dir.glob("*.dem")):
        parsed = TacticalDemoParser(str(demo_path)).parse_to_dict()
        if not parsed.get("rounds"):
            continue
        match_id = _match_id(demo_path)
        manifest = _manifest(demo_path, match_id)
        records.extend(annotate_match(
            parsed,
            source_demo=demo_path.name,
            match_id=match_id,
            source_match_url=manifest.get("match", {}).get("match_url"),
            tick_rate=args.tick_rate,
        ))

    if not records:
        raise SystemExit(f"No parsed rounds found in {args.demo_dir}")
    report = summarize_annotations(records)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "round_annotations.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    (args.output_dir / "quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "README.md").write_text(_quality_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
