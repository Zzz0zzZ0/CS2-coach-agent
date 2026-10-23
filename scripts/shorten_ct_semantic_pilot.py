"""Derive a 24-pair process pilot without changing the frozen full pilot."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "ct-semantic-pilot-v9-short24-r2"


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


def distribute(payload, key, template, output_dir):
    """One query per packet; each original pair is assigned exactly once."""
    if payload_hash(payload) != payload["payload_sha256"] or key["payload_sha256"] != payload["payload_sha256"]:
        raise ValueError("Payload and private key do not match")
    output_dir.mkdir(parents=True)
    packets = []
    for query in payload["queries"]:
        qid, count = query["id"], len(query["candidates"])
        packet = copy.deepcopy(payload)
        packet.update(version=f"ct-pilot-v9-distributed-r2-{qid}", queries=[copy.deepcopy(query)])
        packet["payload_sha256"] = payload_hash(packet)
        folder = output_dir / qid
        folder.mkdir()
        html = template.replace("独立评审试点", f"分发题包 {qid} · {count} 条")
        html = html.replace("CT-pilot-v9-${reviewer}", f"CT-pilot-v9-{qid}-" + "${reviewer}")
        html = html.replace("@@PAYLOAD@@", json.dumps(packet, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c"))
        (folder / "review.html").write_text(html, encoding="utf-8")
        guide = (f"题包 {qid}，共 {count} 条；只需完成这一包。\n"
                 "先解压，再用 Chrome 或 Edge 打开 review.html；不要在聊天或压缩包预览内填写。\n"
                 "打开即可评分，无需注册或点开始。匿名代号自动分配，CS2 经验可补填。\n"
                 "每条填写两项评分和简短理由；信息不足选无法判断。结束或暂停时点导出，将 JSON 交回组织者。\n"
                 "各自独立填写；不会自动上传。此批材料用于检查部署参考和评分规则，尚不支持模型效果结论。\n")
        (folder / "说明.txt").write_text(guide, encoding="utf-8")
        archive = output_dir / f"CT-{qid}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for name in ("review.html", "说明.txt"):
                bundle.write(folder / name, name)
        packets.append({"packet": qid, "candidate_pairs": count, "payload_sha256": packet["payload_sha256"],
                        "archive": archive.name, "archive_sha256": digest(archive.read_bytes())})
    private = {"source_payload_sha256": payload["payload_sha256"], "queries": key["queries"], "packets": packets}
    (output_dir / "analyst_key.json").write_text(json.dumps(private, indent=2) + "\n", encoding="utf-8")
    instructions = "组织者：每人分发一个不同的 CT-Qxx.zip，不要发送 analyst_key.json 或整个目录。\n"
    instructions += "\n".join(f"{p['archive']}：{p['candidate_pairs']} 条；领取人：________" for p in packets)
    instructions += "\n各包题目不重复；回收每人的 JSON。此分配不测量同题评审一致性。\n"
    (output_dir / "分发清单.txt").write_text(instructions, encoding="utf-8")
    with zipfile.ZipFile(output_dir / "CT-12题包-分发合集.zip", "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in [p["archive"] for p in packets] + ["分发清单.txt"]:
            bundle.write(output_dir / name, name)
    report = {"status": "prepared_distributed_process_pilot_without_human_ratings", "human_ratings": 0,
              "candidate_pairs": sum(p["candidate_pairs"] for p in packets), "packets": packets,
              "source_payload_sha256": payload["payload_sha256"],
              "limits": ["Disjoint packets cannot measure agreement on the same items.",
                         "Development materials only; not neural-model efficacy evidence."],
              "source_sha256": digest(Path(__file__).read_bytes()), "template_sha256": digest(template.encode())}
    (output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"packets": len(packets), "candidate_pairs": report["candidate_pairs"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--distribute", action="store_true", help="Split all full-pilot queries into separate reviewer packets")
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new output directory to preserve ratings")
    receipt = ROOT / "datasets/evaluation/ct_semantic_pilot_v9_report.json"
    source = json.loads(receipt.read_text(encoding="utf-8"))
    template = ROOT / "scripts/templates/ct_pilot_review.html"
    for path, expected in [(args.source_dir / "review.html", source["html_sha256"]),
                           (args.source_dir / "analyst_key.json", source["private_key_sha256"] )]:
        if digest(path.read_bytes()) != expected:
            raise ValueError(f"Frozen input changed: {path.name}")
    html = (args.source_dir / "review.html").read_text(encoding="utf-8")
    match = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    payload = json.loads(match.group(1))
    if payload["payload_sha256"] != source["payload_sha256"]:
        raise ValueError("Unexpected source pilot")
    key = json.loads((args.source_dir / "analyst_key.json").read_text(encoding="utf-8"))
    if args.distribute:
        distribute(payload, key, template.read_text(encoding="utf-8"), args.output_dir)
        return
    payload, key = shorten(payload, key)
    assert len(payload["queries"]) == 12 and sum(len(q["candidates"]) for q in payload["queries"]) == 24
    html = template.read_text(encoding="utf-8").replace("独立评审试点", "首轮短版 · 24 条")
    html = html.replace("<details open>", '<p class="warning">本轮共 24 条，检查材料和评分规则是否清楚；不用于正式模型效果结论。</p><details open>')
    html = html.replace("CT-pilot-v9-${reviewer}", "CT-pilot-v9-short24-${reviewer}")
    html = html.replace("@@PAYLOAD@@", json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c"))
    guide = (args.source_dir / "README_评审.txt").read_text(encoding="utf-8")
    guide = guide.replace("独立评审试点", "首轮短版（每人 24 条）").replace("119 个候选条目", "24 个候选条目（每查询 2 个）")
    guide = guide.replace("点击“开始／继续评分”。", "打开即可评分；系统自动分配匿名代号。需要改代号时点“切换代号／恢复”。")
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
