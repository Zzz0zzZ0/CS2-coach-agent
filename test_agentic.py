import asyncio

from app.agentic.nodes.critique_node import create_critique_node
from app.agentic.nodes.router_node import create_router_node
from app.agentic.nodes.verify_node import create_verify_node
from app.agentic.nodes.supervisor_node import create_supervisor_node
from app.agentic.nodes.tool_node import create_tool_node
from app.agentic.tools import select_analysis_plan
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
    assert result["tool_trace"][0]["tool"] == "calculate_metrics"


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


def test_supervisor_uses_allowlisted_tool_call_when_available():
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
        "retrieval_evidence": [{"source_id": "one"}],
        "analyst_report": "观察到 [E1]。",
        "coach_advice": "建议加强默认控制。\n错误引用 [E9]。",
    }))

    report = result["verification_report"]
    assert report["status"] == "needs_review"
    assert report["unknown_citations"] == ["E9"]
    assert report["uncited_claim_count"] == 1
