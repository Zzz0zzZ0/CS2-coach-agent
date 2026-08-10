from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MatchMetrics(BaseModel):
    """Metrics computed from match events before any LLM is called."""

    rounds_total: int = 0
    rounds_won: Dict[str, int] = Field(default_factory=dict)
    kills_total: int = 0
    first_kills_total: int = 0
    players: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    available_metrics: List[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """Stable result returned by every analysis entry point."""

    match_id: str
    map_name: str
    metrics: MatchMetrics
    analyst_report: str = ""
    coach_advice: str = ""
    critique_score: Optional[float] = None
    ingested_tactics_count: int = 0
    retrieval_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    verification_report: Dict[str, Any] = Field(default_factory=dict)
    analysis_mode: str = "demo_forensic"
    knowledge_review: Dict[str, Any] = Field(default_factory=dict)
