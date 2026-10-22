"""模拟示例: split identity and clustered uncertainty contracts."""

import pandas as pd
import pytest
import json
import hashlib

from app.services.ct_evaluation_service import error_totals, paired_series_bootstrap
from scripts.ct_experiment_data import audit_source, canonical_pair
from app.services.team_identity_service import canonical_team


def test_source_aliases_and_duplicates_ignore_player_order():
    rows = []
    for split, name, reverse in [("train", "monte-vs-navi_dust2", False), ("val", "natus-vincere-vs-monte_dust2", True)]:
        for slot in (range(5) if not reverse else reversed(range(5))):
            rows.append({"sample_id": split, "match_id": name, "split": split, "second": 10,
                         "place": "Middle", "X": slot, "Y": 0, "Z": 0, "health": 100, "current_equip_value": 1000})
    report = audit_source(pd.DataFrame(rows))
    assert len(report["exact_cross_split_duplicate_groups"]) == 1
    assert len(report["cross_split_pair_aliases"]) == 1
    assert canonical_pair("navi-vs-monte_dust2") == canonical_pair("monte-vs-natus-vincere_dust2")


def test_series_bootstrap_does_not_weight_by_round_count():
    base = error_totals([[1] * 8], [[0] * 8], [[1] * 8])
    good = error_totals([[0] * 8], [[0] * 8], [[1] * 8])
    bad = error_totals([[2] * 8], [[0] * 8], [[1] * 8])
    result = paired_series_bootstrap([good] * 20 + [bad], [base] * 21, ["A"] * 20 + ["B"])
    assert result["series_count"] == 2
    assert result["improvement_pct"] == pytest.approx(-100)
    assert result["descriptive_95pct_interval"] == pytest.approx([-300, 100])
    assert paired_series_bootstrap([good], [base], ["A"])["descriptive_95pct_interval"] is None


@pytest.mark.parametrize("problem", [None, "checksum", "duplicate", "series", "limit"])
def test_input_manifest_isolated_and_checksummed(tmp_path, problem):
    from scripts.run_ct_expansion import read_input_manifest
    demo = tmp_path / "source.dem"; demo.write_bytes(b"synthetic demo fixture")
    row = {"series": "one", "demo_path": str(demo), "sha256": hashlib.sha256(demo.read_bytes()).hexdigest()}
    protocol = {"matches": [{"match_id": "one"}], "limits": {"new_demos_max": 2}}
    rows = [row]
    if problem == "checksum":
        row["sha256"] = "invalid"
    elif problem == "duplicate":
        rows.append(dict(row))
    elif problem == "series":
        row["series"] = "unselected"
    elif problem == "limit":
        protocol["limits"]["new_demos_max"] = 0
    path = tmp_path / "input.json"; path.write_text(json.dumps({"files": rows}))
    if problem:
        with pytest.raises(ValueError):
            read_input_manifest(path, protocol)
    else:
        assert read_input_manifest(path, protocol) == [("one", demo.resolve())]


def test_team_aliases_are_shared_and_unknown_brands_stay_distinct():
    assert canonical_team("Team Falcons") == canonical_team("Falcons")
    assert canonical_team("NAVI") == canonical_team("Natus Vincere")
    assert canonical_team("PVISION") == canonical_team("PARIVISION")
    assert canonical_pair("legacy-vs-team-falcons_dust2") == canonical_pair("falcons-vs-legacy_dust2")
    assert canonical_team("Team Unknown") == "team-unknown"
