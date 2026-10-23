"""Compare bounded surface localization with Awpy on the same frozen CT observations."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_navigation_service import NavigationLocator
from scripts.audit_ct_map_semantics import live_players, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new receipt path")
    from awpy import NavMesh
    import psutil

    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    index = json.loads((args.run_dir / "sample_index.json").read_text(encoding="utf-8"))
    if sha(args.run_dir / "report.json") != inventory["run_report_sha256"]:
        raise ValueError("Run report differs from inventory")
    wanted, rows = {e["id"] for e in index}, {}
    for relative, digest in inventory["dataset_sha256"].items():
        path = ROOT / relative
        if sha(path) != digest:
            raise ValueError("Input changed since inventory")
        if relative.endswith("_snapshots.json"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            for row in doc["rounds"]:
                identity = f"{doc['source_demo_sha256']}:{row['round_number']}:CT"
                if row["side"] == "CT" and identity in wanted:
                    if identity in rows:
                        raise ValueError("Duplicate CT identity")
                    rows[identity] = row
    if set(rows) != wanted or len(wanted) != len(index):
        raise ValueError("Cohort mismatch")
    if psutil.virtual_memory().available < 2 * 2**30:
        raise RuntimeError("Require 2 GiB free RAM")
    start, results = time.perf_counter(), {}
    for map_name, old in inventory["maps"].items():
        path = args.assets_dir / "maps" / f"{map_name}.nav"
        if sha(path) != inventory["asset_sha256"][map_name]["nav_sha256"]:
            raise ValueError("NAV changed since inventory")
        nav = NavMesh(path)
        locator = NavigationLocator(nav.area(i) for i in nav.areas["area_id"])
        counts, miss_places, examples = Counter(), Counter(), []
        for entry in index:
            if entry["map"] != map_name:
                continue
            for snapshot, players in zip(rows[entry["id"]]["snapshots"], live_players(rows[entry["id"]]["snapshots"])):
                for player in players:
                    point = player["position"]
                    aid = nav.find_area(tuple(point))
                    old_gap = abs(nav.area(aid)["centroid"][2] - point[2]) if aid is not None else None
                    counts["observations"] += 1
                    for radius in (0, 16, 32):
                        hit = locator.locate(point, max_xy=radius, max_z=64)
                        counts[f"accepted_xy{radius}_z64"] += hit is not None
                        if radius != 32:
                            continue
                        if hit is None:
                            miss_places[player["place"]] += 1
                            counts["rejected_previous_match"] += aid is not None
                        else:
                            counts[hit["status"]] += 1
                            counts["recovered_previous_miss"] += aid is None
                            counts["changed_previous_area"] += aid is not None and hit["area_id"] != aid
                            counts["accepted_previous_centroid_gap_over128"] += old_gap is not None and old_gap > 128
                            counts["changed_area_previous_centroid_gap_over128"] += old_gap is not None and old_gap > 128 and hit["area_id"] != aid
                            if (old_gap is not None and old_gap > 128) and len(examples) < 5:
                                examples.append({"id": entry["id"], "second": snapshot["second"], "place": player["place"],
                                    "position": point, "old_area_id": aid, "old_centroid_abs_dz": old_gap, "bounded_match": hit})
                    if counts["observations"] % 500 == 0 and psutil.virtual_memory().available < 1.5 * 2**30:
                        raise RuntimeError("RAM guard")
        if counts["observations"] != old["live_player_snapshots"]:
            raise ValueError("Player-snapshot denominator differs from inventory")
        results[map_name] = {"counts": dict(counts), "unresolved_by_place": dict(miss_places), "examples": examples}
    result = {"status": "completed_bounded_localization_probe_not_patch_acceptance", "inventory_sha256": sha(args.inventory),
        "source_sha256": {p: sha(ROOT / p) for p in ("app/services/ct_navigation_service.py", "scripts/audit_ct_navigation_repair.py")},
        "protocol": {"xy_tolerances_units": [0, 16, 32], "z_tolerance_units": 64,
            "selection": "valid XY-containing surface first; otherwise nearest 3D surface within both bounds; area-ID tie break; hull 0 only",
            "training": "none; development diagnostics only; bounds are engineering limits, not expert ground truth"},
        "maps": results, "seconds": time.perf_counter() - start,
        "RSS_MiB_at_end": psutil.Process().memory_info().rss / 2**20,
        "limits": ["Original NAV bytes and graph connections are unchanged.",
            "Bounded snaps can cross thin walls; collision and patch compatibility remain unverified.",
            "Unknowns stay masked; higher match coverage is not tactical or geometric accuracy.",
            "Jumping or missing walkable surfaces can remain unresolved; do not fabricate nodes or paths."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"maps": {k: v["counts"] for k, v in results.items()}, "seconds": result["seconds"], "RSS_MiB_at_end": result["RSS_MiB_at_end"]}, indent=2))


if __name__ == "__main__":
    main()
