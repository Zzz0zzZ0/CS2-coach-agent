"""Audit opening offsets against engine clocks and pause state, without changing old extracts."""

import numpy as np
import pandas as pd
from collections import Counter

RULES = "CCSGameRulesProxy.CCSGameRules."
CLOCK_PROPERTIES = ["game_time"] + [RULES + name for name in (
    "m_nTotalPausedTicks", "m_bGamePaused", "m_bWarmupPeriod", "m_fRoundStartTime", "m_totalRoundsPlayed")]


def round_wins_from_rosters(winners, rosters):
    counts = Counter()
    for number, side in enumerate(winners, 1):
        teams = {p["team"] for p in rosters.get(number, {}).get("participants", [])
                 if p["side"] == side and p.get("team")}
        counts[next(iter(teams)) if len(teams) == 1 else "unknown"] += 1
    return dict(counts)


def audit_opening_timing(rounds, frame):
    results = []
    for row in rounds:
        if row["side"] != "CT":
            continue
        item = {"round_number": row["round_number"], "passed": False, "reasons": []}
        results.append(item)
        if row["status"] != "ok":
            item["reasons"].append("snapshot_ineligible:" + row["reason"])
            continue
        if not {"tick", *CLOCK_PROPERTIES}.issubset(frame.columns):
            item["reasons"].append("missing_clock_fields")
            continue
        ticks = [row["freeze_end_tick"] + second * 64 for second in range(21)]
        selected = frame[frame["tick"].isin(ticks)][["tick", *CLOCK_PROPERTIES]].drop_duplicates()
        if len(selected) != 21 or selected["tick"].nunique() != 21:
            item["reasons"].append("missing_or_inconsistent_clock_samples")
            continue
        selected = selected.set_index("tick").loc[ticks]
        values = selected[CLOCK_PROPERTIES].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            item["reasons"].append("nonfinite_clock_state")
            continue
        elapsed = selected["game_time"].to_numpy() - selected["game_time"].iloc[0]
        item["max_offset_error_seconds"] = float(np.max(np.abs(elapsed - np.arange(21))))
        item["paused_tick_delta"] = int(selected[RULES + "m_nTotalPausedTicks"].max() - selected[RULES + "m_nTotalPausedTicks"].iloc[0])
        if item["max_offset_error_seconds"] > 1 / 64:
            item["reasons"].append("clock_offset_mismatch")
        if item["paused_tick_delta"] != 0 or selected[RULES + "m_bGamePaused"].any():
            item["reasons"].append("pause_in_opening")
        if selected[RULES + "m_bWarmupPeriod"].any():
            item["reasons"].append("warmup_in_opening")
        if not (selected[RULES + "m_totalRoundsPlayed"] == row["round_number"] - 1).all():
            item["reasons"].append("engine_round_number_mismatch")
        start_error = np.abs(selected["game_time"].iloc[0] - selected[RULES + "m_fRoundStartTime"].to_numpy()).max()
        item["max_round_start_error_seconds"] = float(start_error)
        if start_error > 1 / 64:
            item["reasons"].append("engine_round_start_mismatch")
        item["passed"] = not item["reasons"]
    return {"scope": "engine-clock consistency at 1-second intervals; not wall-clock or navigation validation",
            "assumed_tick_rate": 64, "samples_per_eligible_round": 21,
            "rounds": results, "passed": sum(r["passed"] for r in results), "total": len(results)}
