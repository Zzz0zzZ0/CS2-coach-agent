"""Audit the exact v7 CT cohort against local map assets; never certify patch compatibility."""

import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import re
import statistics
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
EXACT_ROLES = {"BombsiteA": "site_a", "BombsiteB": "site_b", "CTSpawn": "ct_spawn", "TSpawn": "t_spawn"}


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def named_places(text):
    """Read Source2Viewer entity dumps; entity origins are not volume boundaries."""
    names = Counter()
    for block in re.split(r"^====\d+====\s*$", text, flags=re.M):
        if re.search(r'^classname\s+"env_cs_place"\s*$', block, re.M):
            matches = re.findall(r'^place_name\s+"([^"\r\n]+)"\s*$', block, re.M)
            if len(matches) != 1:
                raise ValueError("Place entity requires one nonempty place_name")
            names[matches[0]] += 1
    if not names:
        raise ValueError("No env_cs_place entities in dump")
    return names


def lower_altitude(text):
    block = re.search(r'"lower"\s*\{([^{}]*)\}', re.sub(r"//[^\n]*", "", text))
    if block is None:
        return None
    value = re.findall(r'"AltitudeMax"\s*"(-?\d+(?:\.\d+)?)"', block[1])
    if len(value) != 1 or not math.isfinite(float(value[0])):
        raise ValueError("Malformed lower-level overview altitude")
    return float(value[0])


def live_players(snapshots):
    if [s["second"] for s in snapshots] != [10, 12, 15, 18, 20]:
        raise ValueError("Expected five ordered opening snapshots")
    identities, result = None, []
    for snapshot in snapshots:
        players = snapshot["players"]
        ids = {str(p["steamid"]) for p in players}
        if len(players) != 5 or len(ids) != 5 or (identities is not None and ids != identities):
            raise ValueError("Five consistent distinct CT players required")
        identities = ids
        live = []
        for player in players:
            xyz, hp, place = player["position"], player["health"], player.get("place")
            if len(xyz) != 3 or not all(math.isfinite(x) for x in xyz) or not math.isfinite(hp) or not 0 <= hp <= 100:
                raise ValueError("Invalid coordinates or health")
            if not isinstance(place, str) or not place.strip():
                raise ValueError("Missing place name")
            if bool(player["alive"]) != (hp > 0):
                raise ValueError("Alive flag disagrees with health")
            if hp > 0:
                live.append(player)
        if not live:
            raise ValueError("No live CT players")
        result.append(live)
    return result


