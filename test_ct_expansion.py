"""模拟示例: split identity and clustered uncertainty contracts."""

import pandas as pd
import pytest

from app.services.ct_evaluation_service import error_totals, paired_series_bootstrap
from scripts.ct_experiment_data import audit_source, canonical_pair


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
