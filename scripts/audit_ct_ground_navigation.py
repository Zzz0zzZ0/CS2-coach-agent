"""Re-read airborne state without changing v7; compare two version-pinned NAV/LOS assets."""

import argparse
from collections import Counter, defaultdict
import gc
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_ground_navigation_service import grounded_candidate
from app.services.ct_navigation_service import NavigationLocator
from scripts.audit_ct_map_semantics import live_players, sha
from scripts.confirm_ct_generalization import load_records


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--asset-dirs", type=Path, nargs=2, required=True)
    p.add_argument("--demo-roots", type=Path, nargs="+", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    if a.output_dir.exists():
        p.error("Use a new output directory")
    from awpy import NavMesh, VisibilityChecker
    from demoparser2 import DemoParser
    import psutil
    import numpy as np

    if psutil.virtual_memory().available < 2 * 2**30:
        raise RuntimeError("Require 2 GiB free RAM")
    start = time.perf_counter()
    inventory = json.loads(a.inventory.read_text(encoding="utf-8"))
    report = json.loads((a.run_dir / "report.json").read_text(encoding="utf-8"))
    if sha(a.run_dir / "report.json") != inventory["run_report_sha256"]:
        raise ValueError("v7 report changed")
    folders = [ROOT / path.replace("\\", "/") for path in report["input_report_sha256"]]
    records, receipts = load_records(folders)
    if receipts != {str(ROOT / path.replace("\\", "/")): digest for path, digest in report["input_report_sha256"].items()}:
        raise ValueError("v7 input reports changed")
    index = [{k: v for k, v in r.items() if k != "features"} for r in records]
    del records
    if index != json.loads((a.run_dir / "sample_index.json").read_text(encoding="utf-8")):
        raise ValueError("v7 ordered index changed")
    wanted, paths, documents = {e["id"] for e in index}, defaultdict(set), []
    for root in a.demo_roots:
        for path in root.rglob("*.dem"):
            paths[path.name].add(path.resolve())
    for relative, digest in inventory["dataset_sha256"].items():
        path = ROOT / relative
        if sha(path) != digest:
            raise ValueError("Frozen input changed")
        if relative.endswith("_snapshots.json"):
            documents.append(json.loads(path.read_text(encoding="utf-8")))
    manifests, assets, locators, checkers = [], {}, {}, {}
    for folder in a.asset_dirs:
        manifest = json.loads((folder / "manifest.json").read_text())
        version = manifest["client_version"]
        if version in assets:
            raise ValueError("Two distinct versions required")
        manifests.append(manifest)
        assets[version] = {"manifest_sha256": sha(folder / "manifest.json"), "maps": {}}
        locators[version], checkers[version] = {}, {}
        for archive in ("navs.zip", "geometry.zip"):
            spec = manifest["artifacts"][archive]
            if (folder / archive).stat().st_size != spec["bytes"] or sha(folder / archive) != spec["sha256"]:
                raise ValueError("Asset archive hash mismatch")
        for map_name in report["maps"]:
            nav_path, mesh_path = folder / f"{map_name}.nav", folder / f"{map_name}.mesh"
            for archive, path in (("navs.zip", nav_path), ("geometry.zip", mesh_path)):
                with zipfile.ZipFile(folder / archive) as bundle:
                    members = [n for n in bundle.namelist() if Path(n).name == path.name]
                    if len(members) != 1 or hashlib.sha256(bundle.read(members[0])).hexdigest() != sha(path):
                        raise ValueError("Extracted asset differs from verified archive")
            nav = NavMesh(nav_path)
            locators[version][map_name] = NavigationLocator(nav.area(i) for i in nav.areas["area_id"])
            checkers[version][map_name] = VisibilityChecker(mesh_path)
            assets[version]["maps"][map_name] = {"nav_sha256": sha(nav_path), "mesh_sha256": sha(mesh_path),
                "nav_areas": nav.area_count, "visual_triangles": checkers[version][map_name].triangle_count}
    output, summary, demos, checked = [], {}, [], set()
    counters = {v: defaultdict(Counter) for v in assets}
    per_place = {v: defaultdict(Counter) for v in assets}
    for document in documents:
        digest = document["source_demo_sha256"]
        candidates = paths[document["source_demo"]]
        if len(candidates) != 1 or digest in checked:
            raise ValueError("Missing, ambiguous or duplicate Demo")
        path = next(iter(candidates))
        if sha(path) != digest:
            raise ValueError("Demo checksum changed")
        checked.add(digest)
        selected = [r for r in document["rounds"] if r["side"] == "CT" and f"{digest}:{r['round_number']}:CT" in wanted]
        ticks = sorted({s["tick"] for r in selected for s in r["snapshots"]})
        parser = DemoParser(str(path))
        header = parser.parse_header()
        patch = header["patch_version"]
        if header["map_name"] != document["map_name"]:
            raise ValueError("Demo header map differs from frozen snapshot")
        frame = parser.parse_ticks(["is_airborne", "X", "Y", "Z", "health", "current_equip_value", "last_place_name"], ticks=ticks)
        lookup = {}
        for row in frame.to_dict("records"):
            key = (row["tick"], str(row["steamid"]))
            if key in lookup:
                raise ValueError("Duplicate parsed tick/player")
            lookup[key] = row
        matched = 0
        for row in selected:
            identity = f"{digest}:{row['round_number']}:CT"
            for snapshot, players in zip(row["snapshots"], live_players(row["snapshots"])):
                for player in snapshot["players"]:
                    raw = lookup[(snapshot["tick"], player["steamid"])]
                    if not np.allclose([raw[k] for k in ("X", "Y", "Z")], player["position"], rtol=0, atol=1e-6) or raw["health"] != player["health"] or raw["current_equip_value"] != player["equipment_value"] or raw["last_place_name"] != player["place"]:
                        raise ValueError("New parse differs from frozen snapshot")
                    matched += 1
                for player in players:
                    raw = lookup[(snapshot["tick"], player["steamid"])]
                    flag = raw["is_airborne"]
                    if flag is not None and not isinstance(flag, (bool, np.bool_)):
                        raise ValueError("Nonboolean airborne field")
                    airborne = None if flag is None else bool(flag)
                    entry = {"id": identity, "second": snapshot["second"], "tick": snapshot["tick"],
                        "steamid": player["steamid"], "map": document["map_name"], "place": player["place"],
                        "position": player["position"], "is_airborne": airborne, "patch_version": patch, "versions": {}}
                    for manifest in manifests:
                        version, map_name = manifest["client_version"], document["map_name"]
                        locator, checker = locators[version][map_name], checkers[version][map_name]
                        hit = locator.locate(player["position"])
                        result = grounded_candidate(locator, player["position"], airborne, checker.is_occluded)
                        same_patch = manifest["patch_version"].replace(".", "") == patch
                        entry["versions"][version] = {**result, "patch_number_matches": same_patch,
                            "ungated_bounded_match": hit is not None}
                        counter = counters[version][map_name]
                        counter["observations"] += 1
                        counter[result["status"]] += 1
                        counter["ungated_bounded_match"] += hit is not None
                        counter["grounded_bounded_match"] += airborne is False and hit is not None
                        counter["airborne_bounded_match"] += airborne is True and hit is not None
                        counter["patch_number_matches"] += same_patch
                        if hit is None:
                            per_place[version][(map_name, player["place"])]["airborne" if airborne else "grounded" if airborne is False else "unknown"] += 1
                    output.append(entry)
        demos.append({"demo": document["source_demo"], "sha256": digest, "map": document["map_name"],
                      "patch_version": patch, "frozen_player_snapshots_rechecked": matched, "ticks": len(ticks)})
        del parser, frame, lookup
        gc.collect()
        if psutil.virtual_memory().available < 1.5 * 2**30:
            raise RuntimeError("RAM guard")
        print(document["source_demo"], "checked", matched, flush=True)
    if len(output) != sum(m["live_player_snapshots"] for m in inventory["maps"].values()):
        raise ValueError("Observation denominator mismatch")
    for version in assets:
        summary[version] = {"by_map": {k: dict(v) for k, v in counters[version].items()},
            "unlocalized_by_place_and_ground_state": [{"map": k[0], "place": k[1], **dict(v)} for k, v in sorted(per_place[version].items())]}
    a.output_dir.mkdir(parents=True)
    sidecar = a.output_dir / "ground_navigation.jsonl"
    sidecar.write_text("".join(json.dumps(row, allow_nan=False) + "\n" for row in output), encoding="utf-8")
    result = {"status": "completed_ground_state_and_two_version_development_audit", "inventory_sha256": sha(a.inventory),
        "source_sha256": {p: sha(ROOT / p) for p in ("scripts/audit_ct_ground_navigation.py", "app/services/ct_ground_navigation_service.py", "app/services/ct_navigation_service.py")},
        "environment": {p: importlib.metadata.version(p) for p in ("awpy", "demoparser2", "numpy")},
        "protocol": {"xy_max_units": 32, "z_max_units": 64, "ray_above_feet_units": 16,
            "airborne_source": "demoparser2 is_airborne (m_hGroundEntity); no velocity estimates from sparse ticks",
            "ground_gate": "airborne and unknown flags excluded from navigation candidates; spatial/role observations retained",
            "visibility_mesh": "visual occluders, not player collision; a clear ray is only a candidate"},
        "assets": assets, "manifests": manifests, "demos": demos, "maps": summary,
        "live_CT_player_snapshots": len(output), "sidecar_sha256": sha(sidecar),
        "seconds": time.perf_counter() - start, "RSS_MiB_at_end": psutil.Process().memory_info().rss / 2**20,
        "limits": ["Matching patch numbers do not identify the Demo server's exact client build or map checksum.",
            "Visual meshes omit clips/glass and are decimated; no full player-hull walkability or path guarantee.",
            "Airborne is an engine/parser flag, not expert tactical gold; unlocalized grounded observations remain unknown.",
            "All nine series remain development data; no new model training, human labels or unseen test."]}
    (a.output_dir / "report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"observations": len(output), "seconds": result["seconds"], "RSS_MiB_at_end": result["RSS_MiB_at_end"]}))


if __name__ == "__main__":
    main()
