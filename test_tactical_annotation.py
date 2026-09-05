from app.services.tactical_annotation_service import annotate_match, summarize_annotations


def _parsed_match():
    return {
        "match_id": "fixture",
        "map_name": "de_dust2",
        "rounds": [{
            "round_number": 1,
            "start_tick": 0,
            "freeze_end_tick": 64,
            "end_tick": 1200,
            "winner": "T",
            "reason": "target_bombed",
            "kills": [
                {
                    "tick": 400, "killer": "entry", "killer_steamid": "1",
                    "killer_team": "Alpha", "killer_side": "TERRORIST",
                    "victim": "anchor", "victim_steamid": "2",
                    "victim_team": "Bravo", "victim_side": "CT",
                    "weapon": "ak47", "is_first_kill": True,
                    "location": {"killer_xyz": [1, 2, 3], "victim_xyz": [4, 5, 6]},
                },
                {
                    "tick": 600, "killer": "trader", "killer_steamid": "3",
                    "killer_team": "Bravo", "killer_side": "CT",
                    "victim": "entry", "victim_steamid": "1",
                    "victim_team": "Alpha", "victim_side": "TERRORIST",
                    "weapon": "m4a1", "is_first_kill": False,
                    "location": {"killer_xyz": [7, 8, 9], "victim_xyz": [1, 2, 3]},
                },
                {
                    "tick": 900, "killer": "entry2", "killer_steamid": "4",
                    "killer_team": "Alpha", "killer_side": "TERRORIST",
                    "victim": "trader", "victim_steamid": "3",
                    "victim_team": "Bravo", "victim_side": "CT",
                    "weapon": "ak47", "is_first_kill": False,
                    "location": {"killer_xyz": [1, 2, 3], "victim_xyz": [7, 8, 9]},
                },
            ],
            "grenades": [
                {
                    "tick": 300, "type": "Smoke", "thrower": "support",
                    "thrower_steamid": "5", "thrower_team": "Alpha",
                    "thrower_side": "TERRORIST", "thrower_xyz": [0, 0, 0],
                    "detonation_xyz": [10, 10, 0],
                },
                {
                    "tick": 330, "type": "Flash", "thrower": "support",
                    "thrower_steamid": "5", "thrower_team": "Alpha",
                    "thrower_side": "TERRORIST", "thrower_xyz": [0, 0, 0],
                    "detonation_xyz": [11, 10, 0],
                },
                {
                    "tick": 350, "type": "HE", "thrower": "entry",
                    "thrower_steamid": "1", "thrower_team": "Alpha",
                    "thrower_side": "TERRORIST", "thrower_xyz": [0, 0, 0],
                    "detonation_xyz": [12, 10, 0],
                },
            ],
            "plants": [{
                "tick": 500, "planter": "support", "planter_steamid": "5",
                "planter_team": "Alpha", "planter_side": "TERRORIST",
                "site": "A", "position": [10, 10, 0],
            }],
            "flash_blinds": [],
        }],
    }


def test_annotation_builds_traceable_tactical_and_player_labels():
    records = annotate_match(_parsed_match(), source_demo="fixture.dem", match_id="42")
    record = records[0]
    labels = {label["label_type"]: label for label in record["labels"]}
    trades = [label for label in record["labels"] if label["label_type"] == "TRADE_KILL"]

    assert record["map_name"] == "Dust2"
    assert len({event["event_id"] for event in record["events"]}) == len(record["events"])
    assert labels["OPENING_DUEL"]["details"]["winner_steamid"] == "1"
    assert trades[0]["details"]["trader_steamid"] == "3"
    assert trades[0]["details"]["response_ticks"] == 200
    assert labels["UTILITY_BURST"]["details"]["side"] == "T"
    assert labels["EXECUTE_CANDIDATE"]["details"]["utility_count"] == 3
    assert labels["EXECUTE_CANDIDATE"]["review_status"] == "auto_accepted"
    assert labels["POST_PLANT"]["site"] == "A"
    assert labels["RETAKE_CONTACT"]["review_status"] == "auto_accepted"

    quality = summarize_annotations(records)
    assert quality["rounds"] == 1
    assert quality["player_id_coverage"] == 1.0
    assert quality["actor_team_coverage"] == 1.0
    assert quality["label_policy"].startswith("AI-assisted silver")
    assert quality["integrity"] == {
        "missing_evidence_refs": 0,
        "duplicate_event_ids": 0,
        "tick_boundary_violations": 0,
    }


def test_annotation_does_not_invent_an_execute_without_team_context():
    parsed = _parsed_match()
    for grenade in parsed["rounds"][0]["grenades"]:
        grenade["thrower_team"] = None

    record = annotate_match(parsed, source_demo="fixture.dem")[0]

    assert "EXECUTE_CANDIDATE" not in {label["label_type"] for label in record["labels"]}


def test_annotation_does_not_invent_trades_without_team_context():
    parsed = _parsed_match()
    for kill in parsed["rounds"][0]["kills"]:
        for field in ("killer_team", "killer_side", "victim_team", "victim_side"):
            kill[field] = None

    record = annotate_match(parsed, source_demo="fixture.dem")[0]

    assert "TRADE_KILL" not in {label["label_type"] for label in record["labels"]}
