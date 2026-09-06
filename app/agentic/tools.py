from typing import Literal

from langchain_core.tools import tool

AnalysisMode = Literal[
    "demo_forensic",
    "tactical_comparison",
    "player_coaching",
    "data_quality_check",
]
TaskId = Literal["opening_duel", "utility", "round_flow", "map_context"]
CoachingPriority = Literal[
    "opening_followup",
    "post_plant",
    "utility_review",
    "side_transition",
]


@tool
def select_analysis_plan(
    mode: AnalysisMode,
    task_ids: list[TaskId],
    reason: str = "",
) -> dict:
    """Select one bounded CS2 analysis mode and the retrieval tasks it needs.

    This tool only returns a validated plan. It cannot execute code, write data,
    ingest knowledge, or access the network.
    """
    return {"mode": mode, "task_ids": task_ids, "reason": reason}


@tool
def select_coaching_priorities(
    priority_ids: list[CoachingPriority],
    reason: str = "",
) -> dict:
    """Select two or three coaching priorities from a fixed allowlist.

    The returned IDs only control ordering of deterministic, evidence-backed
    advice. The model cannot author facts, citations, or final report text.
    """
    unique = list(dict.fromkeys(priority_ids))
    return {"priority_ids": unique[:3], "reason": reason}
