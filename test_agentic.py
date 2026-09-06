import asyncio

from app.agentic.nodes.critique_node import create_critique_node
from app.agentic.nodes.analyst_node import create_analyst_node
from app.agentic.nodes.coach_node import create_coach_node
from app.agentic.nodes.retrieve_node import create_retrieve_node
from app.agentic.nodes.router_node import create_router_node
from app.agentic.nodes.verify_node import create_verify_node
from app.agentic.nodes.supervisor_node import create_supervisor_node
from app.agentic.nodes.tool_node import create_tool_node
from app.agentic.tools import select_analysis_plan
from app.services.rag_service import Evidence
from langchain_core.messages import AIMessage


def test_router_creates_specialized_analysis_plan():
    result = asyncio.run(
        create_router_node()( {
            "match": {"map_name": "de_dust2"},
            "metrics": {"kills_total": 10, "first_kills_total": 2},
        })
    )

    assert {task["id"] for task in result["analysis_plan"]} == {
        "opening_duel", "utility", "round_flow", "map_context"
    }
    assert result["retrieval_metadata"] == {"map": "de_dust2"}


def test_router_includes_current_teams_in_historical_search_queries():
    result = asyncio.run(create_router_node()({
        "match": {
            "map_name": "de_nuke",
            "rounds": [{"kills": [{
                "killer_team": "Falcons", "victim_team": "Spirit",
            }]}],
        },
        "metrics": {},
    }))

    assert "Falcons" in result["retrieval_query"]
    assert "Spirit" in result["retrieval_query"]
    assert all("Falcons" in task["query"] for task in result["analysis_plan"])


def test_supervisor_selects_bounded_mode_and_router_filters_tasks():
    state = {
        "match": {
            "map_name": "de_dust2",
            "extra_data": {"analysis_mode": "player_coaching"},
        },
        "metrics": {},
    }
    supervisor = asyncio.run(create_supervisor_node()(state))
    routed = asyncio.run(create_router_node()(state | supervisor))

    assert supervisor["analysis_mode"] == "player_coaching"
    assert {task["id"] for task in routed["analysis_plan"]} == {
        "opening_duel", "utility", "round_flow"
    }


def test_tools_node_calculates_metrics_before_agents():
    result = asyncio.run(create_tool_node()({
        "match": {"rounds": [{"winner": "T", "kills": []}]},
        "agent_trace": [],
    }))

    assert result["metrics"]["rounds_total"] == 1
    assert result["current_evidence"][0]["metadata"]["evidence_scope"] == "current_match"
    assert result["current_context"].startswith("[C1]")
    assert result["tool_trace"][0]["tool"] == "calculate_metrics"


def test_analyst_report_is_deterministic_and_does_not_call_llm():
    class _FailIfCalled:
        async def ainvoke(self, _prompt):
            raise AssertionError("deterministic analyst must not call the model")

    result = asyncio.run(create_analyst_node(_FailIfCalled())({
        "match": {"map_name": "de_nuke"},
        "metrics": {
            "rounds_total": 2,
            "rounds_won_by_team": {"Spirit": 1, "Falcons": 1},
            "rounds_won_by_team_and_side": {"Spirit": {"CT": 1}, "Falcons": {"T": 1}},
            "kills_total": 10,
            "opening_duels_by_team": {
                "Spirit": {"round_wins": 1, "attempts": 1, "conversion_pct": 100.0},
            },
            "post_plant_by_team": {
                "Falcons": {"round_wins": 1, "attempts": 1, "conversion_pct": 100.0},
            },
            "grenades_total": 2,
            "grenades_by_type": {"Smoke": 2},
            "plants_total": 1,
            "plants_by_team": {"Falcons": 1},
            "defuses_by_team": {},
            "flash_blinds_total": 0,
        },
    }))

    assert "Spirit（CT 1）" in result["analyst_report"]
    assert "投掷次数只代表使用量" in result["analyst_report"]
    assert result["analyst_report"].count("[C1]") == 7


