import json
import logging

from app.agentic.states import GraphState
from app.agentic.tools import select_coaching_priorities

logger = logging.getLogger(__name__)

_PRIORITIES = (
    "opening_followup",
    "post_plant",
    "utility_review",
    "side_transition",
)


def _usage(response) -> dict:
    usage = getattr(response, "usage_metadata", None) or {}
    if usage:
        return dict(usage)
    metadata = getattr(response, "response_metadata", None) or {}
    raw = metadata.get("token_usage", {})
    return {
        "input_tokens": raw.get("prompt_tokens", 0),
        "output_tokens": raw.get("completion_tokens", 0),
        "total_tokens": raw.get("total_tokens", 0),
    } if raw else {}


def _fallback_priorities(metrics: dict) -> list[str]:
    choices = []
    if len(metrics.get("opening_duels_by_team", {})) > 1:
        choices.append("opening_followup")
    if any(
        item.get("conversion_pct", 100) < 50
        for item in metrics.get("post_plant_by_team", {}).values()
    ):
        choices.append("post_plant")
    if not metrics.get("flash_blinds_total"):
        choices.append("utility_review")
    choices.append("side_transition")
    return list(dict.fromkeys(choices))[:3]


async def _select_priorities(llm, metrics: dict) -> tuple[list[str], str, dict]:
    fallback = _fallback_priorities(metrics)
    if not llm:
        return fallback, "deterministic_fallback", {}
    bounded_metrics = {
        key: metrics.get(key, {})
        for key in (
            "rounds_won_by_team_and_side",
            "opening_duels_by_team",
            "post_plant_by_team",
            "defuses_by_team",
            "flash_blinds_total",
            "enemy_flash_blinds_by_team",
            "team_flash_blinds_by_team",
        )
    }
    prompt = (
        "Select 2 or 3 coaching priorities for this CS2 match. Call "
        "select_coaching_priorities exactly once. Choose only from the tool's "
        "allowed IDs. Do not write a report or add facts. Metrics: "
        + json.dumps(bounded_metrics, ensure_ascii=False)
    )
    try:
        response = await llm.bind_tools([select_coaching_priorities]).ainvoke(prompt)
        calls = getattr(response, "tool_calls", []) or []
        if not calls or calls[0].get("name") != select_coaching_priorities.name:
            return fallback, "deterministic_fallback", _usage(response)
        decision = select_coaching_priorities.invoke(calls[0].get("args", {}))
        choices = [item for item in decision["priority_ids"] if item in _PRIORITIES]
        if len(choices) < 2:
            return fallback, "deterministic_fallback", _usage(response)
        return choices, "qwen_tool_call", _usage(response)
    except Exception as error:
        logger.warning("[Coach] priority selection failed (%s); using fallback", type(error).__name__)
        return fallback, "deterministic_fallback", {}


def _conversion_text(values: dict) -> str:
    return "；".join(
        f"{team} {item['round_wins']}/{item['attempts']}（{item['conversion_pct']}%）"
        for team, item in values.items()
    ) or "不可用"


def _count_text(values: dict) -> str:
    return "；".join(f"{team} {count}" for team, count in values.items()) or "0"


def _round_refs(rounds: list[dict]) -> str:
    return "".join(f"[C{item['round_number'] + 1}]" for item in rounds)


def _round_numbers(rounds: list[dict]) -> str:
    return "、".join(f"R{item['round_number']}" for item in rounds) or "无"


def _plant_outcome_text(round_data: dict) -> str:
    planters = "、".join(round_data.get("plant_teams", [])) or "未知队伍"
    winner = round_data.get("winner_team") or round_data.get("winner_side") or "未知队伍"
    if str(round_data.get("reason", "")).lower() == "bomb_defused":
        return f"{planters} 下包，{winner} 拆包获胜"
    if winner in round_data.get("plant_teams", []):
        return f"{planters} 下包并赢得回合"
    return f"{planters} 下包，{winner} 赢得回合"


