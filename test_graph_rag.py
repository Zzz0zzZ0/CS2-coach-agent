import asyncio
import json
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import graph as graph_router
from app.services.graph_rag_service import GraphRAGClient, _query_text


def test_graph_rag_returns_a_traceable_opening_path(tmp_path):
    client = GraphRAGClient(tmp_path / "graph.sqlite")
    connection = sqlite3.connect(client.db_path)
    connection.row_factory = sqlite3.Row
    client._create_schema(connection)
    nodes, edges = client._graph_rows(
        tmp_path / "demo-12345-map1.dem",
        {
            "match_id": "demo-12345-map1",
            "map_name": "de_mirage",
            "rounds": [{
                "round_number": 1,
                "winner": "T",
                "reason": "bomb_exploded",
                "kills": [{
                    "tick": 100,
                    "killer": "attacker",
                    "killer_steamid": "111",
                    "victim": "defender",
                    "victim_steamid": "222",
                    "assister": "support",
                    "assister_steamid": "333",
                    "weapon": "ak47",
                    "is_first_kill": True,
                }],
                "grenades": [{
                    "tick": 80,
                    "type": "Flash",
                    "thrower": "support",
                    "thrower_steamid": "333",
                }],
                "flash_blinds": [{
                    "tick": 90,
                    "attacker": "support",
                    "attacker_steamid": "333",
                    "victim": "defender",
                    "victim_steamid": "222",
                }],
                "plants": [{
                    "tick": 200,
                    "planter": "attacker",
                    "planter_steamid": "111",
                    "site": "A",
                }],
            }],
        },
    )
    connection.executemany("INSERT INTO nodes VALUES (?,?,?,?,?,?,?)", nodes)
    connection.executemany("INSERT INTO edges VALUES (?,?,?,?)", edges)
    assert client._build_communities(connection) == 4
    summaries = {
        row[0]: row[1]
        for row in connection.execute(
            "SELECT json_extract(properties, '$.topic'), summary FROM communities"
        )
    }
    assert "Opening duels:" in summaries["opening"]
    assert "Tactical labels: OPENING_DUEL 1" in summaries["opening"]
    assert "Utility usage:" in summaries["utility"]
    assert "Round flow:" in summaries["round_flow"]
    connection.commit()
    connection.close()

    evidence = asyncio.run(
        client.retrieve("Mirage opening duel first kill", {"map": "de_mirage"}, "opening_duel")
    )

    assert len(evidence) == 1
    assert evidence[0].metadata["context_level"] == "graph_path"
    assert "attacker killed defender" in evidence[0].content

    global_evidence = asyncio.run(
        client.retrieve(
            "Mirage professional opening patterns",
            {"map": "de_mirage"},
            global_search=True,
        )
    )
    assert global_evidence[0].metadata["tactic_type"] == "Graph Community Summary"
    assert "Community Summary" in global_evidence[0].content
    assert {item.metadata["topic"] for item in global_evidence} == {"opening"}

    chinese_evidence = asyncio.run(
        client.retrieve("Mirage 首杀分析", {"map": "de_mirage"}, global_search=True)
    )
    assert chinese_evidence[0].metadata["topic"] == "opening"

    projection = client.subgraph("Mirage", limit_nodes=32, limit_edges=64)
    assert {node["id"] for node in projection["nodes"]} >= {
        "player:111", "player:222", "player:333"
    }