class _PriorityToolModel:
    def bind_tools(self, tools):
        assert tools[0].name == "select_coaching_priorities"
        return self

    async def ainvoke(self, _prompt):
        return AIMessage(
            content="",
            tool_calls=[{
                "name": "select_coaching_priorities",
                "args": {"priority_ids": ["post_plant", "opening_followup"]},
                "id": "coach-tool-1",
                "type": "tool_call",
            }],
            usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        )


class _UtilityPriorityModel(_PriorityToolModel):
    async def ainvoke(self, _prompt):
        return AIMessage(
            content="",
            tool_calls=[{
                "name": "select_coaching_priorities",
                "args": {"priority_ids": ["utility_review", "side_transition"]},
                "id": "coach-tool-utility",
                "type": "tool_call",
            }],
        )


def test_coach_model_only_selects_priorities_and_report_is_deterministic():
    result = asyncio.run(create_coach_node(_PriorityToolModel())({
        "metrics": {
            "rounds_won_by_team": {"Spirit": 1},
            "rounds_won_by_team_and_side": {"Spirit": {"CT": 1}},
            "opening_duels_by_team": {
                "Falcons": {"round_wins": 0, "attempts": 1, "conversion_pct": 0.0},
            },
            "post_plant_by_team": {
                "Falcons": {"round_wins": 0, "attempts": 1, "conversion_pct": 0.0},
            },
            "defuses_by_team": {"Spirit": 1},
            "round_summaries": [{
                "round_number": 1,
                "winner_team": "Spirit",
                "opening_team": "Falcons",
                "plants": 1,
                "plant_teams": ["Falcons"],
                "plant_outcome": "Falcons planted; Spirit defused",
                "reason": "bomb_defused",
            }],
        },
    }))

    assert result["coach_decision"] == {
        "priority_ids": ["post_plant", "opening_followup"],
        "selection_source": "qwen_tool_call",
    }
    assert "R1：Falcons 下包，Spirit 拆包获胜" in result["coach_advice"]
    assert "优秀" not in result["coach_advice"]
    assert result["model_usage"]["total_tokens"] == 120


def test_coach_utility_review_reports_available_flash_metrics():
    result = asyncio.run(create_coach_node(_UtilityPriorityModel())({
        "metrics": {
            "rounds_won_by_team": {"Falcons": 13, "G2": 6},
            "flash_blinds_total": 251,
            "enemy_flash_blinds_by_team": {"Falcons": 55, "G2": 59},
            "team_flash_blinds_by_team": {"Falcons": 69, "G2": 68},
        },
    }))

    assert "251 次受闪" in result["coach_advice"]
    assert "当前闪光致盲指标不可用" not in result["coach_advice"]


class _ToolCallingModel:
    def bind_tools(self, tools):
        assert tools == [select_analysis_plan]
        return self

    async def ainvoke(self, _prompt):
        return AIMessage(
            content="",
            tool_calls=[{
                "name": "select_analysis_plan",
                "args": {
                    "mode": "player_coaching",
                    "task_ids": ["opening_duel", "utility"],
                    "reason": "focus on player execution",
                },
                "id": "tool-call-1",
                "type": "tool_call",
            }],
        )


def test_supervisor_uses_allowlisted_tool_call_when_available(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "AUTONOMOUS_TOOL_SELECTION_ENABLED", True)
    result = asyncio.run(create_supervisor_node(_ToolCallingModel())({
        "match": {"map_name": "de_mirage"},
    }))

    assert result["supervisor_decision"]["selection_source"] == "llm_tool_call"
    assert result["supervisor_decision"]["enabled_tasks"] == ["opening_duel", "utility"]


