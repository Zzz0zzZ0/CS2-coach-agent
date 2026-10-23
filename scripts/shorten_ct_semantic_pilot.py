"""Derive a 24-pair process pilot without changing the frozen full pilot."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "ct-semantic-pilot-v9-short24"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def payload_hash(payload):
    return digest(json.dumps({k: v for k, v in payload.items() if k != "payload_sha256"},
                            ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())


def shorten(payload, key):
    if payload_hash(payload) != payload["payload_sha256"] or key["payload_sha256"] != payload["payload_sha256"]:
        raise ValueError("Payload and private key do not match")
    result, private = copy.deepcopy(payload), copy.deepcopy(key)
    for query in result["queries"]:
        details = private["queries"][query["id"]]
        ranks = details["method_rankings"]
        common = ranks["common_state_5snap"][0]
        random = next((c for c in ranks["deterministic_random"] if c != common), None)
        if random is None:
            raise ValueError("Two distinct candidates required")
        chosen = sorted([common, random], key=lambda c: digest(f"{VERSION}:{query['id']}:{c}".encode()))
        records = {c["id"]: c["record"] for c in query["candidates"]}
        if any(c not in records or c not in details["candidates"] for c in chosen):
            raise ValueError("Candidate missing from payload or private key")
        labels = {c: f"C{i + 1:02d}" for i, c in enumerate(chosen)}
        query["candidates"] = [{"id": labels[c], "record": records[c]} for c in chosen]
        details["candidates"] = {labels[c]: details["candidates"][c] for c in chosen}
        details["method_rankings"] = {"common_state_5snap": [labels[common]],
                                      "deterministic_random": [labels[random]]}
    result["version"] = VERSION
    result["payload_sha256"] = payload_hash(result)
    private["payload_sha256"] = result["payload_sha256"]
    private["source_payload_sha256"] = payload["payload_sha256"]
    return result, private


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new output directory to preserve ratings")
    receipt = ROOT / "datasets/evaluation/ct_semantic_pilot_v9_report.json"
    source = json.loads(receipt.read_text(encoding="utf-8"))
    template = ROOT / "scripts/templates/ct_pilot_review.html"
    for path, expected in [(args.source_dir / "review.html", source["html_sha256"]),
                           (args.source_dir / "analyst_key.json", source["private_key_sha256"]),
                           (template, source["source_sha256"][str(template.relative_to(ROOT))])]:
        if digest(path.read_bytes()) != expected:
            raise ValueError(f"Frozen input changed: {path.name}")
    html = (args.source_dir / "review.html").read_text(encoding="utf-8")
    match = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    payload = json.loads(match.group(1))
    if payload["payload_sha256"] != source["payload_sha256"]:
        raise ValueError("Unexpected source pilot")
    payload, key = shorten(payload, json.loads((args.source_dir / "analyst_key.json").read_text(encoding="utf-8")))
    assert len(payload["queries"]) == 12 and sum(len(q["candidates"]) for q in payload["queries"]) == 24
    html = template.read_text(encoding="utf-8").replace("独立评审试点", "首轮短版 · 24 条")
    html = html.replace("<details open>", '<p class="warning">本轮共 24 条，检查材料和评分规则是否清楚；不用于正式模型效果结论。</p><details open>')
    html = html.replace("CT-pilot-v9-${reviewer}", "CT-pilot-v9-short24-${reviewer}")
    html = html.replace("@@PAYLOAD@@", json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c"))
    guide = (args.source_dir / "README_评审.txt").read_text(encoding="utf-8")
    guide = guide.replace("独立评审试点", "首轮短版（每人 24 条）").replace("119 个候选条目", "24 个候选条目（每查询 2 个）")
    guide += "\n本轮只检查材料与评分规则是否清楚；无需同时完成区域核查表或 119 条完整版。短版不用于正式模型效果结论。\n"
    args.output_dir.mkdir(parents=True)
    for name, content in [("review.html", html), ("README_评审.txt", guide),
                          ("analyst_key.json", json.dumps(key, ensure_ascii=False, indent=2) + "\n")]:
        (args.output_dir / name).write_text(content, encoding="utf-8")
    archive = args.output_dir / "ct-reviewer-kit-v9-short24.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in ("review.html", "README_评审.txt"):
            bundle.write(args.output_dir / name, name)
    report = {"status": "prepared_short_process_pilot_without_human_ratings", "queries": 12,
              "candidate_pairs": 24, "human_ratings": 0, "version": VERSION,
              "selection": "Common-state rank 1 plus first distinct random-control candidate; deterministic reblinding",
              "limits": ["Process pilot only; no neural comparison, efficacy claim or nDCG@5.",
                         "Random control skips overlap with common-state rank 1; not an unbiased method comparison.",
                         "Inherited Q04 patch mismatch and CT-only information limits remain."],
              "source_report_sha256": digest(receipt.read_bytes()), "source_payload_sha256": source["payload_sha256"],
              "payload_sha256": payload["payload_sha256"],
              "artifact_sha256": {p.name: digest(p.read_bytes()) for p in args.output_dir.iterdir()},
              "source_sha256": {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in (Path(__file__), template)}}
    (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("queries", "candidate_pairs", "human_ratings")}))


if __name__ == "__main__":
    main()
