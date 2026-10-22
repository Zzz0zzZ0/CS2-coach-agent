"""模拟示例: engine-clock, pause and formal-round audit contracts."""

import pandas as pd
import pytest

from app.services.opening_timing_service import CLOCK_PROPERTIES, RULES, audit_opening_timing, round_wins_from_rosters


@pytest.mark.parametrize("problem", [None, "offset", "pause", "counter", "warmup", "round", "start", "missing", "disagree"])
def test_timing_audit(problem):
    rounds = [{"round_number": 3, "side": "CT", "status": "ok", "freeze_end_tick": 6400}]
    frame = pd.DataFrame([{**dict(zip(CLOCK_PROPERTIES, [100.0 + i, 0, False, False, 100.0, 2])),
                           "tick": 6400 + i * 64} for i in range(21)])
    reason = {"offset": "clock_offset_mismatch", "pause": "pause_in_opening", "counter": "pause_in_opening",
              "warmup": "warmup_in_opening", "round": "engine_round_number_mismatch", "start": "engine_round_start_mismatch",
              "missing": "missing_or_inconsistent_clock_samples", "disagree": "missing_or_inconsistent_clock_samples"}
    if problem == "offset":
        frame.loc[10, "game_time"] += .5
    elif problem == "pause":
        frame.loc[10, RULES + "m_bGamePaused"] = True
    elif problem == "counter":
        frame.loc[10:, RULES + "m_nTotalPausedTicks"] = 32
    elif problem == "warmup":
        frame.loc[10, RULES + "m_bWarmupPeriod"] = True
    elif problem == "round":
        frame.loc[10, RULES + "m_totalRoundsPlayed"] = 9
    elif problem == "start":
        frame.loc[10, RULES + "m_fRoundStartTime"] = 101
    elif problem == "missing":
        frame = frame.iloc[:-1]
    elif problem == "disagree":
        duplicate = frame.iloc[[10]].copy(); duplicate["game_time"] += 1
        frame = pd.concat([frame, duplicate])
    report = audit_opening_timing(rounds, frame)
    assert report["rounds"][0]["passed"] == (problem is None)
    if problem:
        assert reason[problem] in report["rounds"][0]["reasons"]


def test_score_audit_uses_freeze_rosters_even_for_short_rounds():
    rosters = {1: {"participants": [{"team": "A", "side": "CT"}, {"team": "B", "side": "T"}]},
               2: {"participants": [{"team": "A", "side": "T"}, {"team": "B", "side": "CT"}]}}
    assert round_wins_from_rosters(["CT", "T", "CT"], rosters) == {"A": 2, "unknown": 1}
