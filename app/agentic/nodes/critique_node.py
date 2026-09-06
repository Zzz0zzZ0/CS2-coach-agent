import json
import logging

from langchain_core.prompts import PromptTemplate

from app.agentic.states import GraphState

logger = logging.getLogger(__name__)


def _map_label(value: str | None) -> str | None:
    if not value:
        return None
    return value.removeprefix("de_").title()


def _rule_review(state: GraphState) -> tuple[float, str, list[str], dict]:
    evidence = state.get("retrieval_evidence", [])
    task_results = state.get("retrieval_task_results", [])
    expected_map = _map_label(state.get("match", {}).get("map_name"))
    map_hits = sum(1 for item in evidence if item.get("metadata", {}).get("map") == expected_map)
    map_score = map_hits / len(evidence) if evidence else 0.0
    expected_teams = set(state.get("metrics", {}).get("team_totals", {}))
    evidence_text = " ".join(
        f"{item.get('content', '')} {item.get('metadata', {}).get('parent_content', '')}".lower()
        for item in evidence
    )
    matched_teams = {team for team in expected_teams if team.lower() in evidence_text}
    team_score = len(matched_teams) / len(expected_teams) if expected_teams else 1.0
    coverage = [item for item in task_results if item.get("covered")]
    coverage_score = len(coverage) / len(task_results) if task_results else 0.0
    evidence_score = min(1.0, len(evidence) / 6.0)
    score = 0.35 * evidence_score + 0.25 * coverage_score + 0.20 * map_score + 0.20 * team_score
    gaps = [item["task_id"] for item in task_results if not item.get("covered")]
    feedback = []
    if not evidence:
        feedback.append("没有召回可用证据")
    if expected_map and map_score < 1.0:
        feedback.append(f"地图证据不完整，应优先保证 {expected_map}")
    if expected_teams and team_score < 1.0:
        feedback.append("缺少战队历史证据: " + ", ".join(sorted(expected_teams - matched_teams)))
    if gaps:
        feedback.append("缺少任务: " + ", ".join(gaps))
    report = {
        "rule_score": round(score, 3),
        "evidence_count": len(evidence),
        "map_match_rate": round(map_score, 3),
        "team_match_rate": round(team_score, 3),
        "task_coverage_rate": round(coverage_score, 3),
    }
    return score, "; ".join(feedback) or "规则检查通过", gaps, report


def create_critique_node(llm):
    async def node_critique(state: GraphState) -> dict:
        logger.info(">>> 执行图节点: [Critique] 执行规则检查和证据质量评审...")
        rule_score, rule_feedback, retry_tasks, report = _rule_review(state)
        llm_score = None
        llm_feedback = ""
        rag_context = state.get("rag_context", "")
        if llm and state.get("retrieval_evidence") and "暂无匹配" not in rag_context:
            try:
                prompt = PromptTemplate.from_template(
                    "作为一名 CS2 战术检索评审员，评估证据能否支持当前问题。"
                    "只返回 JSON：{{\"score\": 0.0, \"feedback\": \"缺失主题\"}}。"
                    "不要评价战术好坏，只评价证据相关性和覆盖度。score 为 0 到 1。\n\n"
                    "当前问题：{query}\n规则检查：{rule_report}\n证据：{context}\n"
                )
                response = await (prompt | llm).ainvoke({
                    "query": state.get("retrieval_query", ""),
                    "rule_report": json.dumps(report, ensure_ascii=False),
                    "context": rag_context[:6000],
                })
                content = response.content if hasattr(response, "content") else str(response)
                result = json.loads(content.replace("```json", "").replace("```", "").strip())
                llm_score = max(0.0, min(1.0, float(result.get("score", 0.0))))
                llm_feedback = str(result.get("feedback", ""))
            except Exception as error:
                logger.warning("[Critique] LLM 评审不可用，使用规则评分: %s", error)

        score = rule_score if llm_score is None else 0.5 * rule_score + 0.5 * llm_score
        feedback = "; ".join(item for item in (rule_feedback, llm_feedback) if item)
        return {
            "critique_score": round(score, 3),
            "critique_feedback": feedback,
            "retrieval_retry_tasks": retry_tasks,
            "retrieval_trace": {
                **state.get("retrieval_trace", {}),
                "critique": {
                    **report,
                    "llm_score": llm_score,
                    "final_score": round(score, 3),
                    "retry_tasks": retry_tasks,
                },
            },
            "retry_count": state.get("retry_count", 0) + 1,
        }

    return node_critique
