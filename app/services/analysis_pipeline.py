from typing import Any

from app.agentic.workflow import create_workflow_app
from app.domain.analysis_models import AnalysisResult, MatchMetrics
from app.domain.match_models import MatchWebhookPayload


class AnalysisPipeline:
    """Single analysis interface shared by HTTP, Celery, CLI, and scrapers."""

    def __init__(self, llm: Any, kb_client: Any, graph_client: Any = None):
        self.llm = llm
        self.kb_client = kb_client
        self.graph_client = graph_client

    async def analyze(self, payload: MatchWebhookPayload) -> AnalysisResult:
        serialized_match = payload.model_dump()
        initial_state = {
            "match": serialized_match,
            "metrics": {},
            "current_context": "",
            "current_evidence": [],
            "rag_context": "",
            "retrieval_evidence": [],
            "retrieval_task_results": [],
            "retrieval_retry_tasks": [],
            "retrieval_trace": {},
            "graph_available": bool(self.graph_client and self.graph_client.available()),
            "analysis_plan": [],
            "analysis_mode": "demo_forensic",
            "supervisor_decision": {},
            "agent_trace": [],
            "tool_trace": [],
            "analyst_report": "",
            "coach_advice": "",
            "coach_decision": {},
            "model_usage": {},
            "retry_count": 0,
        }

        workflow = create_workflow_app(self.llm, self.kb_client, self.graph_client)
        final_state = await workflow.ainvoke(initial_state)
        metrics = MatchMetrics(**final_state.get("metrics", {}))
        return AnalysisResult(
            match_id=payload.match_id,
            map_name=payload.map_name,
            metrics=metrics,
            analyst_report=final_state.get("analyst_report", ""),
            coach_advice=final_state.get("coach_advice", ""),
            coach_decision=final_state.get("coach_decision", {}),
            model_usage=final_state.get("model_usage", {}),
            critique_score=final_state.get("critique_score"),
            current_evidence=final_state.get("current_evidence", []),
            retrieval_evidence=final_state.get("retrieval_evidence", []),
            verification_report=final_state.get("verification_report", {}),
            analysis_mode=final_state.get("analysis_mode", "demo_forensic"),
        )
