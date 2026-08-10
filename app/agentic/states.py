from typing import Any, Dict, TypedDict

class GraphState(TypedDict, total=False):
    """全局状态，定义每个节点产生及传递的关键信息流字段"""
    match: Dict[str, Any]
    raw_data: str
    metrics: Dict[str, Any]
    rag_context: str
    retrieval_query: str
    retrieval_queries: list
    analysis_plan: list
    analysis_mode: str
    supervisor_decision: Dict[str, Any]
    retrieval_metadata: Dict[str, Any]
    retrieval_evidence: list
    retrieval_task_results: list
    retrieval_retry_tasks: list
    retrieval_trace: Dict[str, Any]
    retrieval_available: bool
    graph_available: bool
    graph_available: bool
    critique_feedback: str
    analyst_report: str
    coach_advice: str
    critique_score: float
    retry_count: int
    verification_report: Dict[str, Any]
    agent_trace: list
    tool_trace: list
