from typing import Literal

from langchain_core.tools import tool

AnalysisMode = Literal[
    "demo_forensic",
    "tactical_comparison",
    "player_coaching",
    "data_quality_check",
]
TaskId = Literal["opening_duel", "utility", "round_flow", "map_context"]


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
