"""Development faults for source/report consistency; no frozen benchmark edits."""
import asyncio
from copy import deepcopy

import pytest

from app.agentic.nodes.analyst_node import create_analyst_node
from app.agentic.nodes.coach_node import create_coach_node
from app.agentic.nodes.verify_node import create_verify_node
from app.services.metrics_service import calculate_metrics, build_current_match_evidence


def source_match():
    rounds = []
    for number, winner in ((10, "T"), (20, "CT"), (30, "Unknown")):
        rounds.append({
            "round_number": number, "winner": winner,
            "reason": "bomb_defused" if number == 20 else "",
            "participants_complete": True,
            "participants": [{"team": team, "side": side, "name": f"{team}{i}"}
                             for team, side in (("A", "T"), ("B", "CT")) for i in range(5)],
            "kills": [{"killer": "A0", "victim": "B0", "killer_team": "A", "victim_team": "B",
                       "killer_side": "T", "victim_side": "CT", "weapon": "ak47", "tick": 10}],
            "plants": [{"planter_team": "A", "planter_side": "T", "site": "A"}],
        })
    return {"match_id": "development-match", "map_name": "Ancient", "rounds": rounds}


def render(state):
    state.update(asyncio.run(create_analyst_node(None)(state)))
    state.update(asyncio.run(create_coach_node(None)(state)))
    return state


def analysis_state():
    match = source_match()
    metrics = calculate_metrics(match["rounds"])
    return render({"match": match, "metrics": metrics,
                   "current_evidence": build_current_match_evidence(match, metrics)})


def verify(state):
    return asyncio.run(create_verify_node()(state))["verification_report"]


def checks(report):
    return {item["id"]: item for item in report["checks"]}


def test_unknown_outcomes_do_not_become_conversion_losses():
    state = analysis_state()
    for name in ("opening_duels_by_team", "post_plant_by_team"):
        assert state["metrics"][name]["A"] == {
            "attempts": 3, "round_wins": 1, "known_outcomes": 2,
            "unknown_outcomes": 1, "conversion_pct": 50.0,
        }
    assert "A 1/2（50.0%），共 3 次机会、1 次结果未知" in state["analyst_report"]
    assert "A 1/2（50.0%），共 3 次机会、1 次结果未知" in state["coach_advice"]
    assert "attempts=3, unknown outcomes=1" in state["current_evidence"][0]["content"]
    report = verify(state)
    assert report["status"] == "pass"
    assert report["scope"] == "deterministic_report_contract"
    assert set(checks(report)) == {"source_metrics", "source_evidence", "analyst_report", "coach_report"}


def test_no_known_outcomes_has_no_rate_and_no_fabricated_lost_plant():
    match = source_match()
    match["rounds"] = match["rounds"][-1:]
    metrics = calculate_metrics(match["rounds"])
    for name in ("opening_duels_by_team", "post_plant_by_team"):
        assert metrics[name]["A"] == {
            "attempts": 1, "round_wins": 0, "known_outcomes": 0,
            "unknown_outcomes": 1, "conversion_pct": None,
        }
    state = render({"match": match, "metrics": metrics,
                    "current_evidence": build_current_match_evidence(match, metrics)})
    assert "A 0/0（胜率不可用），共 1 次机会、1 次结果未知" in state["coach_advice"]
    assert "R30：A 下包，胜负结果不可用。[C2]" in state["coach_advice"]
    # Force the allowed post-plant priority without a model, to check its filter.
    from app.agentic.nodes.coach_node import _render_report
    forced = _render_report(metrics, ["post_plant"])
    assert "下包方失利的 无" in forced
    assert "下包方失利的 R30" not in forced
    assert verify(state)["status"] == "pass"


def test_noncontiguous_rounds_use_source_order_for_citations():
    state = analysis_state()
    assert "R10：A 下包并赢得回合。[C2]" in state["coach_advice"]
    assert "R20：A 下包，B 拆包获胜。[C3]" in state["coach_advice"]
    assert "R30：A 下包，胜负结果不可用。[C4]" in state["coach_advice"]
    from app.agentic.nodes.coach_node import _render_report
    forced = _render_report(state["metrics"], ["post_plant", "opening_followup"])
    assert "下包方失利的 R20" in forced and "首杀却输掉的 R20" in forced
    assert forced.count("[C3]") == 3
    assert "[C21]" not in forced


