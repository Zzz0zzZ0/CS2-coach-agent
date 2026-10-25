import pandas as pd
import pytest

from scripts.audit_ct_context_availability import score_before, utility_summary


def test_throw_counts_obey_query_tick_and_round_boundary_and_keep_unknown():
    events = pd.DataFrame([
        (9, "CT", "smokegrenade", "A"), (10, "CT", "smokegrenade", "A"),
        (20, "CT", "flashbang", None), (21, "CT", "incgrenade", "B"),
        (20, "TERRORIST", "smokegrenade", "B"), (20, None, "flashbang", "Mid"),
    ], columns=["tick", "user_team_name", "weapon", "user_last_place_name"])
    result = utility_summary(events, 10, 20)
    assert result["recorded_ct_throws"] == {"smokegrenade": 1, "flashbang": 1}
    assert result["geographical_throw_places"]["flashbang"] == {"unknown": 1}
    assert result["unattributed_recorded_throws"] == 1
    assert utility_summary(events.iloc[:3], 10, 20)["recorded_ct_throws"] == result["recorded_ct_throws"]


def test_score_uses_team_identity_across_side_switches_and_excludes_current_result():
    history = [{"round_number": 1, "end_tick": 10, "winner_team": "alpha"},
               {"round_number": 2, "end_tick": 20, "winner_team": "beta"}]
    assert score_before(history, 2, 10, {"CT": "beta", "T": "alpha"}) == {"CT": 0, "T": 1}
    assert score_before(history, 1, 0, {"CT": "alpha", "T": "beta"}) == {"CT": 0, "T": 0}
    assert score_before(history, 2, 10, {"CT": "", "T": "alpha"}) is None
    with pytest.raises(ValueError, match="boundary"):
        score_before(history, 2, 9, {"CT": "beta", "T": "alpha"})
