import pandas as pd

from app.services.parser_service import TacticalDemoParser


class _DemoParserFixture:
    def __init__(self):
        self.requested_events = []

    def parse_header(self):
        return {"map_name": "de_mirage"}

    def parse_event(self, event_name, *, player=None, other=None):
        self.requested_events.append(event_name)
        rows = {
            "round_end": [{"round": 1, "tick": 1000, "winner": "T", "reason": "target_bombed"}],
            "round_freeze_end": [{"tick": 50}],
            "player_death": [{
                "tick": 300,
                "attacker_name": "entry", "attacker_steamid": 111,
                "attacker_team_clan_name": "Alpha", "attacker_team_name": "TERRORIST",
                "attacker_last_place_name": "LongDoors",
                "user_name": "anchor", "user_steamid": 222,
                "user_team_clan_name": "Bravo", "user_team_name": "CT",
                "user_last_place_name": "BombsiteA",
                "assister_name": "support", "assister_steamid": 333,
                "assister_team_clan_name": "Alpha", "assister_team_name": "TERRORIST",
                "assistedflash": True, "distance": 420.0, "thrusmoke": True,
                "attackerblind": False, "weapon": "ak47", "headshot": True,
                "attacker_X": 1, "attacker_Y": 2, "attacker_Z": 3,
                "user_X": 4, "user_Y": 5, "user_Z": 6,
            }],
            "smokegrenade_detonate": [{
                "tick": 100, "user_name": "support", "user_steamid": 333,
                "user_team_clan_name": "Alpha", "user_team_name": "TERRORIST",
                "user_last_place_name": "TopMid",
                "user_X": 1, "user_Y": 2, "user_Z": 3, "x": 10, "y": 20, "z": 30,
            }],
            "flashbang_detonate": [{
                "tick": 110, "user_name": "support", "user_steamid": 333,
                "user_X": 1, "user_Y": 2, "user_Z": 3, "x": 11, "y": 21, "z": 31,
            }],
            "inferno_startburn": [{
                "tick": 120, "user_name": "support", "user_steamid": 333,
                "user_X": 1, "user_Y": 2, "user_Z": 3, "x": 12, "y": 22, "z": 32,
            }],
            "hegrenade_detonate": [{
                "tick": 130, "user_name": "support", "user_steamid": 333,
                "user_X": 1, "user_Y": 2, "user_Z": 3, "x": 13, "y": 23, "z": 33,
            }],
            "bomb_planted": [{
                "tick": 500, "user_name": "entry", "user_steamid": 111,
                "user_team_clan_name": "Alpha", "user_team_name": "TERRORIST",
                "user_last_place_name": "BombsiteA",
                "user_X": 7, "user_Y": 8, "user_Z": 9, "site": "A",
            }],
        }
        return pd.DataFrame(rows.get(event_name, []))


def test_parser_preserves_player_ids_and_current_utility_events():
    fixture = _DemoParserFixture()
    parser = TacticalDemoParser.__new__(TacticalDemoParser)
    parser.demo_path = "fixture.dem"
    parser.parser = fixture

    result = parser.parse_to_dict()
    round_data = result["rounds"][0]
    kill = round_data["kills"][0]

    assert kill["killer_steamid"] == 111
    assert kill["victim_steamid"] == 222
    assert kill["assister_steamid"] == 333
    assert kill["killer_team"] == "Alpha"
    assert kill["victim_team"] == "Bravo"
    assert kill["killer_side"] == "TERRORIST"
    assert kill["killer_area"] == "LongDoors"
    assert kill["victim_area"] == "BombsiteA"
    assert kill["assisted_flash"] is True
    assert kill["through_smoke"] is True
    assert {item["type"] for item in round_data["grenades"]} == {
        "Smoke", "Flash", "Molotov/Incendiary", "HE"
    }
    assert round_data["grenades"][0]["detonation_xyz"] == [10, 20, 30]
    assert round_data["grenades"][0]["thrower_xyz"] == [1, 2, 3]
    assert round_data["grenades"][0]["thrower_steamid"] == 333
    assert round_data["grenades"][0]["thrower_team"] == "Alpha"
    assert round_data["grenades"][0]["thrower_area"] == "TopMid"
    assert round_data["plants"][0]["planter_steamid"] == 111
    assert round_data["plants"][0]["planter_team"] == "Alpha"
    assert round_data["plants"][0]["site"] == "BombsiteA"
    assert round_data["plants"][0]["position"] == [7, 8, 9]
    assert round_data["freeze_end_tick"] == 50
    assert round_data["end_tick"] == 1000
    assert "inferno_startburn" in fixture.requested_events
    assert "flashbang_detonate" in fixture.requested_events
