import logging

from app.agentic.states import GraphState
from app.services.metrics_service import build_current_match_evidence, calculate_metrics

logger = logging.getLogger(__name__)


def create_tool_node():
    """Run deterministic tools before any LLM agent is allowed to reason."""

    async def node_tools(state: GraphState) -> dict:
        match = state.get("match", {})
        metrics = calculate_metrics(match.get("rounds", []))
        current_evidence = build_current_match_evidence(match, metrics)
        current_context = "\n---\n".join(
            f"[C{index}] source=current_demo location={item['metadata'].get('map')}/"
            f"{item['metadata'].get('round_number', 'summary')}\n{item['content']}"
            for index, item in enumerate(current_evidence, start=1)
        )
        logger.info("[Tools] calculate_metrics completed: rounds=%s", metrics["rounds_total"])
        return {
            "metrics": metrics,
            "current_evidence": current_evidence,
            "current_context": current_context,
            "tool_trace": [{
                "tool": "calculate_metrics",
                "status": "completed",
                "rounds": metrics["rounds_total"],
            }],
            "agent_trace": state.get("agent_trace", []) + [{
                "node": "Tools",
                "tools": ["calculate_metrics", "build_current_match_evidence"],
            }],
        }

    return node_tools
