"""Provisional manuscript figures from complete, equal-series development results."""

import argparse
import csv
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

LABELS = {"mlp_static": "MLP / static", "mlp_gru": "MLP / GRU",
          "graph_static": "Graph / static", "graph_gru": "Graph / GRU",
          "graph_gru_no_motion": "Graph / GRU\n(no motion)", "graph_gru_common": "Graph / GRU\n(common input)"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if report["status"] != "completed" or set(report["tasks"]) != {"G3", "G4"}:
        raise ValueError("Complete development summary required")
    methods = list(LABELS)
    rows = []
    for task in ("G3", "G4"):
        for method in methods:
            item = report["tasks"][task]["methods"][method]
            for series, value in item["by_series"].items():
                rows.append({"task": task, "method": method, "series": series, **value})
            mean = np.mean([value["loss"] for value in item["by_series"].values()])
            if not np.isfinite(mean) or not np.isclose(mean, item["loss_equal_series"], atol=1e-8):
                raise ValueError("Figure estimator differs from report")
    args.output_dir.mkdir(parents=True)
    with (args.output_dir / "series_data.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    style = {"font.family": "Arial", "font.size": 9, "axes.labelsize": 9, "axes.titlesize": 10, "pdf.fonttype": 42,
             "svg.fonttype": "none", "axes.spines.top": False, "axes.spines.right": False,
             "figure.facecolor": "white", "savefig.facecolor": "white"}
    with plt.rc_context(style):
        fig, axes = plt.subplots(1, 2, figsize=(7.1, 3.4), sharey=True, sharex=True, layout="constrained")
        maximum = max(row["loss"] for row in rows)
        for ax, task, title in zip(axes, ("G3", "G4"), ("(a) Series held out", "(b) Map and its series excluded")):
            for y, method in enumerate(methods):
                item = report["tasks"][task]["methods"][method]
                values = [value["loss"] for _, value in sorted(item["by_series"].items())]
                offset = np.linspace(-.13, .13, len(values))
                ax.scatter(values, y + offset, s=12, color="#777777", alpha=.65, marker="o", linewidths=0)
                ax.scatter(item["loss_equal_series"], y, s=28, marker="s", color="#0072B2", edgecolors="black", linewidths=.5, zorder=3)
            ax.set_title(title)
            ax.set_xlim(0, maximum * 1.08)
            ax.set_xlabel("Reconstruction objective\n(lower is better)")
            ax.set_yticks(range(len(methods)), [LABELS[method] for method in methods])
            ax.grid(axis="x", alpha=.2)
        axes[0].invert_yaxis()
        fig.suptitle("Development only: dots = individual series; squares = equal-series means", fontsize=9)
        for suffix in ("pdf", "svg", "png"):
            fig.savefig(args.output_dir / ("reconstruction." + suffix), dpi=300)
        plt.close(fig)
        maps = sorted(report["tasks"]["G4"]["methods"][methods[0]]["by_map"])
        cells, csv_rows = [], []
        for name in maps:
            baseline = report["tasks"]["G4"]["methods"]["graph_gru_common"]["by_map"][name]["loss_equal_series"]
            if baseline <= 0:
                raise ValueError("Positive common-input loss required")
            cells.append([])
            for method in methods:
                value = report["tasks"]["G4"]["methods"][method]["by_map"][name]["loss_equal_series"]
                reduction = 100 * (1 - value / baseline)
                cells[-1].append(reduction)
                csv_rows.append({"map": name, "method": method, "loss": value, "reference_loss": baseline, "reduction_pct": reduction})
        cells = np.asarray(cells)
        limit = max(float(np.abs(cells).max()), 1)
        fig, ax = plt.subplots(figsize=(7.1, 3.6), layout="constrained")
        image = ax.imshow(cells, cmap="RdBu", vmin=-limit, vmax=limit, interpolation="nearest", aspect="auto")
        ax.set_xticks(range(len(methods)), [LABELS[method] for method in methods], fontsize=9)
        ax.set_yticks(range(len(maps)), [name.replace("de_", "").capitalize() for name in maps])
        for i in range(len(maps)):
            for j in range(len(methods)):
                ax.text(j, i, f"{cells[i, j]:+.1f}%", ha="center", va="center",
                        color="white" if abs(cells[i, j]) > .6 * limit else "black", fontsize=9)
        fig.colorbar(image, ax=ax, label="Objective reduction vs common-input Graph/GRU (%)")
        ax.set_title("G4 development: equal-series comparison within each map")
        for suffix in ("pdf", "svg", "png"):
            fig.savefig(args.output_dir / ("map_comparison." + suffix), dpi=300)
        plt.close(fig)
    with (args.output_dir / "map_data.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(csv_rows[0])); writer.writeheader(); writer.writerows(csv_rows)
    write(args.output_dir / "manifest.json", {"status": "provisional_figures_generated_visual_review_pending",
          "source_report_sha256": sha(args.report), "script_sha256": sha(Path(__file__)),
          "figures": {"reconstruction": "Per-series loss after averaging neural seeds within windows; square is equal-series mean, no inferential error bar.",
                      "map_comparison": "100*(1-method_loss/common_input_graph_gru_loss), equal-series within each map. Positive means lower objective, not tactical improvement."},
          "destination": "Provisional full-paper figures, journal-specific export requirements not yet verified",
          "dimensions_inches": {"reconstruction": [7.1, 3.4], "map_comparison": [7.1, 3.6]},
          "formats": ["PDF vector with Type42 fonts", "SVG with editable text", "PNG at 300 DPI"],
          "limits": ["Development data only; shared teams/folds are not independent.", "No tactical relevance, win-rate or coaching effect claimed."],
          "output_sha256": {p.name: sha(p) for p in args.output_dir.iterdir() if p.is_file()}})


if __name__ == "__main__":
    main()
