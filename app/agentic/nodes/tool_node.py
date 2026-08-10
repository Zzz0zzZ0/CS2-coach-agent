import logging

from app.agentic.states import GraphState
from app.services.metrics_service import calculate_metrics

logger = logging.getLogger(__name__)


def create_tool_node():
    """Run deterministic tools before any LLM agent is allowed to reason."""

    async def node_tools(state: GraphState) -> dict:
        match = state.get("match", {})
        metrics = calculate_metrics(match.get("rounds", []))
        logger.info("[Tools] calculate_metrics completed: rounds=%s", metrics["rounds_total"])
        return {
            "metrics": metrics,
            "tool_trace": [{
                "tool": "calculate_metrics",
                "status": "completed",
                "rounds": metrics["rounds_total"],
            }],
            "agent_trace": state.get("agent_trace", []) + [{
                "node": "Tools",
                "tools": ["calculate_metrics"],
            }],
        }

    return node_tools