def test_graph_roles_are_event_specific_and_players_use_steamids(tmp_path):
    client = GraphRAGClient(tmp_path / "graph.sqlite")
    nodes, edges = client._graph_rows(
        tmp_path / "demo-12345-map1.dem",
        {
            "map_name": "de_mirage",
            "rounds": [{
                "round_number": 1,
                "winner": "T",
                "reason": "bomb_exploded",
                "kills": [{
                    "killer": "attacker", "killer_steamid": "111",
                    "victim": "defender", "victim_steamid": "222",
                    "assister": "support", "assister_steamid": "333",
                }],
                "grenades": [{"thrower": "support", "thrower_steamid": "333"}],
                "flash_blinds": [{
                    "attacker": "support", "attacker_steamid": "333",
                    "victim": "defender", "victim_steamid": "222",
                }],
                "plants": [{"planter": "attacker", "planter_steamid": "111"}],
            }],
        },
    )

    relations_by_event = {}
    for source, relation, target, _ in edges:
        if source.startswith("event:"):
            relations_by_event.setdefault(source.split(":")[-2], set()).add((relation, target))

    assert relations_by_event["kill"] == {
        ("KILLER", "player:111"),
        ("VICTIM", "player:222"),
        ("ASSISTER", "player:333"),
    }
    assert relations_by_event["grenade"] == {("THROWER", "player:333")}
    assert relations_by_event["flash"] == {
        ("FLASHER", "player:333"),
        ("BLINDED", "player:222"),
    }
    assert relations_by_event["plant"] == {("PLANTER", "player:111")}
    player_nodes = {row[0]: row for row in nodes if row[1] == "player"}
    assert set(player_nodes) == {"player:111", "player:222", "player:333"}
    assert all(row[3:6] == (None, None, None) for row in player_nodes.values())


def test_graph_global_search_rejects_irrelevant_queries(tmp_path):
    client = GraphRAGClient(tmp_path / "graph.sqlite")
    connection = sqlite3.connect(client.db_path)
    connection.row_factory = sqlite3.Row
    client._create_schema(connection)
    nodes, edges = client._graph_rows(
        tmp_path / "demo-12345-map1.dem",
        {
            "map_name": "de_mirage",
            "rounds": [{
                "round_number": 1,
                "winner": "T",
                "reason": "target_bombed",
                "kills": [],
                "grenades": [],
                "flash_blinds": [],
                "plants": [],
            }],
        },
    )
    connection.executemany("INSERT INTO nodes VALUES (?,?,?,?,?,?,?)", nodes)
    connection.executemany("INSERT INTO edges VALUES (?,?,?,?)", edges)
    client._build_communities(connection)
    connection.commit()
    connection.close()

    evidence = asyncio.run(
        client.retrieve("quantum banana payroll invoice", {"map": "Mirage"}, global_search=True)
    )

    assert evidence == []


def test_round_score_prefers_requested_team():
    falcons = [("tactical_sequence", {
        "label_type": "EXECUTE_CANDIDATE", "team": "Team Falcons",
    })]
    spirit = [("tactical_sequence", {
        "label_type": "EXECUTE_CANDIDATE", "team": "Team Spirit",
    })]

    falcons_score = GraphRAGClient._round_score(
        falcons, {}, "utility", {"falcons", "execute"}, "猎鹰 execute falcons",
    )
    spirit_score = GraphRAGClient._round_score(
        spirit, {}, "utility", {"falcons", "execute"}, "猎鹰 execute falcons",
    )

    assert falcons_score > spirit_score


def test_chinese_team_aliases_expand_for_retrieval():
    assert "falcons" in _query_text("Nuke 猎鹰 execute")
    assert "spirit" in _query_text("Dust2 绿龙 补枪")


