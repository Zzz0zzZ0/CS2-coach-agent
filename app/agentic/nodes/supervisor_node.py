import logging
import json

from app.agentic.states import GraphState
from app.agentic.tools import select_analysis_plan
from app.core.config import settings

logger = logging.getLogger(__name__)

_MODE_CONFIG = {
    "demo_forensic": {
        "objective": "完整复盘 Demo 中的首杀、道具、回合流程和地图上下文",
        "tasks": ["opening_duel", "utility", "round_flow", "map_context"],
    },
    "tactical_comparison": {
        "objective": "将当前比赛的回合流程和道具执行与职业战术证据对照",
        "tasks": ["utility", "round_flow", "map_context"],
    },
    "player_coaching": {
        "objective": "聚焦个人首杀、交换、道具纪律和可执行训练建议",
        "tasks": ["opening_duel", "utility", "round_flow"],
    },
    "data_quality_check": {
        "objective": "优先确认 Demo 事件是否足以支持可靠分析",
        "tasks": ["opening_duel", "round_flow"],
    },
}


def _fallback_selection(requested_mode: str | None) -> tuple[str, dict, str]:
    mode = requested_mode if requested_mode in _MODE_CONFIG else "demo_forensic"
    config = _MODE_CONFIG[mode]
    return mode, {
        "mode": mode,
        "task_ids": config["tasks"],
        "reason": "explicit_request" if requested_mode == mode else "safe_default",
    }, "deterministic_fallback"


async def _select_with_tool(llm, match: dict) -> tuple[str, dict, str] | None:
    if not llm or not settings.AUTONOMOUS_TOOL_SELECTION_ENABLED:
        return None

    prompt = (
        "You are the bounded Supervisor for a CS2 tactical analysis workflow. "
        "Call select_analysis_plan exactly once. Choose the smallest sufficient "
        "task set from the allowed modes and task IDs. Never invent IDs. "
        f"Allowed modes: {list(_MODE_CONFIG)}. "
        f"Mode task mapping: {json.dumps({k: v['tasks'] for k, v in _MODE_CONFIG.items()})}. "
        f"Match input: {json.dumps(match, ensure_ascii=False, default=str)[:4000]}"
    )
    try:
        response = await llm.bind_tools([select_analysis_plan]).ainvoke(prompt)
        tool_calls = getattr(response, "tool_calls", []) or []
        if not tool_calls:
            logger.warning("[Supervisor] model returned no tool call; using fallback")
            return None
        call = tool_calls[0]
        if call.get("name") != select_analysis_plan.name:
            logger.warning("[Supervisor] rejected unexpected tool: %s", call.get("name"))
            return None
        selection = select_analysis_plan.invoke(call.get("args", {}))
        mode = selection["mode"]
        allowed_tasks = set(_MODE_CONFIG[mode]["tasks"])
        task_ids = [task_id for task_id in selection["task_ids"] if task_id in allowed_tasks]
        if not task_ids:
            return None
        return mode, {**selection, "task_ids": task_ids}, "llm_tool_call"
    except Exception as error:
        logger.warning("[Supervisor] tool selection failed (%s); using fallback", type(error).__name__)
        return None


def create_supervisor_node(llm=None):
    """Select a bounded workflow mode without letting an LLM invent graph branches."""

    async def node_supervisor(state: GraphState) -> dict:
        match = state.get("match", {})
        extra_data = match.get("extra_data", {}) or {}
        requested_mode = extra_data.get("analysis_mode") or match.get("analysis_mode")
        selection = None if requested_mode in _MODE_CONFIG else await _select_with_tool(llm, match)
        if selection is None:
            mode, selection, selection_source = _fallback_selection(requested_mode)
        else:
            mode, selection, selection_source = selection
        config = _MODE_CONFIG[mode]

        decision = {
            "mode": mode,
            "objective": config["objective"],
            "enabled_tasks": selection["task_ids"],
            "reason": selection.get("reason", ""),
            "selection_source": selection_source,
        }
        logger.info("[Supervisor] mode=%s tasks=%s", mode, config["tasks"])
        return {
            "analysis_mode": mode,
            "supervisor_decision": decision,
            "agent_trace": [{
                "node": "Supervisor",
                "mode": mode,
                "tasks": selection["task_ids"],
                "tool": "select_analysis_plan" if selection_source == "llm_tool_call" else None,
                "selection_source": selection_source,
            }],
        }

    return node_supervisor
