"""Compare static NAV versions, audit Rafters support, and create an unreviewed zone-role queue."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_ct_map_semantics import sha


def navigation_signature(areas):
    """Compare shape/edge multisets without mistaking area-ID renumbering for geometry change."""
    shapes = {i: (a["hull_index"], tuple(sorted(tuple(v) for v in a["corners"]))) for i, a in areas.items()}
    polygons = Counter(shapes.values())
    edges = Counter()
    for i, area in areas.items():
        for target in area["connections"]:
            if target not in shapes:
                raise ValueError("Dangling NAV connection")
            edges[(shapes[i], shapes[target])] += 1
    return polygons, edges


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--context-dir", type=Path, required=True)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--asset-dirs", type=Path, nargs=2, required=True)
    p.add_argument("--nuke-full-mesh", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    if a.output_dir.exists():
        p.error("Use a new output directory")
    from awpy import NavMesh, VisibilityChecker

    context = json.loads((a.context_dir / "report.json").read_text())
    inventory = json.loads(a.inventory.read_text())
    sidecar = a.context_dir / "ground_navigation.jsonl"
    if sha(sidecar) != context["sidecar_sha256"] or sha(a.inventory) != context["inventory_sha256"]:
        raise ValueError("Ground-state sidecar or inventory changed")
    rows = [json.loads(line) for line in sidecar.read_text().splitlines()]
    if len(rows) != context["live_CT_player_snapshots"]:
        raise ValueError("Observation count changed")
    versions = [json.loads((folder / "manifest.json").read_text())["client_version"] for folder in a.asset_dirs]
    comparisons = {}
    for map_name in inventory["maps"]:
        meshes = []
        for folder, version in zip(a.asset_dirs, versions):
            path = folder / f"{map_name}.nav"
            if sha(path) != context["assets"][version]["maps"][map_name]["nav_sha256"]:
                raise ValueError("NAV differs from ground audit")
            nav = NavMesh(path)
            meshes.append({i: {**nav.area(i), "connections": sorted(nav.area(i)["connections"])} for i in nav.areas["area_id"]})
        first, second = meshes
        shared = first.keys() & second.keys()
        first_shapes, first_edges = navigation_signature(first)
        second_shapes, second_edges = navigation_signature(second)
        comparisons[map_name] = {"versions": versions,
            "exposed_area_records_identical": first == second,
            "areas_only_in_first": len(first.keys() - second.keys()), "areas_only_in_second": len(second.keys() - first.keys()),
            "shared_areas_with_changed_records": sum(first[i] != second[i] for i in shared),
            "polygon_multisets_equal_ignoring_ids": first_shapes == second_shapes,
            "polygons_only_in_first": sum((first_shapes - second_shapes).values()),
            "polygons_only_in_second": sum((second_shapes - first_shapes).values()),
            "directed_edge_multisets_equal_by_polygon_shape": first_edges == second_edges,
            "scope": "Awpy-exposed polygons, hull/flags, adjacency and ladders; excludes unexposed NAV metadata"}
    full = VisibilityChecker(a.nuke_full_mesh)
    support = []
    for row in rows:
        if row["map"] != "de_nuke" or row["place"] != "Rafters" or row["versions"][versions[0]]["status"] != "grounded_unlocalized":
            continue
        q = row["position"]
        blocked = full.is_occluded((q[0], q[1], q[2] + 2), (q[0], q[1], q[2] - 16))
        support.append({"id": row["id"], "tick": row["tick"], "second": row["second"], "position": q,
                        "nearby_static_collision_below": blocked})
    by_place = defaultdict(list)
    for row in rows:
        by_place[(row["map"], row["place"])].append(row)
    queue = []
    for map_name, data in sorted(inventory["maps"].items()):
        for place in data["place_inventory"]:
            observations = by_place[(map_name, place["place"])]
            if len(observations) != place["live_observations"]:
                raise ValueError("Place denominator differs from inventory")
            counts = Counter(row["versions"][versions[0]]["status"] for row in observations)
            examples, used = [], set()
            for row in sorted(observations, key=lambda r: (r["versions"][versions[0]]["status"] != "grounded_unlocalized", r["id"], r["second"])):
                if row["id"] in used:
                    continue
                used.add(row["id"])
                examples.append({k: row[k] for k in ("id", "second", "tick", "position", "is_airborne", "patch_version")})
                if len(examples) == 3:
                    break
            queue.append({"map": map_name, "place": place["place"], "live_observations": len(observations),
                "ground_navigation_counts": dict(counts), "z_min": place["z_min"], "z_max": place["z_max"],
                "current_entity_name_present": place["place"] in data["current_entity_names"],
                "literal_role_candidate": place["label_role_candidate"], "review_status": "unreviewed",
                "approved_roles": None, "reviewer_judgments": [], "examples": examples})
    assert len(queue) == sum(len(m["place_inventory"]) for m in inventory["maps"].values())
    assert sum(x["live_observations"] for x in queue) == len(rows)
    assert all(x["approved_roles"] is None and not x["reviewer_judgments"] for x in queue)
    a.output_dir.mkdir(parents=True)
    review = {"status": "unreviewed_real_data_queue_no_expert_labels", "context_report_sha256": sha(a.context_dir / "report.json"),
        "roles": ["site_a", "site_b", "a_approach", "b_approach", "connector", "ct_spawn", "t_spawn", "other_known", "unknown"],
        "instructions": ["Review map-zone function, not player tactical intent; multiple or unknown roles are allowed.",
            "Literal role candidates are lexical hints, not accepted labels.",
            "Copy this queue before annotation; preserve each independent review, rationale, asset version and evidence.",
            "Each judgment requires reviewer_id, roles, rationale and evidence; conflicts need separate adjudication.",
            "No semantic feature acceptance before independent review and patch/geometry checks."],
        "items": queue}
    review_path = a.output_dir / "role_review_queue.json"
    review_path.write_text(json.dumps(review, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    result = {"status": "completed_static_comparison_and_review_materials_not_semantic_acceptance",
        "script_sha256": sha(Path(__file__)), "context_report_sha256": sha(a.context_dir / "report.json"),
        "nav_comparison": comparisons, "nuke_full_collision_sha256": sha(a.nuke_full_mesh),
        "nuke_full_collision_triangles": full.triangle_count,
        "rafters_grounded_unlocalized": len(support),
        "rafters_with_nearby_static_collision_below": sum(x["nearby_static_collision_below"] for x in support),
        "support_probe": {"start_above_feet_units": 2, "end_below_feet_units": 16, "observations": support,
            "interpretation": "Nearby collision supports a NAV coverage-gap explanation; no walkable-area or connectivity inferred."},
        "review_queue_items": len(queue), "reviewed_items": 0, "review_queue_sha256": sha(review_path),
        "limits": ["Unfiltered world physics excludes separate entity/dynamic collision; no player-hull test.",
            "Current full geometry and unknown exact Demo build prevent treating support probes as historical ground truth.",
            "No NAV augmentation, new model training, human judgments or test-set optimization."]}
    (a.output_dir / "report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("rafters_grounded_unlocalized", "rafters_with_nearby_static_collision_below", "review_queue_items", "reviewed_items")}))


if __name__ == "__main__":
    main()