def _priority_advice(priority: str, metrics: dict) -> str:
    rounds = metrics.get("round_summaries", [])
    if priority == "opening_followup":
        lost = [
            item for item in rounds
            if item.get("opening_team") and item.get("winner_team")
            and item["opening_team"] != item["winner_team"]
        ]
        return (
            f"**首杀后续**：复盘取得首杀却输掉的 {_round_numbers(lost)}，逐段人工确认首杀后的存活、补枪和人数优势处理；"
            f"事件序列只证明结果反转，不直接证明失误原因。{_round_refs(lost) or '[C1]'}"
        )
    if priority == "post_plant":
        lost = [
            item for item in rounds
            if item.get("plant_teams") and item.get("winner_team") not in item["plant_teams"]
        ]
        return (
            f"**下包后处理**：重点复盘下包方失利的 {_round_numbers(lost)}，人工标记站位、交叉火力与延时道具；"
            f"当前数据只确认下包方和胜方。{_round_refs(lost) or '[C1]'}"
        )
    if priority == "utility_review":
        flash_total = metrics.get("flash_blinds_total", 0)
        if flash_total:
            enemy = _count_text(metrics.get("enemy_flash_blinds_by_team", {}))
            team = _count_text(metrics.get("team_flash_blinds_by_team", {}))
            return (
                f"**道具复核**：本场记录 {flash_total} 次受闪（对手受闪：{enemy}；队友受闪：{team}）；"
                "优先复核队友受闪较多的回合，计数本身不证明闪光质量。[C1]"
            )
        return (
            "**道具复核**：按回合查看烟、火、雷的落点与队友接触时机；投掷次数不能衡量封锁或助攻效果，"
            "当前闪光致盲指标不可用。[C1]"
        )
    return (
        "**攻守转换**：分别对照双方 T/CT 胜局拆分，优先检查低胜局一侧的开局计划与回合中期决策；"
        "这是一项训练优先级，不是由胜局数直接推出的战术原因。[C1]"
    )


def _render_report(metrics: dict, priorities: list[str]) -> str:
    score = "，".join(
        f"{team} {wins}" for team, wins in metrics.get("rounds_won_by_team", {}).items()
    ) or "不可用"
    sides = "；".join(
        f"{team}（" + "，".join(f"{side} {wins}" for side, wins in values.items()) + "）"
        for team, values in metrics.get("rounds_won_by_team_and_side", {}).items()
    ) or "不可用"
    plant_rounds = [item for item in metrics.get("round_summaries", []) if item.get("plants")]
    plant_lines = [
        f"- R{item['round_number']}：{_plant_outcome_text(item)}。[C{item['round_number'] + 1}]"
        for item in plant_rounds
    ]
    advice = [
        f"{index}. {_priority_advice(priority, metrics)}"
        for index, priority in enumerate(priorities, start=1)
    ]
    return (
        "**核心结论**\n"
        f"- 比分 {score}；按实际阵营拆分为 {sides}。[C1]\n"
        f"- 首杀后胜局转化：{_conversion_text(metrics.get('opening_duels_by_team', {}))}。[C1]\n"
        f"- 下包后胜局转化：{_conversion_text(metrics.get('post_plant_by_team', {}))}；"
        f"拆包胜局 {_count_text(metrics.get('defuses_by_team', {}))}。[C1]\n\n"
        "**关键下包回合**\n"
        + ("\n".join(plant_lines) if plant_lines else "- 当前数据未记录下包。[C1]")
        + "\n\n**训练建议**\n"
        + "\n".join(advice)
        + "\n\n**限制**\n"
        "- 当前 Demo 可确定击杀、胜方、道具投掷、下包与拆包结果；站位、沟通、道具效果和战术意图需要人工录像复核。[C1]"
    )


def create_coach_node(llm):
    async def node_coach(state: GraphState) -> dict:
        logger.info(">>> 执行图节点: [Coach] 选择白名单训练优先级并生成证据报告...")
        metrics = state.get("metrics", {})
        priorities, source, usage = await _select_priorities(llm, metrics)
        return {
            "coach_advice": _render_report(metrics, priorities),
            "coach_decision": {"priority_ids": priorities, "selection_source": source},
            "model_usage": usage,
        }

    return node_coach
