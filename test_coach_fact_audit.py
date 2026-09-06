import asyncio

from app.agentic.nodes.coach_node import _render_report, _select_priorities
from app.domain.analysis_models import MatchMetrics
from app.services.metrics_service import calculate_metrics, build_current_match_evidence


def roster_round(side, winner, complete=True):
    return {"winner": winner, "participants_complete": complete,
            "participants": [{"name": f"{team}{i}", "steamid": f"{team}{i}", "team": team, "side": played}
                             for team, played in (("A", side), ("B", "T" if side == "CT" else "CT"))
                             for i in range(5)]}


def test_side_rates_use_actual_exposure_and_keep_zero_wins():
    rounds = [roster_round("CT", "CT") for _ in range(9)] + [roster_round("CT", "T") for _ in range(3)]
    rounds += [roster_round("T", "T") for _ in range(4)] + [roster_round("T", "CT")]
    metrics = calculate_metrics(rounds)
    assert metrics["rounds_won_by_team"] == {"A": 13, "B": 4}
    assert metrics["side_performance_by_team"]["A"] == {
        "CT": {"rounds": 12, "known_outcomes": 12, "round_wins": 9, "win_rate_pct": 75.0},
        "T": {"rounds": 5, "known_outcomes": 5, "round_wins": 4, "win_rate_pct": 80.0}}
    assert MatchMetrics(**metrics).side_performance_by_team == metrics["side_performance_by_team"]
    report = _render_report(metrics, ["side_transition"])
    assert "A T 4/5（80.0%）" in report and "A CT 9/12（75.0%）" in report
    assert "优先检查低胜局一侧" not in report
    assert "known_outcomes" in build_current_match_evidence({"match_id": "m", "map_name": "Dust2"}, metrics)[0]["content"]
    zero = calculate_metrics([roster_round("T", "T")])
    assert zero["side_performance_by_team"]["B"]["CT"]["round_wins"] == 0


def test_side_unknown_outcomes_and_incomplete_rosters_are_not_losses():
    metrics = calculate_metrics([roster_round("CT", "Unknown"), roster_round("CT", "T"), roster_round("T", "T", False)])
    assert metrics["side_performance_by_team"]["A"] == {
        "CT": {"rounds": 2, "known_outcomes": 1, "round_wins": 0, "win_rate_pct": 0.0}}
    unknown = calculate_metrics([roster_round("CT", "Unknown")])
    assert unknown["side_performance_by_team"]["A"]["CT"]["win_rate_pct"] is None
    assert "0/0（胜率不可用）" in _render_report(unknown, ["side_transition"])
    ambiguous = roster_round("T", "T")
    ambiguous["participants"][0]["team"] = "third"
    assert calculate_metrics([ambiguous])["side_performance_by_team"] == {}
    assert "分母不可用" in _render_report({}, ["side_transition"])


def test_self_flash_counts_are_explicitly_labeled_in_evidence_and_report():
    row = roster_round("CT", "CT")
    row["flash_blinds"] = [{"attacker": "A0", "victim": victim, "attacker_team": "A", "victim_team": team}
                           for victim, team in (("A0", "A"), ("A1", "A"), ("B0", "B"))]
    metrics = calculate_metrics([row])
    assert metrics["team_flash_blinds_by_team"] == {"A": 2}
    assert metrics["enemy_flash_blinds_by_team"] == {"A": 1}
    assert "己方受闪（含自己）：A 2" in _render_report(metrics, ["utility_review"])
    assert "same-team blinds (including self)" in build_current_match_evidence({}, metrics)[0]["content"]


def test_coach_model_sees_denominators_and_self_flash_definition():
    class Probe:
        def bind_tools(self, _):
            return self

        async def ainvoke(self, prompt):
            assert '"known_outcomes": 1' in prompt
            assert "includes self-blinds" in prompt
            return type("Reply", (), {"tool_calls": [{"name": "select_coaching_priorities", "args": {"priority_ids": ["opening_followup", "side_transition"]}}]})()

    metrics = calculate_metrics([roster_round("CT", "CT")])
    _, source, _ = asyncio.run(_select_priorities(Probe(), metrics))
    assert source == "qwen_tool_call"
