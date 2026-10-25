"""Recover time-bounded observer context without changing the frozen CT model input."""

import argparse
from collections import Counter, defaultdict
import gc
import importlib.metadata
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.team_identity_service import canonical_team
from scripts.confirm_ct_generalization import sha, write


def utility_summary(events, start_tick, query_tick):
    """Start at freeze end, excluding post-round throws; ignition is not throwing."""
    selected = events[(events["tick"] >= start_tick) & (events["tick"] <= query_tick)]
    side = selected["user_team_name"].str.upper()
    ct = selected[side == "CT"]
    places = defaultdict(Counter)
    for event in ct.to_dict("records"):
        place = event["user_last_place_name"]
        places[str(event["weapon"])][str(place) if pd.notna(place) and str(place).strip() else "unknown"] += 1
    return {"recorded_ct_throws": dict(Counter(ct["weapon"])),
            "geographical_throw_places": {weapon: dict(counts) for weapon, counts in places.items()},
            "unattributed_recorded_throws": int((~side.isin(["CT", "TERRORIST", "T"])).sum())}


def score_before(history, round_number, start_tick, teams):
    prior = [row for row in history if row["round_number"] < round_number]
    if any(row["end_tick"] > start_tick for row in prior):
        raise ValueError("Previous-round result lies after the current round boundary")
    if len(prior) != round_number - 1 or len(set(teams.values())) != 2 or any(not t for t in teams.values()):
        return None
    if any(not row["winner_team"] or row["winner_team"] not in teams.values() for row in prior):
        return None
    counts = Counter(row["winner_team"] for row in prior)
    return {side: counts[team] for side, team in teams.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-roots", type=Path, nargs="+", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    import psutil
    from app.services.parser_service import TacticalDemoParser

    inventory_path = ROOT / "datasets/evaluation/ct_map_semantics_v8_report.json"
    index_path = ROOT / "output/tagnet/ct_deployment_inputs_p1_v03/sample_index.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    index = json.loads(index_path.read_text(encoding="utf-8"))
    wanted = {row["id"] for row in index}
    paths = defaultdict(set)
    for root in args.demo_roots:
        for path in root.rglob("*.dem"):
            paths[path.name].add(path.resolve())
    sources, demo_receipts, records = {}, [], []
    started = time.monotonic()
    for relative, digest in inventory["dataset_sha256"].items():
        if not relative.endswith("_snapshots.json"):
            continue
        raw_path = ROOT / relative
        if sha(raw_path) != digest:
            raise ValueError("Frozen raw snapshot changed")
        sources[relative] = digest
        document = json.loads(raw_path.read_text(encoding="utf-8"))
        candidates = paths[Path(document["source_demo"]).name]
        if len(candidates) != 1:
            raise ValueError(f"Require one local source demo: {document['source_demo']}")
        path = next(iter(candidates))
        if sha(path) != document["source_demo_sha256"]:
            raise ValueError("Source demo changed")
        if psutil.virtual_memory().available < 2 * 2**30:
            raise RuntimeError("Context parsing requires 2 GiB available RAM; no further demo started")
        tactical = TacticalDemoParser(str(path))
        native = tactical.parser
        if native is None or native.parse_header()["map_name"] != document["map_name"]:
            raise ValueError("Parser/header mismatch")
        ends, boundary = tactical._completed_rounds()
        raw_rounds = {row["round_number"]: row for row in document["rounds"] if row["side"] == "CT"}
        if len(ends) != len(raw_rounds):
            raise ValueError("Native completed-round alignment changed")
        freezes = native.parse_event("round_freeze_end", player=["team_name", "team_clan_name"])
        plants = native.parse_event("bomb_planted", player=["last_place_name"])
        throws = native.parse_event("grenade_thrown", player=["team_name", "last_place_name"])
        if not {"tick", "user_team_name", "user_last_place_name", "weapon"}.issubset(throws.columns):
            raise ValueError("Throw event schema unavailable; do not substitute zero")
        history, teams_by_round = [], {}
        previous = boundary
        for number, end in enumerate(ends.to_dict("records"), 1):
            raw = raw_rounds[number]
            if int(end["tick"]) != raw["end_tick"]:
                raise ValueError("Round-end tick differs from the frozen source")
            choices = freezes[(freezes["tick"] > previous) & (freezes["tick"] <= end["tick"])]
            freeze = choices.sort_values("tick").iloc[0] if len(choices) else None
            teams = {side: canonical_team(freeze[f"{side.lower()}_team_clan_name"])
                     if freeze is not None and pd.notna(freeze[f"{side.lower()}_team_clan_name"]) else ""
                     for side in ("CT", "T")}
            if raw.get("team") and canonical_team(raw["team"]) != teams["CT"]:
                raise ValueError("Event CT team disagrees with frozen roster")
            teams_by_round[number] = teams
            if freeze is not None and raw["freeze_end_tick"] is not None and int(freeze["tick"]) != raw["freeze_end_tick"]:
                raise ValueError("Freeze-end tick differs from the frozen source")
            plant_slice = plants[(plants["tick"] >= int(freeze["tick"])) & (plants["tick"] <= end["tick"])] if len(plants) and freeze is not None else plants.iloc[:0]
            sites = set(plant_slice["user_last_place_name"].dropna()) if len(plant_slice) else set()
            site = {"BombsiteA": "A", "BombsiteB": "B"}.get(next(iter(sites))) if len(sites) == 1 else None
            history.append({"round_number": number, "end_tick": int(end["tick"]),
                            "winner_side_at_previous_round": end["winner"], "winner_team": teams.get(end["winner"]),
                            "planted_site": site, "plant_observation": "round_boundary_unavailable" if freeze is None
                            else "no_plant_recorded" if not len(plant_slice)
                            else "site_observed" if site else "site_unresolved"})
            previous = int(end["tick"])
        selected = [row for row in raw_rounds.values()
                    if f"{document['source_demo_sha256']}:{row['round_number']}:CT" in wanted]
        ticks = sorted({snapshot["tick"] for row in selected for snapshot in row["snapshots"]})
        fields = ["team_name", "team_clan_name", "health", "current_equip_value", "X", "Y", "Z", "pitch", "yaw"]
        frame = native.parse_ticks(fields, ticks=ticks)
        if not {"tick", "steamid", *fields}.issubset(frame.columns):
            raise ValueError("Context tick schema unavailable")
        for raw in selected:
            number = raw["round_number"]
            item = {"id": f"{document['source_demo_sha256']}:{number}:CT", "map": document["map_name"],
                    "freeze_end_tick": raw["freeze_end_tick"],
                    "score_before": score_before(history, number, raw["start_tick"], teams_by_round[number]),
                    "previous_round": history[number - 2] if number > 1 else None, "snapshots": []}
            for snapshot in raw["snapshots"]:
                rows = frame[frame["tick"] == snapshot["tick"]]
                by_id = {str(row["steamid"]): row for row in rows.to_dict("records")}
                equipment = {}
                for side, native_side in (("CT", "CT"), ("T", "TERRORIST")):
                    roster = rows[rows["team_name"].str.upper() == native_side]
                    values = roster["current_equip_value"].to_numpy(dtype=float)
                    equipment[side] = float(values.sum()) if len(roster) == 5 and np.isfinite(values).all() and (values >= 0).all() else None
                angles = []
                for player in snapshot["players"]:
                    row = by_id[player["steamid"]]
                    np.testing.assert_allclose([row["X"], row["Y"], row["Z"]], player["position"], atol=1e-5, rtol=0)
                    np.testing.assert_allclose([row["health"], row["current_equip_value"]],
                                               [player["health"], player["equipment_value"]], atol=1e-5, rtol=0)
                    angle = [row["pitch"], row["yaw"]]
                    angles.append([float(v) for v in angle] if player["alive"] and np.isfinite(angle).all() else None)
                item["snapshots"].append({"second": snapshot["second"], "tick": snapshot["tick"],
                    "equipment_total": equipment, "CT_pitch_yaw_in_frozen_player_order": angles,
                    "utility": utility_summary(throws, raw["freeze_end_tick"], snapshot["tick"])})
            records.append(item)
        demo_receipts.append({"source_demo": document["source_demo"], "sha256": document["source_demo_sha256"],
                              "map": document["map_name"], "rounds": len(ends), "selected_windows": len(selected),
                              "recorded_throws": len(throws), "plant_events": len(plants)})
        print(json.dumps({"completed_demos": len(demo_receipts), "context_windows": len(records),
                          "available_RAM_GiB": round(psutil.virtual_memory().available / 2**30, 2)}), flush=True)
        del frame, native, tactical, freezes, plants, throws
        gc.collect()
    if len(records) != len(wanted) or {row["id"] for row in records} != wanted:
        raise ValueError("Context does not cover the exact frozen 465-window cohort")
    by_id = {row["id"]: row for row in records}
    records = [by_id[row["id"]] for row in index]
    snapshots = [snapshot for row in records for snapshot in row["snapshots"]]
    args.output_dir.mkdir(parents=True)
    write(args.output_dir / "context.json", records)
    result = {"status": "completed", "scope": "observational context availability, not a model input revision",
              "script_sha256": sha(Path(__file__)), "inventory_sha256": sha(inventory_path),
              "sample_index_sha256": sha(index_path), "snapshot_source_sha256": sources,
              "context_sha256": sha(args.output_dir / "context.json"), "demos": demo_receipts,
              "runtime_versions": {name: importlib.metadata.version(name) for name in ("demoparser2", "pandas", "numpy", "psutil")},
              "windows": len(records), "snapshots": len(snapshots),
              "coverage": {"score_before_windows": sum(row["score_before"] is not None for row in records),
                  "CT_equipment_snapshots": sum(s["equipment_total"]["CT"] is not None for s in snapshots),
                  "T_equipment_snapshots": sum(s["equipment_total"]["T"] is not None for s in snapshots),
                  "CT_angle_pairs": sum(angle is not None for s in snapshots for angle in s["CT_pitch_yaw_in_frozen_player_order"]),
                  "throws_with_unattributed_side": sum(s["utility"]["unattributed_recorded_throws"] > 0 for s in snapshots)},
              "limits": ["All data remain the already inspected development cohort.",
                  "Current opponent equipment is privileged observer information, not CT player knowledge; keep separate in any future experiment.",
                  "Live-player angles are recorded view direction, not demonstrated visibility, intent, or tactical duty; dead slots are masked unknown.",
                  "Counts start at freeze end and stop at each query tick; they describe recorded throws, not active smokes/fires. Throw places are geography only.",
                  "No-plant rounds do not reveal an attack site; only an exact previous BombsiteA/B observation is mapped.",
                  "Economy bins, pistol flags, the upstream 25-dimensional context, and new model integration are not implemented here."],
              "elapsed_seconds": time.monotonic() - started,
              "peak_RAM_MiB": psutil.Process().memory_info().peak_wset / 2**20,
              "human_verification": {"status": "pending", "verified_by": None}}
    write(args.output_dir / "report.json", result)
    print(json.dumps({"status": result["status"], "coverage": result["coverage"], "elapsed_seconds": result["elapsed_seconds"]}))


if __name__ == "__main__":
    main()
