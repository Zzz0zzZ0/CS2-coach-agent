"""模拟示例: small synthetic records verify contracts, never real-match model quality."""

import pandas as pd
import pytest

from app.services.parser_service import TacticalDemoParser


class OpeningFixture:
    def parse_header(self):
        return {"map_name": "de_mirage"}

    def parse_event(self, name, **kwargs):
        return pd.DataFrame({
            "round_end": [{"round": 1, "tick": 2000, "winner": "CT"}],
            "round_freeze_end": [{"tick": 100}],
        }.get(name, []))

    def parse_ticks(self, wanted_props, *, ticks):
        return pd.DataFrame([
            {"tick": tick, "steamid": player, "team_name": side,
             "team_clan_name": side, "X": player * 10, "Y": 20, "Z": 30,
             "health": 0 if player == 1 and tick > 100 else 100,
             "current_equip_value": 3000, "last_place_name": "TopMid"}
            for tick in ticks for side, players in (("CT", range(1, 6)), ("TERRORIST", range(6, 11)))
            for player in players
        ])


def make_parser(fixture=None):
    parser = TacticalDemoParser.__new__(TacticalDemoParser)
    parser.demo_path = "synthetic.dem"
    parser.parser = fixture or OpeningFixture()
    return parser


def test_both_sides_and_deaths_are_preserved_without_outcomes():
    result = make_parser().parse_opening_snapshots()
    assert [r["side"] for r in result["rounds"]] == ["CT", "T"]
    assert all(r["status"] == "ok" for r in result["rounds"])
    ct = result["rounds"][0]
    assert [s["tick"] for s in ct["snapshots"]] == [740, 868, 1060, 1252, 1380]
    assert len(ct["snapshots"][0]["players"]) == 5
    assert ct["snapshots"][0]["players"][0]["alive"] is False
    assert "winner" not in ct
    assert result["tick_rate_status"] == "assumed_not_measured"


@pytest.mark.parametrize("problem,reason", [
    ("missing_player", "snapshot_roster_mismatch"),
    ("duplicate_player", "snapshot_roster_mismatch"),
    ("nan", "invalid_player_state"),
])
def test_incomplete_or_invalid_snapshots_have_no_partial_success(problem, reason):
    class Broken(OpeningFixture):
        def parse_ticks(self, props, *, ticks):
            frame = super().parse_ticks(props, ticks=ticks)
            if max(ticks) == 100:
                return frame
            if problem == "missing_player":
                return frame[~((frame.tick == max(ticks)) & (frame.steamid == 1))]
            if problem == "duplicate_player":
                return pd.concat([frame, frame[(frame.tick == max(ticks)) & (frame.steamid == 1)]])
            frame.loc[(frame.tick == max(ticks)) & (frame.steamid == 1), "X"] = float("nan")
            return frame
    result = make_parser(Broken()).parse_opening_snapshots()
    assert result["rounds"][0]["reason"] == reason
    assert result["rounds"][0]["snapshots"] == []
    assert result["rounds"][1]["status"] == "ok"


def test_short_round_is_not_padded():
    class Short(OpeningFixture):
        def parse_event(self, name, **kwargs):
            if name == "round_end":
                return pd.DataFrame([{"round": 1, "tick": 900, "winner": "CT"}])
            return super().parse_event(name, **kwargs)
    assert all(r["reason"] == "round_ended_before_final_snapshot"
               for r in make_parser(Short()).parse_opening_snapshots()["rounds"])


def test_invalid_limit_is_rejected():
    with pytest.raises(ValueError):
        make_parser().parse_opening_snapshots(max_rounds=0)
