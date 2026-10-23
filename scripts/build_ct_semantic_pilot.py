"""Build a local blinded rating pilot from development Demos; no neural-effect claim."""

import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_retrieval_service import nearest_common_candidates
from scripts.audit_ct_map_semantics import sha
from scripts.confirm_ct_generalization import load_records

SEED = 20261023


def order_key(text):
    return hashlib.sha256(f"{SEED}:{text}".encode()).hexdigest()


def select_queries(records, patch_by_id):
    selected = []
    for name in sorted({r["map"] for r in records}):
        rows = sorted((r for r in records if r["map"] == name),
                      key=lambda r: (patch_by_id[r["id"]] != "14174", order_key("query:" + r["id"])))
        seen = set()
        for row in rows:
            if row["series"] not in seen:
                selected.append(row)
                seen.add(row["series"])
                if len(seen) == 2:
                    break
        if len(seen) != 2:
            raise ValueError("Two distinct query series per map required")
    return selected


def candidate_library(query, records, patch_by_id):
    held_series = {r["series"] for r in records if r["map"] == query["map"]}
    library = [r for r in records if r["series"] not in held_series and patch_by_id[r["id"]] == "14174"]
    if len(library) < 5 or any(r["map"] == query["map"] for r in library):
        raise ValueError("Source-only cross-map library needs at least five candidates")
    return library


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--context-dir", type=Path, required=True)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--radar-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    if a.output_dir.exists():
        p.error("Use a new pilot directory")
    from PIL import Image
    import zipfile

    context = json.loads((a.context_dir / "report.json").read_text())
    inventory = json.loads(a.inventory.read_text())
    if sha(a.inventory) != context["inventory_sha256"] or sha(a.context_dir / "ground_navigation.jsonl") != context["sidecar_sha256"]:
        raise ValueError("Context inputs changed")
    run = json.loads((a.run_dir / "report.json").read_text())
    if sha(a.run_dir / "report.json") != inventory["run_report_sha256"]:
        raise ValueError("Frozen run changed")
    records, receipts = load_records([ROOT / path.replace("\\", "/") for path in run["input_report_sha256"]])
    if receipts != {str(ROOT / path.replace("\\", "/")): digest for path, digest in run["input_report_sha256"].items()}:
        raise ValueError("Input reports changed")
    context_rows = [json.loads(line) for line in (a.context_dir / "ground_navigation.jsonl").read_text().splitlines()]
    flags = {(r["id"], r["second"], r["steamid"]): r["is_airborne"] for r in context_rows}
    patches = {r["id"]: r["patch_version"] for r in context_rows}
    raw, demo_map = {}, {}
    for relative, digest in inventory["dataset_sha256"].items():
        path = ROOT / relative
        if sha(path) != digest:
            raise ValueError("Frozen snapshots changed")
        if relative.endswith("_snapshots.json"):
            doc = json.loads(path.read_text())
            demo_map[doc["source_demo_sha256"]] = doc["source_demo"]
            for row in doc["rounds"]:
                if row["side"] == "CT":
                    raw[f"{doc['source_demo_sha256']}:{row['round_number']}:CT"] = row
    if set(patches) != {r["id"] for r in records}:
        raise ValueError("Ground context and frozen record IDs differ")
    manifest = json.loads((a.radar_dir / "manifest.json").read_text())
    if manifest["client_version"] != "2000883" or manifest["patch_version"] != "1.41.7.4":
        raise ValueError("Pilot radar version is fixed")
    asset_receipt = json.loads((ROOT / "datasets/selections/ct_map_assets_v9.json").read_text())
    for filename, spec in asset_receipt["versions"]["2000883"]["metadata"].items():
        if sha(a.radar_dir / filename) != spec["sha256"]:
            raise ValueError("Radar metadata differs from asset receipt")
    spec = manifest["artifacts"]["images.zip"]
    if sha(a.radar_dir / "images.zip") != spec["sha256"]:
        raise ValueError("Radar archive changed")
    map_data = json.loads((a.radar_dir / "map_data.json").read_text())
    maps, map_hashes = {}, {}
    with zipfile.ZipFile(a.radar_dir / "images.zip") as archive:
        for name in run["maps"]:
            meta = map_data[name]
            if not np.isfinite([meta[k] for k in ("pos_x", "pos_y", "scale")]).all() or meta["scale"] <= 0:
                raise ValueError("Invalid radar transform")
            item = {k: meta[k] for k in ("pos_x", "pos_y", "scale")}
            lower = meta.get("verticalsections", {}).get("lower")
            item["lower_z"] = float(lower["AltitudeMax"]) if lower else None
            for suffix in ("", "_lower") if lower else ("",):
                path = a.radar_dir / f"{name}{suffix}.png"
                entries = [n for n in archive.namelist() if Path(n).name == path.name]
                if len(entries) != 1 or hashlib.sha256(archive.read(entries[0])).hexdigest() != sha(path):
                    raise ValueError("Radar image differs from archive")
                with Image.open(path) as picture:
                    if picture.size != (1024, 1024):
                        raise ValueError("1024-pixel radar required")
                item["lower_image" if suffix else "image"] = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
                map_hashes[path.name] = sha(path)
            maps[name] = item

    def display_record(record):
        row = raw[record["id"]]
        identities = sorted(p["steamid"] for p in row["snapshots"][0]["players"])
        frames = []
        for snapshot in row["snapshots"]:
            players = {p["steamid"]: p for p in snapshot["players"]}
            frames.append({"second": snapshot["second"], "players": [{"label": chr(65 + k),
                "position": players[identity]["position"], "place": players[identity]["place"],
                "health": players[identity]["health"], "equipment": players[identity]["equipment_value"],
                "airborne": flags.get((record["id"], snapshot["second"], identity))}
                for k, identity in enumerate(identities)]})
        return {"map": record["map"], "patch": patches[record["id"]], "frames": frames}

    queries, key = [], {}
    for number, query in enumerate(select_queries(records, patches), 1):
        library = candidate_library(query, records, patches)
        qv = query["features"]["targets"].reshape(1, 40)
        qm = query["features"]["target_mask"].reshape(1, 40)
        ranking, _ = nearest_common_candidates(qv, np.array([r["features"]["targets"].ravel() for r in library]),
            qm, np.array([r["features"]["target_mask"].ravel() for r in library]), k=5)
        chosen = {"common_state_5snap": [library[i] for i in ranking[0]],
                  "deterministic_random": sorted(library, key=lambda r: order_key(f"control:{query['id']}:{r['id']}"))[:5]}
        pool = {r["id"]: r for group in chosen.values() for r in group}
        pool = sorted(pool.values(), key=lambda r: order_key(f"blind:{query['id']}:{r['id']}"))
        qid = f"Q{number:02d}"
        labels = {r["id"]: f"C{k + 1:02d}" for k, r in enumerate(pool)}
        queries.append({"id": qid, "query": display_record(query), "candidates": [
            {"id": labels[r["id"]], "record": display_record(r)} for r in pool]})
        key[qid] = {"query": {k: query[k] for k in ("id", "map", "series", "round_number")},
            "library_rounds": len(library), "candidates": {labels[r["id"]]: {k: r[k] for k in ("id", "map", "series", "round_number")} for r in pool},
            "method_rankings": {method: [labels[r["id"]] for r in values] for method, values in chosen.items()}}
    payload = {"version": "ct-semantic-pilot-v9", "maps": maps, "queries": queries, "radar_patch": "14174"}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    payload["payload_sha256"] = hashlib.sha256(encoded.encode()).hexdigest()
    assert len(queries) == 12 and all(5 <= len(q["candidates"]) <= 10 for q in queries)
    assert all(len({v["query"]["series"] for v in key.values() if v["query"]["map"] == name}) == 2 for name in maps)
    a.output_dir.mkdir(parents=True)
    template = ROOT / "scripts/templates/ct_pilot_review.html"
    html = template.read_text(encoding="utf-8").replace("@@PAYLOAD@@", json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c"))
    (a.output_dir / "review.html").write_text(html, encoding="utf-8")
    private_key = {"payload_sha256": payload["payload_sha256"], "queries": key, "demo_by_sha256": demo_map}
    (a.output_dir / "analyst_key.json").write_text(json.dumps(private_key, indent=2) + "\n", encoding="utf-8")
    report = {"status": "prepared_blinded_pilot_without_human_ratings", "seed": SEED,
        "scope": "Development-only annotation-process pilot; common-state retrieval plus random control, not a neural comparison",
        "query_selection": "two distinct series per map; prefer radar-patch-matched rows, then SHA-256 seeded order",
        "library": "patch 14174 only; exclude every series containing the query map",
        "queries": len(queries), "candidate_pairs": sum(len(q["candidates"]) for q in queries),
        "query_patch_counts": dict(Counter(q["query"]["patch"] for q in queries)), "human_ratings": 0,
        "payload_sha256": payload["payload_sha256"], "html_sha256": sha(a.output_dir / "review.html"),
        "private_key_sha256": sha(a.output_dir / "analyst_key.json"), "context_report_sha256": sha(a.context_dir / "report.json"),
        "radar_sha256": map_hashes, "map_data_sha256": sha(a.radar_dir / "map_data.json"),
        "source_sha256": {str(path.relative_to(ROOT)): sha(path) for path in (Path(__file__), template)},
        "limits": ["One Anubis query necessarily uses an older patch because the development map has only two series; warn and allow abstention.",
            "CT-only deployment evidence omits enemy, utility and communication; do not infer tactical intent.",
            "Analyst key and Valve radar assets stay local; do not send analyst materials to reviewers.",
            "Local saved ratings and elapsed time require manual export; no network or automatic submission."]}
    (a.output_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("queries", "candidate_pairs", "query_patch_counts", "human_ratings")}))


if __name__ == "__main__":
    main()
