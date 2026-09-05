"""Deterministic, local GraphRAG sidecar for parsed CS2 demo evidence.

The graph is deliberately factual: it stores parser output and relationships,
but never asks an LLM to invent nodes or edges.
"""
import asyncio
import json
import logging
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from app.services.rag_service import Evidence

logger = logging.getLogger(__name__)

MAP_NAMES = {
    "de_ancient": "Ancient",
    "de_dust2": "Dust2",
    "de_inferno": "Inferno",
    "de_mirage": "Mirage",
    "de_nuke": "Nuke",
    "de_overpass": "Overpass",
    "de_vertigo": "Vertigo",
}


def _text(value: Any, fallback: str = "Unknown") -> str:
    if value is None or str(value) in {"", "None", "nan"}:
        return fallback
    return str(value)


def _map_name(value: str) -> str:
    raw = _text(value)
    return MAP_NAMES.get(raw.lower(), raw.removeprefix("de_").title())


def _match_id(path: Path, parsed: dict) -> str:
    parsed_id = _text(parsed.get("match_id"), "")
    match = re.search(r"(?:-|_)(\d{5,})(?:-|_|$)", path.stem)
    return match.group(1) if match else (parsed_id or path.stem)


def _json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _player_identity(event: dict, name_key: str, steamid_key: str) -> tuple[str, str, str] | None:
    name = _text(event.get(name_key), "").strip()
    steamid = _text(event.get(steamid_key), "").strip()
    if steamid and steamid not in {"0", "Unknown", "nan"}:
        return f"player:{steamid}", name or steamid, steamid
    if name and name not in {"Unknown", "nan", "None"}:
        return f"player:{name}", name, ""
    return None


