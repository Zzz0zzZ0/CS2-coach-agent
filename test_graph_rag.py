import asyncio
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
                    "victim": "defender",
                    "weapon": "ak47",
                    "is_first_kill": True,
                }],
                "grenades": [],
                "flash_blinds": [],
                "plants": [],
            }],
        },
    )
    connection.executemany("INSERT INTO nodes VALUES (?,?,?,?,?,?,?)", nodes)
    connection.executemany("INSERT INTO edges VALUES (?,?,?,?)", edges)
    assert client._build_communities(connection) == 4
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