def audit_map(records, nav, names, altitude):
    places, misses, heights, series = defaultdict(list), Counter(), [], set()
    lower_counts = Counter()
    pairs, stacked, windows, examples = 0, 0, set(), []
    for entry, row in records:
        series.add(entry["series"])
        for snapshot, players in zip(row["snapshots"], live_players(row["snapshots"])):
            for player in players:
                xyz, place = player["position"], player["place"]
                places[place].append(xyz[2])
                area_id = nav.find_area(tuple(xyz))
                if area_id is None:
                    misses[place] += 1
                else:
                    heights.append(abs(nav.area(area_id)["centroid"][2] - xyz[2]))
                if altitude is not None and xyz[2] < altitude:
                    lower_counts[place] += 1
            for i, a in enumerate(players):
                for b in players[i + 1:]:
                    pairs += 1
                    xy = math.dist(a["position"][:2], b["position"][:2])
                    dz = abs(a["position"][2] - b["position"][2])
                    if xy <= 200 and dz >= 160:
                        stacked += 1
                        windows.add(entry["id"])
                        if len(examples) < 5:
                            examples.append({"id": entry["id"], "second": snapshot["second"],
                                             "places": [a["place"], b["place"]], "xy": xy, "abs_dz": dz})
    total = sum(map(len, places.values()))
    unknown = sum(len(v) for k, v in places.items() if k not in EXACT_ROLES)
    return {
        "rounds": len(records), "series": sorted(series), "live_player_snapshots": total,
        "baseline_other_count": unknown, "baseline_other_fraction": unknown / total,
        "places_absent_from_current_entities": sorted(set(places) - names.keys()),
        "current_entity_names": dict(sorted(names.items())),
        "place_inventory": [{"place": name, "live_observations": len(z),
            "z_min": min(z), "z_median": statistics.median(z), "z_max": max(z),
            "current_nav_misses": misses[name], "current_radar_lower_observations": lower_counts[name] if altitude is not None else None,
            "label_role_candidate": EXACT_ROLES.get(name), "semantic_review_status": "unreviewed"}
            for name, z in sorted(places.items())],
        "current_nav_probe": {"version": nav.version, "sub_version": nav.sub_version, "areas": nav.area_count,
            "no_xy_area": sum(misses.values()), "assigned": len(heights),
            "centroid_abs_dz_median": statistics.median(heights) if heights else None,
            "centroid_abs_dz_max": max(heights) if heights else None,
            "centroid_abs_dz_over_128": sum(h > 128 for h in heights)},
        "vertical_diagnostic": {"xy_max_units": 200, "abs_dz_min_units": 160,
            "live_pair_snapshots": pairs, "close_xy_large_dz_pairs": stacked, "affected_rounds": len(windows),
            "examples": examples, "current_radar_lower_altitude_max": altitude,
            "places_on_both_sides_of_current_radar_split": sorted(k for k, z in places.items() if 0 < lower_counts[k] < len(z)) if altitude is not None else []}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--extractor", type=Path, required=True)
    parser.add_argument("--demo-roots", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new receipt path")
    from awpy import NavMesh
    from demoparser2 import DemoParser

    report = json.loads((args.run_dir / "report.json").read_text(encoding="utf-8"))
    expected_index = json.loads((args.run_dir / "sample_index.json").read_text(encoding="utf-8"))
    frozen_inputs = json.loads((ROOT / "datasets/evaluation/ct_error_audit_v7_report.json").read_text(encoding="utf-8"))["dataset_artifact_sha256"]
    frozen_inputs = {"output/tagnet/" + key.replace("\\", "/").split("/output/tagnet/", 1)[1]: value
                     for key, value in frozen_inputs.items()}
    steam_info = dict(line.split("=", 1) for line in (args.game_root / "steam.inf").read_text().splitlines() if "=" in line)
    demo_paths = defaultdict(set)
    for root in args.demo_roots:
        for path in root.rglob("*.dem"):
            demo_paths[path.name].add(path.resolve())
    documents, by_map, index, inputs = [], defaultdict(list), [], {}
    seen_demos = set()
    for relative, expected_sha in report["input_report_sha256"].items():
        folder = ROOT / relative.replace("\\", "/")
        if sha(folder / "report.json") != expected_sha:
            raise ValueError("v7 input report changed")
        for name, entries in sorted(json.loads((folder / "sample_index.json").read_text(encoding="utf-8")).items()):
            if name in ("source_train", "dust2_test"):
                continue
            path = folder / f"{name}_snapshots.json"
            doc = json.loads(path.read_text(encoding="utf-8"))
            for artifact in (folder / "sample_index.json", path, folder / f"{name}_timing.json"):
                key = artifact.relative_to(ROOT).as_posix()
                if sha(artifact) != frozen_inputs[key]:
                    raise ValueError(f"v7 artifact changed: {key}")
                inputs[key] = sha(artifact)
            digest = doc["source_demo_sha256"]
            if digest in seen_demos:
                raise ValueError("Duplicate Demo")
            seen_demos.add(digest)
            candidates = demo_paths[doc["source_demo"]]
            if len(candidates) != 1:
                raise ValueError(f"Require exactly one raw Demo: {doc['source_demo']}")
            demo = next(iter(candidates))
            if sha(demo) != digest:
                raise ValueError("Raw Demo checksum differs")
            header = DemoParser(str(demo)).parse_header()
            if header["map_name"] != doc["map_name"]:
                raise ValueError("Demo/map mismatch")
            same_patch = header["patch_version"] == steam_info["PatchVersion"].replace(".", "")
            documents.append({"demo": doc["source_demo"], "sha256": digest, "map": header["map_name"],
                              "patch_version": header["patch_version"],
                              "compatibility": "unverified_same_patch_number" if same_patch else "unverified_patch_mismatch"})
            rows = {r["round_number"]: r for r in doc["rounds"] if r["side"] == "CT"}
            if len(rows) != sum(r["side"] == "CT" for r in doc["rounds"]):
                raise ValueError("Duplicate CT round")
            for entry in entries:
                row = rows[entry["round_number"]]
                if not entry.get("timing_passed") or row["status"] != "ok" or entry["map"] != doc["map_name"] or entry["id"] != f"{digest}:{row['round_number']}:CT":
                    raise ValueError("Invalid CT cohort entry")
                index.append(entry)
                by_map[entry["map"]].append((entry, row))
    if index != expected_index or len({e["id"] for e in index}) != len(index):
        raise ValueError("Cohort does not equal the frozen v7 ordered index")
    maps, assets = {}, {}
    for map_name, records in sorted(by_map.items()):
        nav_path = args.assets_dir / "maps" / f"{map_name}.nav"
        entity_path = args.assets_dir / f"{map_name}.entities.txt"
        overview_path = args.assets_dir / "resource/overviews" / f"{map_name}.txt"
        if struct.unpack("<I", nav_path.read_bytes()[:4])[0] != 0xFEEDFACE:
            raise ValueError("Invalid NAV magic")
        nav = NavMesh(nav_path)
        maps[map_name] = audit_map(records, nav, named_places(entity_path.read_text(encoding="utf-8")),
                                   lower_altitude(overview_path.read_text(encoding="utf-8")))
        assets[map_name] = {"map_vpk_sha256": sha(args.game_root / "maps" / f"{map_name}.vpk"),
            "nav_sha256": sha(nav_path), "entity_dump_sha256": sha(entity_path), "overview_sha256": sha(overview_path)}
    result = {"status": "completed_development_inventory_not_semantic_acceptance", "cohort": {
        "rounds": len(index), "series": sorted({e["series"] for e in index}), "demos": len(documents)},
        "run_report_sha256": sha(args.run_dir / "report.json"), "script_sha256": sha(Path(__file__)),
        "dataset_sha256": inputs, "asset_sha256": assets, "steam_info": steam_info,
        "steam_info_sha256": sha(args.game_root / "steam.inf"), "extractor_sha256": sha(args.extractor),
        "environment": {p: importlib.metadata.version(p) for p in ("awpy", "polars", "demoparser2")},
        "python": sys.version, "demo_headers": documents, "maps": maps,
        "limits": ["Current static map assets are newer than the audited Demos; compatibility remains unverified.",
            "NAV area assignment and centroid height are diagnostics, not validated floor or walk-distance truth.",
            "Named-place membership does not validate volume geometry or tactical roles; all semantic reviews are pending.",
            "Only the frozen eligible CT cohort is counted; T-side data is excluded.",
            "No new model, training, human labels, navigation-distance features, or unseen test outcomes."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"rounds": len(index), "maps": {k: {f: v[f] for f in ("rounds", "baseline_other_fraction", "current_nav_probe")} for k, v in maps.items()}}, indent=2))


if __name__ == "__main__":
    main()