def test_critique_uses_rules_without_remote_llm():
    state = {
        "match": {"map_name": "de_dust2"},
        "retrieval_evidence": [
            {"metadata": {"map": "Dust2"}, "content": "evidence", "score": 0.8, "source_id": "e"}
            for _ in range(6)
        ],
        "retrieval_task_results": [
            {"task_id": "opening_duel", "covered": True},
            {"task_id": "utility", "covered": True},
        ],
        "retrieval_trace": {},
        "retry_count": 0,
        "rag_context": "[E1] evidence",
    }

    result = asyncio.run(create_critique_node(None)(state))

    assert result["critique_score"] == 1.0
    assert result["retrieval_retry_tasks"] == []
    assert result["retrieval_trace"]["critique"]["llm_score"] is None


def test_verifier_reports_unknown_and_uncited_claims():
    result = asyncio.run(create_verify_node()({
        "current_evidence": [{"source_id": "current"}],
        "retrieval_evidence": [{"source_id": "one"}],
        "analyst_report": "当前比赛观察到 [C1]。",
        "coach_advice": "建议加强默认控制。\n错误引用 [E9]。",
    }))

    report = result["verification_report"]
    assert report["status"] == "needs_review"
    assert report["unknown_citations"] == ["E9"]
    assert report["uncited_claim_count"] == 1


def test_verifier_requires_current_evidence_for_current_match_claims():
    result = asyncio.run(create_verify_node()({
        "current_evidence": [{"source_id": "current"}],
        "retrieval_evidence": [{"source_id": "history"}],
        "analyst_report": "",
        "coach_advice": "本场 Falcons 首杀转化偏低 [E1]。",
    }))

    report = result["verification_report"]
    assert report["status"] == "needs_review"
    assert report["current_claims_without_current_evidence"] == 1


def test_verifier_rejects_empty_agent_outputs():
    report = asyncio.run(create_verify_node()({
        "current_evidence": [{"source_id": "current"}],
        "retrieval_evidence": [],
        "analyst_report": "",
        "coach_advice": "",
    }))["verification_report"]

    assert report["status"] == "needs_review"
    assert report["missing_outputs"] == ["analyst_report", "coach_advice"]


class _OffTopicGraph:
    def available(self):
        return True

    async def retrieve(self, *args, **kwargs):
        return [Evidence(
            content="Generic map overview",
            metadata={"context_level": "community_summary", "topic": "overview"},
            score=0.8,
            source_id="graph-overview",
        )]


class _TacticalGraph:
    def available(self):
        return True

    async def retrieve(self, *args, **kwargs):
        return [Evidence(
            content=(
                "Tactical label EXECUTE_CANDIDATE: team Alpha, site A, "
                "source weak_rule, confidence 0.72."
            ),
            metadata={
                "context_level": "graph_path",
                "topic": "utility",
                "tactic_type": "Graph Utility Evidence",
                "tactical_labels": ["EXECUTE_CANDIDATE"],
            },
            score=0.9,
            source_id="graph-execute",
        )]


def test_graph_evidence_only_covers_its_matching_task_topic():
    result = asyncio.run(create_retrieve_node(None, _OffTopicGraph())({
        "analysis_plan": [{
            "id": "utility",
            "query": "Mirage utility",
            "query_variants": [],
            "required_tactic_types": ["Round Event Evidence"],
        }],
        "retrieval_evidence": [],
        "retrieval_task_results": [],
        "agent_trace": [],
    }))

    assert result["retrieval_task_results"][0]["covered"] is False


def test_tactical_graph_evidence_reaches_agent_context():
    result = asyncio.run(create_retrieve_node(None, _TacticalGraph())({
        "analysis_plan": [{
            "id": "utility",
            "query": "Dust2 execute utility",
            "query_variants": [],
            "required_tactic_types": ["Round Event Evidence"],
        }],
        "retrieval_evidence": [],
        "retrieval_task_results": [],
        "agent_trace": [],
    }))

    assert result["retrieval_task_results"][0]["covered"] is True
    assert "EXECUTE_CANDIDATE" in result["rag_context"]
    assert result["retrieval_evidence"][0]["metadata"]["tactical_labels"] == [
        "EXECUTE_CANDIDATE"
    ]
