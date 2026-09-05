import asyncio
import json
import sqlite3

from app.services.graph_rag_service import GraphRAGClient


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
