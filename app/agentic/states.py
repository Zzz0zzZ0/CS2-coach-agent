from typing import TypedDict

class GraphState(TypedDict):
    """全局状态，定义每个节点产生及传递的关键信息流字段"""
    raw_data: str
    rag_context: str
    analyst_report: str
    coach_advice: str
    retrieval_metadata: dict
    critique_score: float
    retry_count: int