def test_silver_tactical_sequences_are_connected_and_retrievable(tmp_path):
    client = GraphRAGClient(tmp_path / "graph.sqlite")
    parsed = {
        "map_name": "de_dust2",
        "rounds": [{
            "round_number": 1,
            "start_tick": 0,
            "end_tick": 1000,
            "winner": "T",
            "reason": "target_bombed",
            "kills": [{
                "tick": 180,
                "killer": "entry", "killer_steamid": "111",
                "killer_team": "Alpha", "killer_side": "TERRORIST",
                "victim": "anchor", "victim_steamid": "222",
                "victim_team": "Bravo", "victim_side": "CT",
                "weapon": "ak47", "is_first_kill": True,
                "location": {"killer_xyz": [1, 2, 3], "victim_xyz": [4, 5, 6]},
            }],
            "grenades": [
                {
                    "tick": 100, "type": "Smoke", "thrower": "support",
                    "thrower_steamid": "333", "thrower_team": "Alpha",
                    "thrower_side": "TERRORIST", "thrower_xyz": [1, 1, 1],
                    "detonation_xyz": [10, 10, 0],
                },
                {
                    "tick": 120, "type": "Flash", "thrower": "support",
                    "thrower_steamid": "333", "thrower_team": "Alpha",
                    "thrower_side": "TERRORIST", "thrower_xyz": [1, 1, 1],
                    "detonation_xyz": [11, 10, 0],
                },
            ],
            "flash_blinds": [],
            "plants": [{
                "tick": 400, "planter": "entry", "planter_steamid": "111",
                "planter_team": "Alpha", "planter_side": "TERRORIST",
                "site": "BombsiteA", "site_entity_id": 313,
                "position": [20, 20, 0],
            }],
        }],
    }
    connection = sqlite3.connect(client.db_path)
    connection.row_factory = sqlite3.Row
    client._create_schema(connection)
    nodes, edges = client._graph_rows(tmp_path / "demo-12345-map1.dem", parsed)
    connection.executemany("INSERT INTO nodes VALUES (?,?,?,?,?,?,?)", nodes)
    connection.executemany("INSERT INTO edges VALUES (?,?,?,?)", edges)
    connection.commit()

    sequence_rows = connection.execute(
        "SELECT node_id, properties FROM nodes WHERE node_type='tactical_sequence'"
    ).fetchall()
    sequence_types = {json.loads(row["properties"])["label_type"] for row in sequence_rows}
    assert {"OPENING_DUEL", "UTILITY_BURST", "EXECUTE_CANDIDATE", "POST_PLANT"} <= sequence_types

    execute_id = next(
        row["node_id"] for row in sequence_rows
        if json.loads(row["properties"])["label_type"] == "EXECUTE_CANDIDATE"
    )
    execute_edges = {
        (row[0], row[1]) for row in connection.execute(
            "SELECT relation,target_id FROM edges WHERE source_id=?", (execute_id,)
        )
    }
    assert ("INVOLVES_PLAYER", "player:111") in execute_edges
    assert any(relation == "SUPPORTED_BY" and target.startswith("event:") for relation, target in execute_edges)
    connection.close()

    evidence = asyncio.run(
        client.retrieve("Dust2 execute utility sequence", {"map": "Dust2"}, "utility")
    )
    assert "EXECUTE_CANDIDATE" in evidence[0].content
    assert "EXECUTE_CANDIDATE" in evidence[0].metadata["tactical_labels"]
    execute_detail = next(
        item for item in evidence[0].metadata["tactical_label_details"]
        if item["label_type"] == "EXECUTE_CANDIDATE"
    )
    assert execute_detail["label_source"] == "weak_rule"
    assert execute_detail["evidence_event_ids"]


