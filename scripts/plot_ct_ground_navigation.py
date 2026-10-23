"""Show missing NAV assignments by ground state; counts are not localization accuracy."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    a = parser.parse_args()
    if a.output.exists():
        parser.error("Use a new figure path")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    report = json.loads(a.report.read_text())
    version = report["manifests"][0]["client_version"]
    maps = report["maps"][version]["by_map"]
    names = sorted(maps)
    grounded = [maps[m].get("grounded_unlocalized", 0) for m in names]
    airborne = [maps[m].get("airborne", 0) - maps[m].get("airborne_bounded_match", 0) for m in names]
    assert all(g >= 0 and b >= 0 for g, b in zip(grounded, airborne))
    assert sum(g + b for g, b in zip(grounded, airborne)) == sum(c["observations"] - c["ungated_bounded_match"] for c in maps.values())
    fig, ax = plt.subplots(figsize=(9, 4.8), layout="constrained")
    ax.barh(names, grounded, label="Grounded, no bounded NAV surface", color="#d07539")
    ax.barh(names, airborne, left=grounded, label="Airborne, no bounded NAV surface", color="#8394ad")
    for y, (g, b) in enumerate(zip(grounded, airborne)):
        ax.text(g + b + 1.5, y, f"{g + b}  ({g} grounded / {b} airborne)", va="center", fontsize=9)
    ax.set_yticks(range(len(names)), [m[3:].capitalize() for m in names])
    ax.set_xlim(0, max(g + b for g, b in zip(grounded, airborne)) * 1.65)
    ax.set_xlabel("Live CT player-snapshots; repeated observations, not independent samples")
    ax.set_title("Missing NAV assignments require separate diagnoses", loc="left", fontweight="bold")
    ax.legend(loc="upper right", frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.invert_yaxis()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.output, dpi=200, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    main()
