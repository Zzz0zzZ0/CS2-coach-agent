import logging
from app.agentic.states import GraphState

logger = logging.getLogger(__name__)


def _match_teams(match: dict) -> list[str]:
    teams = set()
    for round_data in match.get("rounds", []):
        for kill in round_data.get("kills", []):
            teams.update(filter(None, (kill.get("killer_team"), kill.get("victim_team"))))
        for grenade in round_data.get("grenades", []):
            teams.update(filter(None, (grenade.get("thrower_team"),)))
        for plant in round_data.get("plants", []):
            teams.update(filter(None, (plant.get("planter_team"),)))
    return sorted(str(team) for team in teams if str(team) not in {"Unknown", "None", "nan"})

def create_router_node(llm=None):
    async def node_router(state: GraphState) -> dict:
        logger.info(">>> 执行图节点: [Router] 生成确定性的分析任务计划...")
        match = state.get("match", {})
        map_name = match.get("map_name")
        metadata = {"map": map_name} if map_name else {}
        map_label = str(map_name or "CS2").removeprefix("de_").title()
        teams = _match_teams(match)
        subject = " ".join([*teams, map_label])
        query = f"{subject} CS2 tactical review"
        metrics = state.get("metrics", {})
        if metrics:
            query += (
                f" {metrics.get('kills_total', 0)} total kills"
                f" {metrics.get('first_kills_total', 0)} first kills"
            )

        analysis_plan = [
            {
                "id": "opening_duel",
                "goal": "首杀、首死和交火交换",
                "query": f"{subject} opening duel first kill first death trade kill",
                "query_variants": [f"{map_label} first kill trade sequence"],
                "required_tactic_types": ["Opening Duel Evidence", "Round Event Evidence"],
            },
            {
                "id": "utility",
                "goal": "烟雾、闪光、燃烧弹和道具时序",
                "query": f"{subject} smoke flash molotov grenade utility sequence",
                "query_variants": [f"{map_label} execute utility evidence"],
                "required_tactic_types": ["Round Event Evidence"],
            },
            {
                "id": "round_flow",
                "goal": "击杀链、下包、回合结果和残局",
                "query": f"{subject} round outcome kill chain bomb plant retake",
                "query_variants": [f"{map_label} bomb plant retake round evidence"],
                "required_tactic_types": ["Round Event Evidence"],
            },
            {
                "id": "map_context",
                "goal": "地图和比赛级上下文对照",
                "query": f"{subject} professional demo map control match summary",
                "query_variants": [f"{map_label} professional match tactical context"],
                "required_tactic_types": ["Professional Match Summary", "Round Event Evidence"],
            },
        ]
        enabled_tasks = set(
            state.get("supervisor_decision", {}).get("enabled_tasks", [])
        )
        if enabled_tasks:
            analysis_plan = [task for task in analysis_plan if task["id"] in enabled_tasks]
        retrieval_queries = [task["query"] for task in analysis_plan]

        return {
            "retrieval_metadata": metadata,
            "retrieval_query": query,
            "retrieval_queries": retrieval_queries,
            "analysis_plan": analysis_plan,
            "agent_trace": state.get("agent_trace", []) + [{
                "node": "Router",
                "mode": state.get("analysis_mode", "demo_forensic"),
                "task_count": len(analysis_plan),
            }],
            "retry_count": state.get("retry_count", 0)
        }
    return node_router
