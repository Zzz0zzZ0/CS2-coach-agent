import logging
from app.agentic.states import GraphState

logger = logging.getLogger(__name__)


def _format_conversions(values: dict) -> str:
    return "；".join(
        f"{team} {item['round_wins']}/{item['attempts']}（{item['conversion_pct']}%）"
        for team, item in values.items()
    ) or "不可用"


def create_analyst_node(llm):
    async def node_analyst(state: GraphState) -> dict:
        logger.info(">>> 执行图节点: [Analyst] 生成确定性比赛事实报告...")
        metrics = state.get("metrics", {})
        score = "：".join(
            f"{team} {wins}" for team, wins in metrics.get("rounds_won_by_team", {}).items()
        ) or "不可用"
        side_splits = "；".join(
            f"{team}（" + "，".join(f"{side} {wins}" for side, wins in values.items()) + "）"
            for team, values in metrics.get("rounds_won_by_team_and_side", {}).items()
        ) or "不可用"
        grenade_types = "，".join(
            f"{kind} {count}" for kind, count in metrics.get("grenades_by_type", {}).items()
        ) or "不可用"
        plants = "；".join(
            f"{team} {count}" for team, count in metrics.get("plants_by_team", {}).items()
        ) or "不可用"
        defuses = "；".join(
            f"{team} {count}" for team, count in metrics.get("defuses_by_team", {}).items()
        ) or "0"
        flash_total = metrics.get("flash_blinds_total", 0)
        if flash_total:
            flash_summary = (
                f"共记录 {flash_total} 次受闪：对手受闪 "
                f"{metrics.get('enemy_flash_blinds_by_team', {})}，队友受闪 "
                f"{metrics.get('team_flash_blinds_by_team', {})}；该指标描述命中，不单独证明战术质量"
            )
        else:
            flash_summary = "当前解析结果未提供闪光致盲事件，不能据此评价闪光质量"

        report = (
            "**比赛概况**\n"
            f"- 地图 {state.get('match', {}).get('map_name', 'Unknown')}，共 "
            f"{metrics.get('rounds_total', 0)} 回合；比分 {score}。有效战斗击杀 "
            f"{metrics.get('kills_total', 0)} 次。[C1]\n"
            f"- 各队按实际攻守方拆分的胜局为：{side_splits}。[C1]\n\n"
            "**关键转化**\n"
            f"- 首杀后回合胜率：{_format_conversions(metrics.get('opening_duels_by_team', {}))}。[C1]\n"
            f"- 下包后回合胜率：{_format_conversions(metrics.get('post_plant_by_team', {}))}。[C1]\n\n"
            "**道具与下包**\n"
            f"- 共记录 {metrics.get('grenades_total', 0)} 次投掷：{grenade_types}；投掷次数只代表使用量，不代表效果。[C1]\n"
            f"- 共记录 {metrics.get('plants_total', 0)} 次下包（{plants}）；拆包胜局（{defuses}）。[C1]\n\n"
            "**数据缺口**\n"
            f"- {flash_summary}。站位、沟通和战术意图也不能仅由上述计数确定。[C1]"
        )
        return {"analyst_report": report}
    return node_analyst
