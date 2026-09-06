from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MatchMetrics(BaseModel):
    """Metrics computed from match events before any LLM is called."""

    rounds_total: int = 0
    rounds_won: Dict[str, int] = Field(default_factory=dict)
    rounds_won_by_team: Dict[str, int] = Field(default_factory=dict)
    rounds_won_by_team_and_side: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    kills_total: int = 0
    first_kills_total: int = 0
    players: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    team_totals: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    grenades_total: int = 0
    grenades_by_type: Dict[str, int] = Field(default_factory=dict)
    grenades_by_team: Dict[str, int] = Field(default_factory=dict)
    plants_total: int = 0
    plants_by_team: Dict[str, int] = Field(default_factory=dict)
    post_plant_by_team: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    defuses_by_team: Dict[str, int] = Field(default_factory=dict)
    flash_blinds_total: int = 0
    flash_blinds_by_team: Dict[str, int] = Field(default_factory=dict)
    enemy_flash_blinds_by_team: Dict[str, int] = Field(default_factory=dict)
    team_flash_blinds_by_team: Dict[str, int] = Field(default_factory=dict)
    opening_duels_by_team: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    round_summaries: List[Dict[str, Any]] = Field(default_factory=list)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    available_metrics: List[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """Stable result returned by every analysis entry point."""

    match_id: str
    map_name: str
    metrics: MatchMetrics
    analyst_report: str = ""
    coach_advice: str = ""
    coach_decision: Dict[str, Any] = Field(default_factory=dict)
    model_usage: Dict[str, Any] = Field(default_factory=dict)
    critique_score: Optional[float] = None
    ingested_tactics_count: int = 0
    current_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    retrieval_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    verification_report: Dict[str, Any] = Field(default_factory=dict)
    analysis_mode: str = "demo_forensic"
    knowledge_review: Dict[str, Any] = Field(default_factory=dict)