def test_cross_match_player_profiles_and_team_comparison(tmp_path, monkeypatch):
    client = GraphRAGClient(tmp_path / "graph.sqlite")
    parsed = {
        "map_name": "de_mirage",
        "rounds": [
            {
                "round_number": 1,
                "start_tick": 0,
                "end_tick": 1000,
                "winner": "T",
                "reason": "target_bombed",
                "kills": [{
                    "tick": 200,
                    "killer": "entry", "killer_steamid": "111",
                    "killer_team": "Alpha", "killer_side": "TERRORIST",
                    "victim": "anchor", "victim_steamid": "222",
                    "victim_team": "Bravo", "victim_side": "CT",
                    "assister": "support", "assister_steamid": "333",
                    "assister_team": "Alpha", "assister_side": "TERRORIST",
                    "weapon": "ak47", "is_headshot": True, "is_first_kill": True,
                }],
                "grenades": [
                    {
                        "tick": 100, "type": "Smoke", "thrower": "support",
                        "thrower_steamid": "333", "thrower_team": "Alpha",
                        "thrower_side": "TERRORIST",
                    },
                    {
                        "tick": 120, "type": "Flash", "thrower": "support",
                        "thrower_steamid": "333", "thrower_team": "Alpha",
                        "thrower_side": "TERRORIST",
                    },
                ],
                "flash_blinds": [],
                "plants": [{
                    "tick": 400, "planter": "entry", "planter_steamid": "111",
                    "planter_team": "Alpha", "planter_side": "TERRORIST", "site": "A",
                }],
            },
            {
                "round_number": 2,
                "start_tick": 1001,
                "end_tick": 2000,
                "winner": "CT",
                "reason": "ct_win",
                "kills": [{
                    "tick": 1300,
                    "killer": "anchor", "killer_steamid": "222",
                    "killer_team": "Bravo", "killer_side": "CT",
                    "victim": "entry", "victim_steamid": "111",
                    "victim_team": "Alpha", "victim_side": "TERRORIST",
                    "weapon": "m4a1", "is_headshot": False, "is_first_kill": True,
                }],
                "grenades": [],
                "flash_blinds": [],
                "plants": [],
            },
        ],
    }
    connection = sqlite3.connect(client.db_path)
    connection.row_factory = sqlite3.Row
    client._create_schema(connection)
    nodes, edges = client._graph_rows(tmp_path / "demo-12345-map1.dem", parsed)
    connection.executemany("INSERT INTO nodes VALUES (?,?,?,?,?,?,?)", nodes)
    connection.executemany("INSERT INTO edges VALUES (?,?,?,?)", edges)
    second_nodes, second_edges = client._graph_rows(
        tmp_path / "demo-12345-map2.dem",
        {
            "map_name": "de_nuke",
            "rounds": [{
                "round_number": 1,
                "winner": "CT",
                "reason": "ct_win",
                "kills": [{
                    "tick": 300,
                    "killer": "substitute", "killer_steamid": "444",
                    "killer_team": "Alpha", "killer_side": "CT",
                    "victim": "anchor", "victim_steamid": "222",
                    "victim_team": "Bravo", "victim_side": "TERRORIST",
                    "weapon": "m4a1", "is_first_kill": True,
                }],
                "grenades": [], "flash_blinds": [], "plants": [],
            }],
        },
    )
    connection.executemany("INSERT OR REPLACE INTO nodes VALUES (?,?,?,?,?,?,?)", second_nodes)
    connection.executemany("INSERT OR REPLACE INTO edges VALUES (?,?,?,?)", second_edges)
    connection.commit()
    connection.close()

    alpha_players = client.players(team="Alpha")
    assert {player["name"] for player in alpha_players} == {"entry", "support", "substitute"}
    entry = client.player_profile("111")
    assert entry["team"] == "Alpha"
    assert entry["sample_size"] == {
        "matches": 1, "maps": 1, "map_pool_size": 1, "rounds": 2,
    }
    assert entry["combat"]["kills"] == 1
    assert entry["combat"]["deaths"] == 1
    assert entry["combat"]["opening_duel_win_pct"] == 50.0
    assert entry["rates_per_100_rounds"]["kills"] == 50.0
    assert entry["source_round_ids"]
    assert client.player_profile("444")["sample_size"]["rounds"] == 1

    comparison = client.compare_teams(["Alpha", "Bravo"])
    assert [team["team"] for team in comparison["teams"]] == ["Alpha", "Bravo"]
    alpha = comparison["teams"][0]
    assert alpha["sample_size"]["rounds"] == 3
    assert alpha["labels"]["OPENING_DUEL"] == {"count": 2, "per_100_rounds": 66.67}
    assert comparison["methodology"]["causality"].startswith("descriptive")

    tactics = client.team_tactics(
        "Alpha", map_name="Mirage", side="T", opponent="Bravo",
    )
    assert tactics["sample_size"] == {
        "matches": 1, "maps": 1, "rounds": 2, "decided_rounds": 2,
    }
    assert tactics["outcomes"] == {"rounds_won": 1, "round_win_pct": 50.0}
    assert tactics["conversions"]["opening_won"]["round_win_pct"] == 100.0
    assert tactics["conversions"]["opening_lost_recovery"]["round_win_pct"] == 0.0
    assert tactics["conversions"]["post_plant"]["round_win_pct"] == 100.0
    assert tactics["role_leaders"]["opening_kills"][0]["name"] == "entry"
    assert tactics["site_breakdown"][0]["site"] == "A"
    assert tactics["source_round_ids"]
    assert tactics["round_examples"]["opening_won"][0]["outcome"] == "won"
    assert tactics["round_examples"]["opening_lost_recovery"][0]["outcome"] == "lost"
    assert client.team_tactics("does-not-exist") is None
    empty_slice = client.team_tactics("Alpha", map_name="Inferno")
    assert empty_slice["sample_size"]["rounds"] == 0
    assert empty_slice["outcomes"]["round_win_pct"] is None

    profile_evidence = asyncio.run(client.retrieve(
        "Alpha 对阵 Bravo 的 Mirage T侧首杀战术",
        {"map": "Nuke"},
        global_search=True,
    ))
    assert profile_evidence[0].metadata["context_level"] == "team_tactical_profile"
    assert profile_evidence[0].metadata["map"] == "Mirage"
    assert profile_evidence[0].metadata["side"] == "T"
    assert profile_evidence[0].metadata["opponent"] == "Bravo"
    assert "Opening won: 1 rounds" in profile_evidence[0].content
    assert "Graph source paths:" in profile_evidence[0].content
    profile_brief = client.coach_brief(
        "Alpha 对阵 Bravo 的 Mirage T侧首杀战术", profile_evidence,
    )
    assert profile_brief["kind"] == "team_profile"
    assert profile_brief["focus_metric"]["key"] == "opening_won"
    assert profile_brief["sources"][0]["id"] == "G1"
    assert profile_brief["sources"][0]["round_id"] == tactics["round_examples"]["opening_won"][0]["source_id"]
    assert {group["key"] for group in profile_brief["round_groups"]} >= {"all", "opening_won", "post_plant"}
    assert "silver labels" in profile_brief["caveat"]
    round_detail = client.round_detail(profile_brief["sources"][0]["round_id"])
    assert round_detail["map"] == "Mirage"
    assert round_detail["round_number"] == 1
    assert {item["kind"] for item in round_detail["timeline"]} >= {"kill", "plant"}
    assert client.round_detail("invalid-source") is None
    contrast = client.round_comparison("graph:12345:Mirage:2", "Alpha")
    assert contrast["selected"]["outcome"] == "lost"
    assert contrast["selected"]["side"] == "T"
    assert contrast["contrasts"][0]["source_id"] == "graph:12345:Mirage:1"
    assert contrast["contrasts"][0]["outcome"] == "won"
    assert client.round_comparison("invalid-source", "Alpha") is None

    comparison_evidence = asyncio.run(client.retrieve(
        "对比 Alpha 和 Bravo 在 Mirage 的补枪差异",
        {"map": "Mirage"},
        global_search=True,
    ))
    assert comparison_evidence[0].metadata["context_level"] == "team_tactical_comparison"
    assert comparison_evidence[0].metadata["teams"] == ["Alpha", "Bravo"]
    comparison_brief = client.coach_brief(
        "对比 Alpha 和 Bravo 在 Mirage 的补枪差异", comparison_evidence,
    )
    assert comparison_brief["kind"] == "comparison"
    assert comparison_brief["focus_metric"]["key"] == "trade_round"
    assert any(group["key"] == "trade_round" for group in comparison_brief["round_groups"])

    api = FastAPI()
    api.include_router(graph_router.router, prefix="/api")
    monkeypatch.setattr(graph_router, "get_graph_client", lambda: client)
    http = TestClient(api)
    assert http.get("/api/graph/players?team=Alpha").status_code == 200
    assert http.get("/api/graph/players/111").json()["profile"]["name"] == "entry"
    response = http.get("/api/graph/teams/compare?teams=Alpha,Bravo")
    assert response.status_code == 200
    assert len(response.json()["teams"]) == 2
    response = http.get(
        "/api/graph/teams/Alpha/tactics?map_name=Mirage&side=T&opponent=Bravo"
    )
    assert response.status_code == 200
    assert response.json()["profile"]["outcomes"]["round_win_pct"] == 50.0
    assert http.get("/api/graph/teams/Alpha/tactics?side=invalid").status_code == 422
    assert http.get("/api/graph/players/does-not-exist").status_code == 404
    response = http.get(
        "/api/graph/search", params={"q": "Alpha 对阵 Bravo 的 Mirage T侧首杀战术"},
    )
    assert response.status_code == 200
    assert response.json()["answer"]["kind"] == "team_profile"
    source_id = response.json()["answer"]["sources"][0]["round_id"]
    response = http.get("/api/graph/round", params={"source_id": source_id})
    assert response.status_code == 200
    assert response.json()["detail"]["timeline"]
    response = http.get("/api/graph/round", params={"source_id": "graph:12345:Mirage:2", "team": "Alpha"})
    assert response.status_code == 200
    assert response.json()["comparison"]["contrasts"][0]["outcome"] == "won"
    assert http.get("/api/graph/round", params={"source_id": "invalid"}).status_code == 404
