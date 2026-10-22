"""Shared source loading and conservative identity audit for CT experiments."""

import hashlib

import pandas as pd

from app.services.ct_feature_service import feature_sequence
from app.services.team_identity_service import canonical_team


def canonical_pair(name):
    teams = name.removesuffix("_dust2").split("-vs-")
    if len(teams) != 2:
        raise ValueError("Expected an upstream team-pair match label")
    return tuple(sorted(canonical_team(team) for team in teams))


def audit_source(frame):
    entries = []
    for sid, rows in frame.groupby("sample_id", sort=True):
        content = rows.sort_values(["second", "X", "Y", "Z", "health", "current_equip_value", "place"])[
            ["second", "place", "X", "Y", "Z", "health", "current_equip_value"]].to_json(orient="values", double_precision=12)
        entries.append({"id": sid, "match": rows.iloc[0]["match_id"], "split": rows.iloc[0]["split"],
                        "content_sha256": hashlib.sha256(content.encode()).hexdigest()})
    samples = pd.DataFrame(entries)
    duplicates = [rows.to_dict("records") for _, rows in samples.groupby("content_sha256") if rows["split"].nunique() > 1]
    pairs = {}
    for split, rows in frame.groupby("split"):
        for match in sorted(rows["match_id"].unique()):
            pairs.setdefault(canonical_pair(match), []).append({"match": match, "split": split})
    aliases = [{"canonical_pair": list(pair), "labels": labels, "status": "possible series alias; not proof of shared series"}
               for pair, labels in pairs.items() if len({row["split"] for row in labels}) > 1]
    return {"samples": len(samples), "matches": int(frame["match_id"].nunique()),
            "exact_cross_split_duplicate_groups": duplicates, "cross_split_pair_aliases": aliases,
            "claim": "Exact duplicates checked independent of player order; series identity cannot be certified without original source metadata"}


def load_source(path):
    frame = pd.read_parquet(path)
    report = audit_source(frame)
    groups = {name: [] for name in ("train", "val", "test")}
    for sid, rows in frame.groupby("sample_id", sort=True):
        snapshots = [{"second": int(second), "players": [
            {"steamid": p.player_id, "position": [p.X, p.Y, p.Z], "health": p.health,
             "equipment_value": p.current_equip_value, "place": p.place}
            for p in time.sort_values("player_slot").itertuples()]}
            for second, time in rows.groupby("second", sort=True)]
        groups[rows.iloc[0]["split"]].append({"id": sid, "series": rows.iloc[0]["match_id"],
            "map": "de_dust2", "features": feature_sequence(snapshots), "round_number": int(rows.iloc[0]["round_num"])})
    return groups, report
