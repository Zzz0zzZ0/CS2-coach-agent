"""Unjudged cross-map observation examples; sampled segments are not traversed routes."""

import argparse
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.confirm_ct_generalization import sha, write


def observed_tracks(frames):
    origin = np.mean([p["position"][:2] for p in frames[0]["players"] if p["health"] > 0], axis=0)
    identities = [str(p["steamid"]) for p in frames[0]["players"]]
    traces = []
    for identity in identities:
        trace = []
        for frame in frames:
            player = next(p for p in frame["players"] if str(p["steamid"]) == identity)
            trace.append([*(np.asarray(player["position"][:2]) - origin), player["position"][2]] if player["health"] > 0 else [None] * 3)
        traces.append(trace)
    return traces


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("analysis-dir", "run-dir", "inventory", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    for key, value in vars(args).items():
        resolved = value.resolve()
        if not resolved.is_relative_to(ROOT):
            parser.error("Keep evidence paths inside workspace")
        setattr(args, key, resolved)
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    report = json.loads((args.analysis_dir / "report.json").read_text(encoding="utf-8"))
    rankings_path = args.analysis_dir / "rankings.jsonl"
    if report["status"] != "completed" or sha(rankings_path) != report["output_sha256"]["rankings.jsonl"]:
        raise ValueError("Complete checked ranking output required")
    protocol_path = ROOT / "datasets/selections/ct_reconstruction_matrix.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if sha(protocol_path) != report["protocol_sha256"]:
        raise ValueError("Matrix protocol changed")
    index_path = args.run_dir / "sample_index.json"
    if sha(index_path) != protocol["input_sha256"][str(index_path.relative_to(ROOT)).replace('\\', '/')]:
        raise ValueError("Sample index changed")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    raw = {}
    for name, expected in inventory["dataset_sha256"].items():
        if sha(ROOT / name) != expected:
            raise ValueError("Raw observation changed")
        if name.endswith("_snapshots.json"):
            document = json.loads((ROOT / name).read_text(encoding="utf-8"))
            for row in document["rounds"]:
                if row["side"] == "CT":
                    identity = f"{document['source_demo_sha256']}:{row['round_number']}:CT"
                    if identity in raw:
                        raise ValueError("Duplicate raw window")
                    raw[identity] = row["snapshots"]
    rankings = {}
    for line in rankings_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["fold"].startswith("G4__") and row["seed"] == 0 and row["method"] in ("graph_gru", "mlp_gru"):
            rankings[(row["query_index"], row["method"])] = row
    selection = {}
    for query in sorted({key[0] for key in rankings}):
        selection.setdefault(index[query]["map"], query)
    if set(selection) != {row["map"] for row in index}:
        raise ValueError("Missing map evidence")
    args.output_dir.mkdir(parents=True)
    evidence = {"status": "unjudged_observation_examples", "ranking_report_sha256": sha(args.analysis_dir / "report.json"),
                "inventory_sha256": sha(args.inventory), "script_sha256": sha(Path(__file__)),
                "selection": "First query by frozen sample-index order in each G4 map; full-input graph/GRU and MLP/GRU, seed 0, top-1 cross-map candidate. No quality-based selection.",
                "limits": ["No relevance judgment or tactical interpretation supplied.", "Centered coordinates retain native axes; walls, routes, opponents and utility are absent.", "Colors identify players within one window only, not corresponding people across panels."], "examples": []}
    text = ["# 跨地图部署原始观测示例", "", "每图固定取样本顺序中的第一个查询，列出两个预定方法的首位候选。没有挑选好看的结果，也没有给相关性评分。", "", "各回合以10秒时存活队员的平均位置为中心，保留原地图坐标轴；各面板使用相同距离尺度。虚线仅连接10/12/15/18/20秒的观测点，不代表实际路线。死亡后的坐标不显示；颜色只在各自回合内区分队员。没有墙体、敌人或道具信息，不能仅凭图判断战术职责。", ""]
    colors = ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#333333")
    for name, query in sorted(selection.items()):
        candidates = [rankings[(query, method)]["strata"]["cross_map"]["candidate_indices"][0] for method in ("graph_gru", "mlp_gru")]
        chosen = [query, *candidates]
        if any(index[c]["series"] == index[query]["series"] or index[c]["map"] == name for c in candidates):
            raise ValueError("Cross-map or series exclusion failed")
        records = [{"index": i, "record": index[i], "observed_tracks": observed_tracks(raw[index[i]["id"]])} for i in chosen]
        all_xy = np.concatenate([np.asarray(row["observed_tracks"], dtype=float)[..., :2].reshape(-1, 2) for row in records])
        extent = max(float(np.nanmax(np.abs(all_xy))), 100) * 1.12
        with plt.rc_context({"font.family": "Arial", "font.size": 9, "svg.fonttype": "none", "pdf.fonttype": 42}):
            fig, axes = plt.subplots(1, 3, figsize=(7.1, 2.8), layout="constrained")
            for ax, row, label in zip(axes, records, ("Query", "Graph/GRU: top 1", "MLP/GRU: top 1")):
                tracks = np.asarray(row["observed_tracks"], dtype=float)
                for number, (trace, color) in enumerate(zip(tracks, colors), 1):
                    ax.plot(trace[:, 0], trace[:, 1], "o--", color=color, linewidth=.8, markersize=3)
                    valid = np.flatnonzero(np.isfinite(trace[:, 0]))
                    if len(valid):
                        ax.annotate(str(number), trace[valid[0], :2], fontsize=6)
                height = np.nanmax(tracks[..., 2]) - np.nanmin(tracks[..., 2])
                ax.set(xlim=(-extent, extent), ylim=(-extent, extent), aspect="equal",
                       title=f"{label}\n{row['record']['map'].replace('de_', '')}, round {row['record']['round_number']}",
                       xlabel=f"Game units\nObserved height span {height:.0f}")
                ax.grid(alpha=.2)
            axes[0].set_ylabel("Game units from initial team center")
            fig.suptitle("10–20 s observations; dashed links are not traversed paths; relevance unjudged", fontsize=9)
            for suffix in ("png", "svg", "pdf"):
                fig.savefig(args.output_dir / f"{name}.{suffix}", dpi=300, facecolor="white")
            plt.close(fig)
        evidence["examples"].append({"map": name, "records": records, "methods": ["query", "graph_gru", "mlp_gru"], "tactical_relevance": None})
        text.extend([f"## {name}", "", f"![{name}三组未评分观测]({name}.png)", "", "| 面板 | 系列 | 回合 | 样本编号 |", "| --- | --- | --- | --- |"])
        text.extend(f"| {label} | {index[i]['series']} | {index[i]['round_number']} | {i} |" for label, i in zip(("查询", "图模型候选", "非图模型候选"), chosen))
        text.append("")
    (args.output_dir / "README.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    evidence["output_sha256"] = {p.name: sha(p) for p in args.output_dir.iterdir() if p.is_file()}
    write(args.output_dir / "evidence.json", evidence)
    print(json.dumps({"maps": len(selection), "relevance_judgments": 0}))


if __name__ == "__main__":
    main()
