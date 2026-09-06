import pandas as pd

from app.services.parser_service import TacticalDemoParser


class _DemoParserFixture:
    def __init__(self):
        self.requested_events = []
        self.requested_ticks = []

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
                "user_team_clan_name": "Alpha", "user_team_name": "TERRORIST",
                "user_last_place_name": "TopMid",
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

    def parse_ticks(self, wanted_props, *, players=None, ticks=None, prop_states=None):
        self.requested_ticks.append((wanted_props, ticks))
        return pd.DataFrame([
            {
                "tick": 109, "steamid": 222, "name": "anchor",
                "flash_duration": 0.0, "health": 100,
                "team_clan_name": "Bravo", "team_name": "CT",
                "last_place_name": "BombsiteA", "X": 4, "Y": 5, "Z": 6,
            },
            {
                "tick": 110, "steamid": 222, "name": "anchor",
                "flash_duration": 2.5, "health": 100,
                "team_clan_name": "Bravo", "team_name": "CT",
                "last_place_name": "BombsiteA", "X": 4, "Y": 5, "Z": 6,
            },
        ])


class _InterruptedDemoParserFixture(_DemoParserFixture):
    def parse_event(self, event_name, *, player=None, other=None):
        if event_name == "round_end":
            return pd.DataFrame([
                {"round": 1, "tick": 1000, "winner": "T", "reason": "target_bombed"},
                {"round": 2, "tick": 1100, "winner": None, "reason": None},
                {"round": 2, "tick": 1200, "winner": None, "reason": None},
                {"round": 2, "tick": 2000, "winner": "CT", "reason": "t_killed"},
            ])
        return super().parse_event(event_name, player=player, other=other)


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
    assert round_data["flash_blinds"] == [{
        "tick": 110,
        "victim": "anchor",
        "victim_steamid": 222,
        "victim_team": "Bravo",
        "victim_side": "CT",
        "victim_area": "BombsiteA",
        "attacker": "support",
        "attacker_steamid": 333,
        "attacker_team": "Alpha",
        "attacker_side": "TERRORIST",
        "attacker_area": "TopMid",
        "blind_duration": 2.5,
        "victim_xyz": [4, 5, 6],
        "flash_xyz": [11, 21, 31],
        "source": "flash_duration_delta",
    }]
    assert fixture.requested_ticks[0][1] == [109, 110]
    assert round_data["plants"][0]["planter_steamid"] == 111
    assert round_data["plants"][0]["planter_team"] == "Alpha"
    assert round_data["plants"][0]["site"] == "BombsiteA"
    assert round_data["plants"][0]["position"] == [7, 8, 9]
    assert round_data["freeze_end_tick"] == 50
    assert round_data["end_tick"] == 1000
    assert "inferno_startburn" in fixture.requested_events
    assert "flashbang_detonate" in fixture.requested_events


def test_parser_preserves_thrower_candidates_for_simultaneous_flashes():
    parser = TacticalDemoParser.__new__(TacticalDemoParser)
    parser.demo_path = "fixture.dem"
    parser.parser = _DemoParserFixture()
    flashes = pd.DataFrame([
        {
            "tick": 110, "user_name": "support", "user_steamid": 333,
            "user_team_clan_name": "Alpha", "user_team_name": "TERRORIST",
            "user_last_place_name": "TopMid", "x": 11, "y": 21, "z": 31,
        },
        {
            "tick": 110, "user_name": "entry", "user_steamid": 111,
            "user_team_clan_name": "Alpha", "user_team_name": "TERRORIST",
            "user_last_place_name": "Apartments", "x": 15, "y": 25, "z": 35,
        },
    ])

    records = parser._flash_blind_frame(pd.DataFrame(), flashes).to_dict("records")

    assert len(records) == 1
    assert records[0]["attacker"] == "support / entry"
    assert records[0]["attacker_steamid"] is None
    assert records[0]["attacker_team"] == "Alpha"
    assert records[0]["attribution"] == "simultaneous_flash_candidates"
    assert [candidate["name"] for candidate in records[0]["attacker_candidates"]] == [
        "support", "entry"
    ]


def test_parser_excludes_interruption_round_end_events_without_a_winner():
    parser = TacticalDemoParser.__new__(TacticalDemoParser)
    parser.demo_path = "fixture.dem"
    parser.parser = _InterruptedDemoParserFixture()

    rounds = parser.parse_to_dict()["rounds"]

    assert [item["round_number"] for item in rounds] == [1, 2]
    assert [item["winner"] for item in rounds] == ["T", "CT"]
    assert [item["end_tick"] for item in rounds] == [1000, 2000]


def test_round_roster_uses_freeze_snapshot_and_rejects_partial_completeness():
    class RosterFixture(_DemoParserFixture):
        def parse_ticks(self, wanted_props, **kwargs):
            assert kwargs['ticks'] == [50]
            return pd.DataFrame([{'tick':50, 'steamid':str(100+i), 'name':f'p{i}',
                'team_name':'TERRORIST' if i<5 else 'CT', 'team_clan_name':'Alpha' if i<5 else 'Bravo'} for i in range(10)])
    parser = TacticalDemoParser('absent.dem')
    parser.parser = RosterFixture()
    roster = parser.parse_round_rosters()[1]
    assert roster['participants_complete'] is True
    assert len(roster['participants']) == 10
    parser.parser = _DemoParserFixture()
    assert parser.parse_round_rosters()[1]['participants_complete'] is False