class GraphRAGClient:
    """Small graph interface: build once, retrieve traceable graph evidence."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def available(self) -> bool:
        return self.db_path.exists()

    def build_from_demo_dir(self, demo_dir: str | Path) -> dict[str, int]:
        from app.services.parser_service import TacticalDemoParser

        demo_paths = sorted(Path(demo_dir).glob("*.dem"))
        if not demo_paths:
            raise FileNotFoundError(f"No .dem files found in {demo_dir}")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            self.db_path.unlink()

        connection = self._connect()
        self._create_schema(connection)
        node_count = edge_count = demo_count = 0
        try:
            for demo_path in demo_paths:
                parsed = TacticalDemoParser(str(demo_path)).parse_to_dict()
                rounds = parsed.get("rounds", []) if parsed else []
                if not rounds:
                    logger.warning("Skipping demo without parsed rounds: %s", demo_path)
                    continue
                nodes, edges = self._graph_rows(demo_path, parsed)
                connection.executemany(
                    "INSERT OR REPLACE INTO nodes "
                    "(node_id,node_type,label,map_name,match_id,round_number,properties) "
                    "VALUES (?,?,?,?,?,?,?)",
                    nodes,
                )
                connection.executemany(
                    "INSERT OR REPLACE INTO edges "
                    "(source_id,relation,target_id,properties) VALUES (?,?,?,?)",
                    edges,
                )
                node_count += len(nodes)
                edge_count += len(edges)
                demo_count += 1
            community_count = self._build_communities(connection)
            connection.commit()
            node_count = connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            edge_count = connection.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        finally:
            connection.close()
        return {
            "demos": demo_count,
            "nodes": node_count,
            "edges": edge_count,
            "communities": community_count,
        }

    async def retrieve(
        self,
        query: str,
        metadata_filter: dict | None = None,
        task_id: str | None = None,
        k: int = 4,
        global_search: bool = False,
    ) -> list[Evidence]:
        if not self.available():
            return []
        if global_search:
            return await asyncio.to_thread(
                self._global_search_sync, query, metadata_filter or {}, k
            )
        return await asyncio.to_thread(
            self._retrieve_sync, query, metadata_filter or {}, task_id, k
        )

    def stats(self) -> dict[str, int]:
        if not self.available():
            return {"nodes": 0, "edges": 0, "matches": 0}
        connection = self._connect()
        try:
            return {
                "nodes": connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
                "edges": connection.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
                "matches": connection.execute(
                    "SELECT COUNT(*) FROM nodes WHERE node_type='match'"
                ).fetchone()[0],
                "communities": connection.execute(
                    "SELECT COUNT(*) FROM communities"
                ).fetchone()[0],
            }
        finally:
            connection.close()

    def maps(self) -> list[str]:
        if not self.available():
            return []
        connection = self._connect()
        try:
            return [
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT map_name FROM nodes "
                    "WHERE node_type='map' ORDER BY map_name"
                ).fetchall()
            ]
        finally:
            connection.close()

    def subgraph(self, map_name: str | None, limit_nodes: int, limit_edges: int) -> dict:
        """Return a bounded graph projection suitable for a browser canvas."""
        connection = self._connect()
        try:
            columns = "node_id,node_type,label,map_name,match_id,round_number,properties"
            maps = connection.execute(
                f"SELECT {columns} FROM nodes WHERE (? IS NULL OR map_name=?) "
                "AND node_type='map' ORDER BY node_id",
                (map_name, map_name),
            ).fetchall()
            matches = connection.execute(
                f"SELECT DISTINCT n.{columns.replace(',', ',n.')} FROM nodes n "
                "JOIN edges e ON e.source_id=n.node_id AND e.relation='HAS_MAP' "
                "JOIN nodes m ON m.node_id=e.target_id "
                "WHERE n.node_type='match' AND (? IS NULL OR m.map_name=?) ORDER BY n.node_id",
                (map_name, map_name),
            ).fetchall()
            anchors = [*matches, *maps]
            remaining = max(0, limit_nodes - len(anchors))
            round_limit = min(24, remaining // 3 or remaining)
            rounds = connection.execute(
                f"SELECT {columns} FROM nodes WHERE (? IS NULL OR map_name=?) "
                "AND node_type='round' ORDER BY match_id,round_number LIMIT ?",
                (map_name, map_name, round_limit),
            ).fetchall()
            remaining -= len(rounds)
            event_limit = max(0, remaining * 2 // 3)
            events = connection.execute(
                f"SELECT {columns} FROM nodes WHERE (? IS NULL OR map_name=?) "
                "AND node_type='event' ORDER BY match_id,round_number,node_id LIMIT ?",
                (map_name, map_name, event_limit),
            ).fetchall()
            remaining -= len(events)
            event_ids = {row["node_id"] for row in events}
            players = []
            if event_ids and remaining:
                event_placeholders = ",".join("?" for _ in event_ids)
                players = connection.execute(
                    f"SELECT DISTINCT n.{columns.replace(',', ',n.')} FROM edges e "
                    "JOIN nodes n ON n.node_id=e.target_id "
                    f"WHERE e.source_id IN ({event_placeholders}) AND n.node_type='player' "
                    "ORDER BY n.label LIMIT ?",
                    [*event_ids, remaining],
                ).fetchall()
            rows = [*anchors, *rounds, *events, *players]
            node_ids = {row["node_id"] for row in rows}
            if not node_ids:
                return {"nodes": [], "edges": []}
            placeholders = ",".join("?" for _ in node_ids)
            edge_rows = connection.execute(
                f"SELECT source_id,relation,target_id FROM edges "
                f"WHERE source_id IN ({placeholders}) AND target_id IN ({placeholders}) "
                "LIMIT ?",
                [*node_ids, *node_ids, limit_edges],
            ).fetchall()
            return {
                "nodes": [
                    {
                        "id": row["node_id"],
                        "type": row["node_type"],
                        "label": row["label"],
                        "map": row["map_name"],
                        "match_id": row["match_id"],
                        "round_number": row["round_number"],
                        "properties": json.loads(row["properties"]),
                    }
                    for row in rows
                ],
                "edges": [
                    {
                        "source": row["source_id"],
                        "relation": row["relation"],
                        "target": row["target_id"],
                    }
                    for row in edge_rows
                ],
            }
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE nodes (
                node_id TEXT PRIMARY KEY,
                node_type TEXT NOT NULL,
                label TEXT NOT NULL,
                map_name TEXT,
                match_id TEXT,
                round_number TEXT,
                properties TEXT NOT NULL
            );
            CREATE TABLE edges (
                source_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                target_id TEXT NOT NULL,
                properties TEXT NOT NULL,
                PRIMARY KEY (source_id, relation, target_id)
            );
            CREATE TABLE communities (
                community_id TEXT PRIMARY KEY,
                community_type TEXT NOT NULL,
                label TEXT NOT NULL,
                map_name TEXT,
                summary TEXT NOT NULL,
                source_ids TEXT NOT NULL,
                properties TEXT NOT NULL
            );
            CREATE INDEX nodes_map_idx ON nodes(map_name);
            CREATE INDEX nodes_type_idx ON nodes(node_type);
            CREATE INDEX nodes_round_idx ON nodes(match_id, map_name, round_number);
            CREATE INDEX edges_source_idx ON edges(source_id, relation);
            CREATE INDEX communities_map_idx ON communities(map_name);
            """
        )

    @classmethod
    def _graph_rows(cls, demo_path: Path, parsed: dict) -> tuple[list[tuple], list[tuple]]:
        match_id = _match_id(demo_path, parsed)
        map_name = _map_name(parsed.get("map_name"))
        match_node = f"match:{match_id}"
        map_node = f"map:{match_id}:{map_name}"
        nodes = [
            (match_node, "match", match_id, None, match_id, None, _json({"source_file": demo_path.name})),
            (map_node, "map", map_name, map_name, match_id, "0", _json({"source_file": demo_path.name})),
        ]
        edges = [
            (match_node, "HAS_MAP", map_node, "{}"),
        ]

        for round_data in parsed.get("rounds", []):
            number = _text(round_data.get("round_number"), "0")
            round_node = f"round:{match_id}:{map_name}:{number}"
            round_props = {
                "winner": _text(round_data.get("winner")),
                "reason": _text(round_data.get("reason")),
            }
            nodes.append((round_node, "round", f"Round {number}", map_name, match_id, number, _json(round_props)))
            edges.append((map_node, "HAS_ROUND", round_node, "{}"))
            event_groups = (
                ("kill", "KILL", round_data.get("kills", [])),
                ("grenade", "USES_UTILITY", round_data.get("grenades", [])),
                ("flash", "FLASH_BLIND", round_data.get("flash_blinds", [])),
                ("plant", "PLANTS_BOMB", round_data.get("plants", [])),
            )
            for kind, relation, events in event_groups:
                for index, event in enumerate(events):
                    event_id = f"event:{match_id}:{map_name}:{number}:{kind}:{index}"
                    props = dict(event)
                    props["kind"] = kind
                    nodes.append((event_id, "event", kind, map_name, match_id, number, _json(props)))
                    edges.append((round_node, relation, event_id, "{}"))
                    role_fields = {
                        "kill": (
                            ("KILLER", "killer", "killer_steamid"),
                            ("VICTIM", "victim", "victim_steamid"),
                            ("ASSISTER", "assister", "assister_steamid"),
                        ),
                        "grenade": (("THROWER", "thrower", "thrower_steamid"),),
                        "flash": (
                            ("FLASHER", "attacker", "attacker_steamid"),
                            ("BLINDED", "victim", "victim_steamid"),
                        ),
                        "plant": (("PLANTER", "planter", "planter_steamid"),),
                    }[kind]
                    for role, name_key, steamid_key in role_fields:
                        identity = _player_identity(event, name_key, steamid_key)
                        if identity:
                            player_id, player_name, steamid = identity
                            nodes.append((
                                player_id,
                                "player",
                                player_name,
                                None,
                                None,
                                None,
                                _json({"name": player_name, "steamid": steamid}),
                            ))
                            edges.append((event_id, role, player_id, "{}"))
        return list({row[0]: row for row in nodes}.values()), list({(row[0], row[1], row[2]): row for row in edges}.values())

    def _retrieve_sync(self, query: str, metadata: dict, task_id: str | None, k: int) -> list[Evidence]:
        map_name = _map_name(metadata["map"]) if metadata.get("map") else None
        terms = set(re.findall(r"[a-z0-9_]+", query.lower()))
        topic = self._topic(task_id, terms, query)
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM nodes WHERE node_type='round' "
                "AND (? IS NULL OR map_name=?) ORDER BY match_id, round_number",
                (map_name, map_name),
            ).fetchall()
            scored = []
            for row in rows:
                props = json.loads(row["properties"])
                event_rows = connection.execute(
                    "SELECT n.* FROM edges e JOIN nodes n ON n.node_id=e.target_id "
                    "WHERE e.source_id=? ORDER BY CAST(json_extract(n.properties, '$.tick') AS INTEGER)",
                    (row["node_id"],),
                ).fetchall()
                events = [(item["label"], json.loads(item["properties"])) for item in event_rows]
                score = self._round_score(events, props, topic, terms)
                if score > 0:
                    scored.append((score, row, props, events))
            scored.sort(key=lambda item: item[0], reverse=True)
            return [self._evidence(item, topic) for item in scored[:k]]
        finally:
            connection.close()

    def _build_communities(self, connection: sqlite3.Connection) -> int:
        """Create extractive map-topic summaries with round-level provenance."""
        map_names = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT map_name FROM nodes WHERE node_type='map' ORDER BY map_name"
            ).fetchall()
        ]
        communities = []
        for map_name in map_names:
            round_rows = connection.execute(
                "SELECT * FROM nodes WHERE node_type='round' AND map_name=?",
                (map_name,),
            ).fetchall()
            if not round_rows:
                continue
            round_data = []
            for round_row in round_rows:
                events = connection.execute(
                    "SELECT n.* FROM edges e JOIN nodes n ON n.node_id=e.target_id "
                    "WHERE e.source_id=?",
                    (round_row["node_id"],),
                ).fetchall()
                round_data.append((round_row, [json.loads(event["properties"]) for event in events]))
            for topic in ("overview", "opening", "utility", "round_flow"):
                summary, source_ids, properties = self._community_summary(map_name, topic, round_data)
                community_id = f"community:{map_name}:{topic}"
                communities.append(
                    (
                        community_id,
                        "map_topic",
                        f"{map_name} {topic}",
                        map_name,
                        summary,
                        _json(source_ids),
                        _json(properties),
                    )
                )
        connection.executemany(
            "INSERT INTO communities "
            "(community_id,community_type,label,map_name,summary,source_ids,properties) "
            "VALUES (?,?,?,?,?,?,?)",
            communities,
        )
        return len(communities)

    @staticmethod
    def _community_summary(map_name: str, topic: str, round_data: list[tuple]) -> tuple[str, list[str], dict]:
        selected = []
        for round_row, events in round_data:
            kinds = Counter(event.get("kind") for event in events)
            if topic == "opening" and not any(event.get("is_first_kill") for event in events):
                continue
            if topic == "utility" and not (kinds["grenade"] or kinds["flash"]):
                continue
            if topic == "round_flow" and not (kinds["kill"] or kinds["plant"]):
                continue
            selected.append((round_row, events))
        selected = selected or round_data
        source_ids = [row["node_id"] for row, _ in selected]
        matches = {row["match_id"] for row, _ in selected}
        kills = [event for _, events in selected for event in events if event.get("kind") == "kill"]
        grenades = [event for _, events in selected for event in events if event.get("kind") == "grenade"]
        flashes = [event for _, events in selected for event in events if event.get("kind") == "flash"]
        plants = [event for _, events in selected for event in events if event.get("kind") == "plant"]
        first_kills = [event for event in kills if event.get("is_first_kill")]
        opening_players = Counter(
            event.get("killer", "Unknown")
            for event in first_kills
        )
        opening_deaths = Counter(event.get("victim", "Unknown") for event in first_kills)
        opening_weapons = Counter(event.get("weapon", "Unknown") for event in first_kills)
        utility_types = Counter(event.get("type", "Unknown") for event in grenades)
        utility_throwers = Counter(event.get("thrower", "Unknown") for event in grenades)
        winners = Counter(row["properties"] and json.loads(row["properties"]).get("winner", "Unknown") for row, _ in selected)
        end_reasons = Counter(row["properties"] and json.loads(row["properties"]).get("reason", "Unknown") for row, _ in selected)
        properties = {
            "topic": topic,
            "rounds": len(selected),
            "matches": len(matches),
            "kills": len(kills),
            "first_kills": len(first_kills),
            "grenades": len(grenades),
            "flashes": len(flashes),
            "plants": len(plants),
        }
        winner_text = ", ".join(f"{name} {count}" for name, count in winners.most_common(4)) or "none"
        player_text = ", ".join(f"{name} {count}" for name, count in opening_players.most_common(5)) or "none"
        death_text = ", ".join(f"{name} {count}" for name, count in opening_deaths.most_common(5)) or "none"
        weapon_text = ", ".join(f"{name} {count}" for name, count in opening_weapons.most_common(5)) or "none"
        utility_text = ", ".join(f"{name} {count}" for name, count in utility_types.most_common(5)) or "none"
        thrower_text = ", ".join(f"{name} {count}" for name, count in utility_throwers.most_common(5)) or "none"
        reason_text = ", ".join(f"{name} {count}" for name, count in end_reasons.most_common(5)) or "none"
        prefix = (
            f"[Community Summary | {map_name} | {topic}] Based on {len(matches)} matches and "
            f"{len(selected)} parsed rounds. "
        )
        if topic == "opening":
            body = (
                f"Opening duels: {len(first_kills)}. First-kill players: {player_text}. "
                f"First-death players: {death_text}. Opening weapons: {weapon_text}."
            )
        elif topic == "utility":
            body = (
                f"Utility usage: {len(grenades)} detonations and {len(flashes)} recorded blind events. "
                f"Types: {utility_text}. Throwers: {thrower_text}."
            )
        elif topic == "round_flow":
            body = (
                f"Round flow: {len(kills)} kills and {len(plants)} bomb plants. "
                f"Round winners: {winner_text}. End reasons: {reason_text}."
            )
        else:
            body = (
                f"Overview: {len(kills)} kills, {properties['first_kills']} first kills, "
                f"{len(grenades)} utility detonations, {len(flashes)} recorded blind events, "
                f"and {len(plants)} bomb plants. Round winners: {winner_text}."
            )
        summary = prefix + body + " This is an extractive factual summary; it does not establish tactical causality."
        return summary, source_ids, properties

    def _global_search_sync(self, query: str, metadata: dict, k: int) -> list[Evidence]:
        map_name = _map_name(metadata["map"]) if metadata.get("map") else None
        terms = set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", query.lower()))
        topic = self._topic(None, terms, query)
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM communities WHERE (? IS NULL OR map_name=?)",
                (map_name, map_name),
            ).fetchall()
            ranked = []
            for row in rows:
                text = f"{row['label']} {row['summary']}".lower()
                overlap = sum(1 for term in terms if term in text)
                row_topic = json.loads(row["properties"]).get("topic")
                topic_match = bool(topic and row_topic == topic)
                if topic and not topic_match:
                    continue
                if not topic and overlap == 0:
                    continue
                topic_bonus = 0.25 if topic_match else 0
                score = min(1.0, overlap * 0.08 + topic_bonus)
                ranked.append((score, row))
            ranked.sort(key=lambda item: item[0], reverse=True)
            return [self._community_evidence(score, row) for score, row in ranked[:k]]
        finally:
            connection.close()

    @staticmethod
    def _community_evidence(score: float, row: sqlite3.Row) -> Evidence:
        source_ids = json.loads(row["source_ids"])
        topic = json.loads(row["properties"]).get("topic", "overview")
        source = f"community:{row['community_id']}"
        content = (
            f"{row['summary']} Graph source paths: "
            + ", ".join(source_ids[:12])
            + (" ..." if len(source_ids) > 12 else "")
        )
        return Evidence(
            content=content,
            metadata={
                "map": row["map_name"],
                "side": "Both",
                "tactic_type": "Graph Community Summary",
                "source": source,
                "community_id": row["community_id"],
                "topic": topic,
                "context_level": "community_summary",
                "source_round_count": len(source_ids),
            },
            score=float(score),
            source_id=source,
        )

    @staticmethod
    def _topic(task_id: str | None, terms: set[str], query: str = "") -> str | None:
        task_topics = {
            "opening_duel": "opening",
            "utility": "utility",
            "round_flow": "round_flow",
            "map_context": "overview",
        }
        if task_id in task_topics:
            return task_topics[task_id]
        query = query.lower()
        if any(value in query for value in ("首杀", "首死", "开局", "对枪", "补枪")):
            return "opening"
        if any(value in query for value in ("道具", "烟雾", "闪光", "燃烧弹", "手雷", "投掷物")):
            return "utility"
        if any(value in query for value in ("回合", "下包", "拆包", "回防", "残局", "击杀链")):
            return "round_flow"
        if any(value in query for value in ("地图", "比赛", "职业", "概览", "总体", "战术")):
            return "overview"
        if terms & {"opening", "first", "duel", "trade"}:
            return "opening"
        if terms & {"utility", "smoke", "flash", "grenade", "molotov", "execute"}:
            return "utility"
        if terms & {"round", "plant", "retake", "kill", "bomb"}:
            return "round_flow"
        if terms & {"map", "match", "professional", "overview", "context", "control", "tactical"}:
            return "overview"
        return None

    @staticmethod
    def _round_score(events: list[tuple[str, dict]], props: dict, topic: str | None, terms: set[str]) -> float:
        kinds = Counter(kind for kind, _ in events)
        score = 0.0
        if topic == "opening":
            score += 1.0 if any(event.get("is_first_kill") for kind, event in events if kind == "kill") else 0
        elif topic == "utility":
            score += min(1.0, (kinds["grenade"] + kinds["flash"]) / 4)
        elif topic == "round_flow":
            score += min(1.0, (kinds["kill"] + kinds["plant"]) / 6)
        elif topic == "overview":
            score += min(1.0, len(events) / 8)
        text = " ".join([props.get("winner", ""), props.get("reason", "")] + [kind for kind, _ in events]).lower()
        score += min(0.5, sum(1 for term in terms if term in text) * 0.05)
        return min(1.0, score)

    @staticmethod
    def _evidence(item: tuple, topic: str | None) -> Evidence:
        score, row, props, events = item
        lines = [
            f"[Graph path] Match {row['match_id']} -> {row['map_name']} -> Round {row['round_number']}",
            f"Round winner: {_text(props.get('winner'))}; end reason: {_text(props.get('reason'))}.",
        ]
        for kind, event in events:
            if kind == "kill":
                first = " [first kill]" if event.get("is_first_kill") else ""
                lines.append(f"tick {event.get('tick', '?')}: {event.get('killer', 'Unknown')} killed {event.get('victim', 'Unknown')} with {event.get('weapon', 'Unknown')}{first}.")
            elif kind == "grenade":
                lines.append(f"tick {event.get('tick', '?')}: {event.get('thrower', 'Unknown')} used {event.get('type', 'utility')}.")
            elif kind == "flash":
                lines.append(f"tick {event.get('tick', '?')}: {event.get('attacker', 'Unknown')} blinded {event.get('victim', 'Unknown')}.")
            elif kind == "plant":
                lines.append(f"tick {event.get('tick', '?')}: {event.get('planter', 'Unknown')} planted at {event.get('site', 'Unknown')}.")
        source = f"graph:{row['match_id']}:{row['map_name']}:{row['round_number']}"
        return Evidence(
            content=" ".join(lines),
            metadata={
                "map": row["map_name"],
                "side": "Both",
                "tactic_type": f"Graph {(topic or 'general').title()} Evidence",
                "source": source,
                "match_id": row["match_id"],
                "round_number": row["round_number"],
                "topic": topic or "general",
                "context_level": "graph_path",
            },
            score=float(score),
            source_id=source,
        )