@pytest.mark.parametrize("field,before,after,check_id", [
    ("analyst_report", "共 3 回合", "共 30 回合", "analyst_report"),
    ("analyst_report", "50.0%", "66.7%", "analyst_report"),
    ("coach_advice", "B 拆包获胜", "A 拆包获胜", "coach_report"),
    ("coach_advice", "R20：A 下包，B 拆包获胜。[C3]", "R20：A 下包，B 拆包获胜。[C2]", "coach_report"),
    ("coach_advice", "胜负结果不可用", "A 赢得回合", "coach_report"),
])
def test_report_mutations_fail_even_with_existing_citation_ids(field, before, after, check_id):
    state = analysis_state()
    assert before in state[field]
    state[field] = state[field].replace(before, after, 1)
    report = verify(state)
    assert report["status"] == "needs_review"
    assert report["unknown_citations"] == []
    assert checks(report)[check_id]["status"] == "fail"
    assert checks(report)[check_id]["mismatches"][0]["path"].startswith(check_id + "[")


def test_jointly_altered_metrics_evidence_and_reports_cannot_verify_themselves():
    state = analysis_state()
    state["metrics"]["kills_total"] = 999
    state["current_evidence"] = build_current_match_evidence(state["match"], state["metrics"])
    render(state)
    report = verify(state)
    assert report["status"] == "needs_review"
    assert checks(report)["source_metrics"]["mismatches"] == [
        {"path": "source_metrics.kills_total", "reason": "value_mismatch", "expected": 3, "actual": 999}
    ]
    assert checks(report)["source_evidence"]["status"] == "fail"
    assert checks(report)["analyst_report"]["status"] == "fail"


def test_valid_citation_id_with_wrong_source_provenance_or_body_fails():
    for field, value in (("metadata", {"match_id": "other-match"}), ("content", "altered source")):
        state = analysis_state()
        state["current_evidence"][2][field] = value
        report = verify(state)
        assert report["unknown_citations"] == []
        assert report["status"] == "needs_review"
        assert checks(report)["source_evidence"]["status"] == "fail"


def test_additional_uncertified_claim_or_removed_caveat_fails_contract():
    state = analysis_state()
    state["coach_advice"] += "\n- 这些道具证明战术配合完美。[C1]"
    assert checks(verify(state))["coach_report"]["status"] == "fail"
    state = analysis_state()
    state["coach_advice"] = state["coach_advice"].replace("单场小样本也不足以确定战术原因", "已确定战术原因")
    assert checks(verify(state))["coach_report"]["status"] == "fail"


def test_missing_source_cannot_claim_fact_verification_passed():
    state = analysis_state()
    del state["match"]
    report = verify(state)
    assert report["status"] == "needs_review"
    assert checks(report)["source_input"]["status"] == "not_checked"


@pytest.mark.parametrize("number", [10, 0, True, "30", []])
def test_ambiguous_round_source_identity_is_rejected(number):
    state = analysis_state()
    state["match"]["rounds"][-1]["round_number"] = deepcopy(number)
    report = verify(state)
    assert report["status"] == "needs_review"
    assert checks(report)["source_input"]["reason"] == "round_numbers_must_be_unique_positive_integers"


def test_missing_round_number_is_not_treated_as_explicit_source_identity():
    state = analysis_state()
    del state["match"]["rounds"][-1]["round_number"]
    assert checks(verify(state))["source_input"]["status"] == "fail"


@pytest.mark.parametrize("decision", [None, [], {"priority_ids": ["unknown"]}])
def test_invalid_coach_decision_is_reviewable_instead_of_crashing(decision):
    state = analysis_state()
    state["coach_decision"] = decision
    report = verify(state)
    assert report["status"] == "needs_review"
    assert checks(report)["coach_priorities"]["reason"] == "missing_or_invalid_priority_ids"
