"""Deterministic, local GraphRAG sidecar for parsed CS2 demo evidence.

The graph is deliberately factual: it stores parser output and relationships,
but never asks an LLM to invent nodes or edges.
"""
import asyncio
import json
import logging
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.services.rag_service import Evidence
from app.services.tactical_annotation_service import annotate_match

logger = logging.getLogger(__name__)

MAP_NAMES = {
    "de_ancient": "Ancient",
    "de_anubis": "Anubis",
    "de_cache": "Cache",
    "de_dust2": "Dust2",
    "de_inferno": "Inferno",
    "de_mirage": "Mirage",
    "de_nuke": "Nuke",
    "de_overpass": "Overpass",
    "de_vertigo": "Vertigo",
}
TEAM_ALIASES = {
    "猎鹰": "falcons",
    "绿龙": "spirit",
    "蜜蜂": "vitality",
    "黑豹": "furia",
    "老鼠": "mouz",
}
TACTICAL_LABELS = (
    "OPENING_DUEL",
    "TRADE_KILL",
    "UTILITY_BURST",
    "EXECUTE_CANDIDATE",
    "POST_PLANT",
    "RETAKE_CONTACT",
)
TEAM_DISPLAY_NAMES = {
    "falcons": "Falcons",
    "spirit": "Spirit",
    "vitality": "Vitality",
    "furia": "FURIA",
    "mouz": "MOUZ",
}
COACH_METRICS = {
    "opening_won": ("首杀优势回合", "复盘首杀后的站位收缩、第二接触和交叉火力，避免人数优势被连续单挑消耗。"),
    "opening_lost_recovery": ("首杀劣势回合", "训练首杀失利后 5 秒内的止损：撤点、补闪和双人再接触。"),
    "trade_round": ("补枪回合", "检查首接触队员与补枪位的距离、枪线和同步时机。"),
    "utility_burst_round": ("道具爆发回合", "核对最后一颗关键道具落地到第一接触之间的时间差。"),
    "execute_candidate": ("爆弹候选回合", "逐回合复盘爆弹后的首个清点顺序与下包前区域控制。"),
    "post_plant": ("下包后回合", "固定下包后的交叉站位、信息优先级和延时道具分工。"),
    "retake_contact": ("回防接触回合", "训练回防集合点、第一颗闪光和双人同步接触。"),
}
TACTICAL_LABEL_NAMES = {
    "OPENING_DUEL": "首杀对局",
    "TRADE_KILL": "补枪",
    "UTILITY_BURST": "道具爆发",
    "EXECUTE_CANDIDATE": "爆弹候选",
    "POST_PLANT": "下包后",
    "RETAKE_CONTACT": "回防接触",
}


def _query_text(query: str) -> str:
    return query.lower() + " " + " ".join(
        name for alias, name in TEAM_ALIASES.items() if alias in query
    )


def _text(value: Any, fallback: str = "Unknown") -> str:
    if value is None or str(value) in {"", "None", "nan"}:
        return fallback
    return str(value)


def _map_name(value: str) -> str:
    raw = _text(value)
    return MAP_NAMES.get(raw.lower(), raw.removeprefix("de_").title())


def _team_key(value: Any) -> str:
    raw = _text(value, "").strip().lower()
    for alias, expanded in TEAM_ALIASES.items():
        if alias in raw:
            raw = expanded
            break
    return re.sub(r"[^a-z0-9]+", "", raw.removeprefix("team "))


def _team_name(value: Any) -> str:
    raw = _text(value, "").strip()
    key = _team_key(raw)
    if not key:
        return "Unknown"
    return TEAM_DISPLAY_NAMES.get(key, raw.removeprefix("Team ").strip() or key.title())


def _side_name(value: Any) -> str | None:
    return {
        "T": "T",
        "TERRORIST": "T",
        "CT": "CT",
        "COUNTERTERRORIST": "CT",
    }.get(_text(value, "").upper())


def _pct(numerator: int, denominator: int) -> float | None:
    return round(100 * numerator / denominator, 2) if denominator else None


def _pct_text(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.2f}%"


def _zh_pct(value: float | None) -> str:
    return "暂无" if value is None else f"{value:.1f}%"


def _requested_metric(query: str) -> str | None:
    lowered = query.lower()
    keywords = (
        ("opening_lost_recovery", ("首死", "丢首杀", "opening loss", "opening lost")),
        ("trade_round", ("补枪", "trade")),
        ("utility_burst_round", ("道具", "utility")),
        ("execute_candidate", ("爆弹", "execute")),
        ("post_plant", ("下包", "post plant", "post-plant")),
        ("retake_contact", ("回防", "retake")),
        ("opening_won", ("首杀", "opening", "first kill")),
    )
    return next((key for key, terms in keywords if any(term in lowered for term in terms)), None)


def _event_tick(properties: dict) -> int | None:
    value = properties.get("tick", properties.get("start_tick"))
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _round_event_label(properties: dict) -> str:
    kind = properties.get("kind")
    if kind == "kill":
        flags = []
        if properties.get("is_first_kill"):
            flags.append("首杀")
        if properties.get("is_headshot"):
            flags.append("爆头")
        suffix = f" · {' / '.join(flags)}" if flags else ""
        return (
            f"{properties.get('killer', 'Unknown')} 击杀 {properties.get('victim', 'Unknown')}"
            f" · {properties.get('weapon', 'Unknown')}{suffix}"
        )
    if kind == "grenade":
        area = properties.get("thrower_area")
        return f"{properties.get('thrower', 'Unknown')} 投掷 {properties.get('type', '道具')}" + (f" · {area}" if area else "")
    if kind == "flash":
        return f"{properties.get('attacker', 'Unknown')} 闪白 {properties.get('victim', 'Unknown')}"
    if kind == "plant":
        site = str(properties.get("site", "Unknown")).removeprefix("Bombsite")
        return f"{properties.get('planter', 'Unknown')} 在 {site} 点下包"
    label_type = properties.get("label_type", "Unknown")
    label = TACTICAL_LABEL_NAMES.get(label_type, label_type)
    team = _team_name(properties.get("team"))
    site = f" · {properties.get('site')} 点" if properties.get("site") else ""
    return f"{label} · {team}{site} · 置信度 {float(properties.get('confidence', 0)):.2f}"


def _query_map_name(query: str) -> str | None:
    lowered = query.lower()
    return next(
        (name for name in sorted(set(MAP_NAMES.values())) if name.lower() in lowered),
        None,
    )


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
                "tactical_sequences": connection.execute(
                    "SELECT COUNT(*) FROM nodes WHERE node_type='tactical_sequence'"
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

    def players(self, team: str | None = None, limit: int = 100) -> list[dict]:
        """Return cross-match player summaries derived from graph facts."""
        if not self.available():
            return []
        profiles, _ = self._analytics_snapshot()
        requested_team = _team_key(team) if team else ""
        selected = [
            profile for profile in profiles.values()
            if not requested_team
            or any(_team_key(item["team"]) == requested_team for item in profile["teams"])
        ]
        selected.sort(
            key=lambda item: (
                -item["sample_size"]["matches"],
                -item["sample_size"]["rounds"],
                -item["combat"]["kills"],
                item["name"].lower(),
            )
        )
        summary_keys = (
            "player_id", "graph_id", "name", "team", "teams", "sample_size",
            "combat", "utility", "tactical_participation", "rates_per_100_rounds",
        )
        return [
            {key: profile[key] for key in summary_keys}
            for profile in selected[:limit]
        ]

    def player_profile(self, player_id: str) -> dict | None:
        """Return one traceable player profile by SteamID, graph id, or exact nickname."""
        if not self.available():
            return None
        profiles, _ = self._analytics_snapshot()
        graph_id = player_id if player_id.startswith("player:") else f"player:{player_id}"
        if graph_id in profiles:
            return profiles[graph_id]
        lowered = player_id.lower()
        return next(
            (profile for profile in profiles.values() if profile["name"].lower() == lowered),
            None,
        )

    def compare_teams(self, team_names: list[str]) -> dict:
        """Compare tactical label frequencies using team-round denominators."""
        if not self.available():
            return {"teams": [], "available_teams": []}
        _, team_profiles = self._analytics_snapshot()
        by_key = {_team_key(profile["team"]): profile for profile in team_profiles.values()}
        requested = []
        seen = set()
        for name in team_names:
            key = _team_key(name)
            if key and key not in seen:
                seen.add(key)
                profile = by_key.get(key)
                if profile:
                    requested.append(profile)
        return {
            "teams": requested,
            "available_teams": sorted(profile["team"] for profile in team_profiles.values()),
            "methodology": {
                "version": "graph-analytics-v1",
                "denominator": "parsed team-round appearances",
                "labels": "deterministic silver labels; EXECUTE_CANDIDATE is weakly supervised",
                "causality": "descriptive counts only; no causal claim",
            },
        }

    def team_tactics(
        self,
        team: str,
        *,
        map_name: str | None = None,
        side: str | None = None,
        opponent: str | None = None,
    ) -> dict | None:
        """Return contextual tactical outcomes for one team."""
        if not self.available():
            return None
        target_key = _team_key(team)
        requested_map = _map_name(map_name) if map_name else None
        requested_side = _side_name(side) if side else None
        opponent_key = _team_key(opponent) if opponent else ""
        connection = self._connect()
        try:
            player_names = {
                row["node_id"].removeprefix("player:"): row["label"]
                for row in connection.execute(
                    "SELECT node_id,label FROM nodes WHERE node_type='player'"
                )
            }
            contexts = {}
            for row in connection.execute(
                "SELECT match_id,map_name,round_number,properties "
                "FROM nodes WHERE node_type='round'"
            ):
                key = (row["match_id"], row["map_name"], row["round_number"])
                contexts[key] = {
                    "winner": json.loads(row["properties"]).get("winner"),
                    "teams": set(),
                    "team_names": Counter(),
                    "team_sides": defaultdict(Counter),
                    "labels": [],
                }

            team_side_fields = (
                ("killer_team", "killer_side"),
                ("victim_team", "victim_side"),
                ("assister_team", "assister_side"),
                ("thrower_team", "thrower_side"),
                ("attacker_team", "attacker_side"),
                ("planter_team", "planter_side"),
            )
            for row in connection.execute(
                "SELECT match_id,map_name,round_number,properties "
                "FROM nodes WHERE node_type='event'"
            ):
                key = (row["match_id"], row["map_name"], row["round_number"])
                context = contexts.get(key)
                if not context:
                    continue
                props = json.loads(row["properties"])
                for team_field, side_field in team_side_fields:
                    name = _team_name(props.get(team_field))
                    normalized = _team_key(name)
                    if not normalized or name == "Unknown":
                        continue
                    context["teams"].add(normalized)
                    context["team_names"][name] += 1
                    event_side = _side_name(props.get(side_field))
                    if event_side:
                        context["team_sides"][normalized][event_side] += 1

            for row in connection.execute(
                "SELECT match_id,map_name,round_number,properties "
                "FROM nodes WHERE node_type='tactical_sequence'"
            ):
                key = (row["match_id"], row["map_name"], row["round_number"])
                if key in contexts:
                    contexts[key]["labels"].append(json.loads(row["properties"]))

            target_contexts = []
            target_display = TEAM_DISPLAY_NAMES.get(target_key, _team_name(team))
            for key, context in contexts.items():
                if target_key not in context["teams"]:
                    continue
                side_counts = context["team_sides"].get(target_key)
                round_side = side_counts.most_common(1)[0][0] if side_counts else None
                opponents = {
                    _team_key(name): name
                    for name in context["team_names"]
                    if _team_key(name) not in {target_key, "unknown"}
                }
                target_contexts.append((key, context, round_side, opponents))
            if not target_contexts:
                return None

            available_maps = sorted({key[1] for key, *_ in target_contexts})
            available_opponents = sorted({
                name
                for _, _, _, opponents in target_contexts
                for name in opponents.values()
            })
            selected = [
                item for item in target_contexts
                if (not requested_map or item[0][1] == requested_map)
                and (not requested_side or item[2] == requested_side)
                and (not opponent_key or opponent_key in item[3])
            ]

            matches = {key[0] for key, *_ in selected}
            maps = {(key[0], key[1]) for key, *_ in selected}
            decided = {}
            labels = Counter()
            label_rounds = defaultdict(set)
            opening_lost_rounds = set()
            sites = defaultdict(lambda: {
                "rounds": set(), "post_plants": set(), "executes": set(), "retakes": set(),
            })
            opponent_stats = defaultdict(lambda: {
                "name": "Unknown", "rounds": set(), "decided": set(),
                "won": set(), "labels": Counter(),
            })
            opening_players = Counter()
            trade_players = Counter()
            utility_players = Counter()
            sources = set()

            for key, context, round_side, opponents in selected:
                winner_side = _side_name(context["winner"])
                won = round_side == winner_side if winner_side else None
                decided[key] = won
                sources.add(f"graph:{key[0]}:{key[1]}:{key[2]}")
                target_labels = [
                    label for label in context["labels"]
                    if _team_key(label.get("team")) == target_key
                ]
                opposing_opening = any(
                    label.get("label_type") == "OPENING_DUEL"
                    and _team_key(label.get("team")) not in {target_key, "", "unknown"}
                    for label in context["labels"]
                )
                if opposing_opening:
                    opening_lost_rounds.add(key)
                for label in target_labels:
                    label_type = label.get("label_type", "Unknown")
                    labels[label_type] += 1
                    label_rounds[label_type].add(key)
                    site = label.get("site")
                    if site:
                        sites[site]["rounds"].add(key)
                        if label_type == "POST_PLANT":
                            sites[site]["post_plants"].add(key)
                        elif label_type == "EXECUTE_CANDIDATE":
                            sites[site]["executes"].add(key)
                        elif label_type == "RETAKE_CONTACT":
                            sites[site]["retakes"].add(key)
                    details = label.get("details") or {}
                    if label_type == "OPENING_DUEL" and details.get("winner_steamid"):
                        opening_players[str(details["winner_steamid"])] += 1
                    elif label_type == "TRADE_KILL" and details.get("trader_steamid"):
                        trade_players[str(details["trader_steamid"])] += 1
                    elif label_type == "UTILITY_BURST":
                        utility_players.update(str(item) for item in label.get("participant_ids", []))
                for other_key, other_name in opponents.items():
                    bucket = opponent_stats[other_key]
                    bucket["name"] = other_name
                    bucket["rounds"].add(key)
                    if won is not None:
                        bucket["decided"].add(key)
                    if won:
                        bucket["won"].add(key)
                    bucket["labels"].update(label.get("label_type") for label in target_labels)

            won_rounds = {key for key, won in decided.items() if won}
            decided_rounds = {key for key, won in decided.items() if won is not None}

            def conversion(round_keys: set) -> dict:
                known = round_keys & decided_rounds
                won = len(known & won_rounds)
                return {
                    "opportunities": len(round_keys),
                    "decided": len(known),
                    "rounds_won": won,
                    "round_win_pct": _pct(won, len(known)),
                }

            def leaders(counter: Counter) -> list[dict]:
                total = sum(counter.values())
                return [
                    {
                        "player_id": player_id,
                        "name": player_names.get(player_id, player_id),
                        "count": count,
                        "share_pct": _pct(count, total),
                    }
                    for player_id, count in counter.most_common(5)
                ]

            rounds = len(selected)
            return {
                "team": target_display,
                "filters": {
                    "map": requested_map,
                    "side": requested_side,
                    "opponent": _team_name(opponent) if opponent else None,
                },
                "available_filters": {
                    "maps": available_maps,
                    "sides": ["T", "CT"],
                    "opponents": available_opponents,
                },
                "sample_size": {
                    "matches": len(matches),
                    "maps": len(maps),
                    "rounds": rounds,
                    "decided_rounds": len(decided_rounds),
                },
                "outcomes": {
                    "rounds_won": len(won_rounds),
                    "round_win_pct": _pct(len(won_rounds), len(decided_rounds)),
                },
                "labels": {
                    label: {
                        "count": labels[label],
                        "per_100_rounds": _pct(labels[label], rounds) or 0.0,
                    }
                    for label in TACTICAL_LABELS
                },
                "conversions": {
                    "opening_won": conversion(label_rounds["OPENING_DUEL"]),
                    "opening_lost_recovery": conversion(opening_lost_rounds),
                    "trade_round": conversion(label_rounds["TRADE_KILL"]),
                    "utility_burst_round": conversion(label_rounds["UTILITY_BURST"]),
                    "execute_candidate": conversion(label_rounds["EXECUTE_CANDIDATE"]),
                    "post_plant": conversion(label_rounds["POST_PLANT"]),
                    "retake_contact": conversion(label_rounds["RETAKE_CONTACT"]),
                },
                "role_leaders": {
                    "opening_kills": leaders(opening_players),
                    "trade_kills": leaders(trade_players),
                    "utility_burst_participation": leaders(utility_players),
                },
                "site_breakdown": [
                    {
                        "site": site,
                        "rounds": len(values["rounds"]),
                        "round_win_pct": conversion(values["rounds"])["round_win_pct"],
                        "post_plants": len(values["post_plants"]),
                        "execute_candidates": len(values["executes"]),
                        "retake_contacts": len(values["retakes"]),
                    }
                    for site, values in sorted(sites.items())
                ],
                "opponent_breakdown": [
                    {
                        "opponent": values["name"],
                        "rounds": len(values["rounds"]),
                        "decided_rounds": len(values["decided"]),
                        "round_win_pct": _pct(len(values["won"]), len(values["decided"])),
                        "labels": dict(values["labels"]),
                    }
                    for values in sorted(opponent_stats.values(), key=lambda item: item["name"])
                ],
                "source_round_ids": sorted(sources)[:12],
                "methodology": {
                    "version": "graph-tactics-v1",
                    "winner": "round winner side matched to the team's observed side",
                    "retake": "contact label plus round outcome; not proof of a coordinated retake",
                    "execute": "weak-rule candidate plus round outcome; not tactical-intent ground truth",
                },
            }
        finally:
            connection.close()

    def coach_brief(self, query: str, evidence: list[Evidence]) -> dict | None:
        """Turn structured tactical evidence into a cited Chinese coaching brief."""
        tactical = next(
            (item for item in evidence if item.metadata.get("context_level", "").startswith("team_tactical_")),
            None,
        )
        if not tactical:
            return None
        metadata = tactical.metadata
        source_ids = metadata.get("source_round_ids", [])[:6]
        sources = [
            {"id": f"G{index}", "round_id": source_id}
            for index, source_id in enumerate(source_ids, start=1)
        ]
        source_note = "；可复核回合样本见 " + "、".join(f"[{item['id']}]" for item in sources) if sources else ""
        map_name = metadata.get("map", "All")
        side = metadata.get("side", "Both")
        context = f"{map_name if map_name != 'All' else '全部地图'} · {side if side != 'Both' else '双阵营'}"
        caveat = "结论来自确定性事件与 silver labels，只描述当前样本相关性，不代表战术意图或因果关系。"

        if metadata["context_level"] == "team_tactical_comparison":
            profiles = metadata.get("profiles", [])
            if len(profiles) < 2:
                return None
            focus_key = _requested_metric(query)
            label = COACH_METRICS[focus_key][0] if focus_key else "整体回合"
            values = []
            for profile in profiles[:2]:
                metric = profile.get("conversions", {}).get(focus_key, {}) if focus_key else {}
                values.append({
                    "team": profile["team"],
                    "rounds": profile.get("sample_size", {}).get("rounds", 0),
                    "opportunities": metric.get("opportunities") if focus_key else profile.get("sample_size", {}).get("decided_rounds", 0),
                    "win_pct": metric.get("round_win_pct") if focus_key else profile.get("outcomes", {}).get("round_win_pct"),
                })
            difference = None
            if all(item["win_pct"] is not None for item in values):
                difference = round(values[0]["win_pct"] - values[1]["win_pct"], 1)
            findings = [
                f"{item['team']}：{item['rounds']} 回合样本，{label}胜率 {_zh_pct(item['win_pct'])}"
                + (f"（{item['opportunities']} 次机会）" if item["opportunities"] is not None else "")
                for item in values
            ]
            if difference is not None:
                findings.append(f"按 {values[0]['team']} − {values[1]['team']} 计算，差值为 {difference:+.1f} 个百分点{source_note}。")
            action = COACH_METRICS[focus_key][1] if focus_key else "把差距继续拆到相同地图、阵营与对手，避免用不同样本结构直接判断战术强弱。"
            return {
                "kind": "comparison",
                "title": f"{values[0]['team']} vs {values[1]['team']} · {context}",
                "summary": f"当前对比聚焦{label}；两队样本量不同，先看方向，再下钻到同条件回合。",
                "focus_metric": {"key": focus_key or "round_win", "label": label, "teams": values, "difference_pct_points": difference},
                "findings": findings,
                "actions": [action],
                "sample_confidence": "中" if min(item["rounds"] for item in values) >= 30 else "低",
                "caveat": caveat,
                "sources": sources,
                "methodology": "deterministic-coach-brief-v1",
            }

        sample = metadata.get("sample_size", {})
        team = metadata.get("team", "Unknown")
        opponent = metadata.get("opponent")
        rounds = sample.get("rounds", 0)
        conversion_rows = [
            {
                "key": key,
                "label": COACH_METRICS[key][0],
                "opportunities": value.get("opportunities", 0),
                "win_pct": value.get("round_win_pct"),
            }
            for key, value in metadata.get("conversions", {}).items()
            if key in COACH_METRICS and value.get("opportunities", 0) > 0 and value.get("round_win_pct") is not None
        ]
        focus_key = _requested_metric(query)
        focus = next((row for row in conversion_rows if row["key"] == focus_key), None)
        ranked = sorted(conversion_rows, key=lambda row: row["win_pct"])
        findings = [f"{sample.get('matches', 0)} 场、{sample.get('maps', 0)} 张地图、{rounds} 回合；整体回合胜率 {_zh_pct(metadata.get('outcomes', {}).get('round_win_pct'))}。"]
        if focus:
            findings.append(f"查询指标：{focus['label']} {focus['opportunities']} 次机会，回合胜率 {_zh_pct(focus['win_pct'])}{source_note}。")
        if ranked:
            weakest, strongest = ranked[0], ranked[-1]
            if not focus or weakest["key"] != focus["key"]:
                findings.append(f"当前最低转化：{weakest['label']} {_zh_pct(weakest['win_pct'])}（{weakest['opportunities']} 次机会）。")
            if strongest["key"] != weakest["key"] and (not focus or strongest["key"] != focus["key"]):
                findings.append(f"当前最高转化：{strongest['label']} {_zh_pct(strongest['win_pct'])}（{strongest['opportunities']} 次机会）。")
        priority = focus_key if focus else (ranked[0] if ranked else {}).get("key")
        actions = [COACH_METRICS[priority][1]] if priority else ["当前切片没有足够的战术事件，先扩大地图、阵营或对手范围。"]
        if rounds < 30:
            actions.append("样本少于 30 回合，先补充相同条件 Demo，再把百分比用于训练决策。")
        return {
            "kind": "team_profile",
            "title": f"{team}{f' vs {opponent}' if opponent else ''} · {context}",
            "summary": "先按查询指标定位回合，再用最低转化项安排复盘；百分比不脱离机会次数解读。",
            "focus_metric": focus,
            "findings": findings,
            "actions": actions,
            "sample_confidence": "高" if rounds >= 100 else "中" if rounds >= 30 else "低",
            "caveat": caveat,
            "sources": sources,
            "methodology": "deterministic-coach-brief-v1",
        }

    def round_detail(self, source_id: str) -> dict | None:
        """Return one cited round as a chronological event and tactical-label timeline."""
        match = re.fullmatch(r"(?:graph|round):([^:]+):([^:]+):(\d+)", source_id)
        if not match or not self.available():
            return None
        match_id, map_name, round_number = match.groups()
        connection = self._connect()
        try:
            round_row = connection.execute(
                "SELECT properties FROM nodes WHERE node_id=? AND node_type='round'",
                (f"round:{match_id}:{map_name}:{round_number}",),
            ).fetchone()
            if not round_row:
                return None
            rows = connection.execute(
                "SELECT node_id,node_type,properties FROM nodes "
                "WHERE match_id=? AND map_name=? AND round_number=? "
                "AND node_type IN ('event','tactical_sequence')",
                (match_id, map_name, round_number),
            ).fetchall()
            timeline = []
            counts = Counter()
            teams = set()
            for row in rows:
                properties = json.loads(row["properties"])
                kind = properties.get("kind", row["node_type"])
                counts[kind] += 1
                for field in ("team", "killer_team", "victim_team", "thrower_team", "attacker_team", "planter_team"):
                    if properties.get(field):
                        teams.add(_team_name(properties[field]))
                timeline.append({
                    "id": row["node_id"],
                    "tick": _event_tick(properties),
                    "kind": kind,
                    "label": _round_event_label(properties),
                    "team": _team_name(properties.get("team")) if properties.get("team") else None,
                    "site": properties.get("site"),
                    "label_source": properties.get("label_source"),
                    "confidence": properties.get("confidence"),
                })
            timeline.sort(key=lambda item: (item["tick"] is None, item["tick"] or 0, item["kind"] == "tactical_sequence"))
            outcome = json.loads(round_row["properties"])
            return {
                "source_id": f"graph:{match_id}:{map_name}:{round_number}",
                "match_id": match_id,
                "map": map_name,
                "round_number": int(round_number),
                "winner": outcome.get("winner"),
                "reason": outcome.get("reason"),
                "teams": sorted(team for team in teams if team != "Unknown"),
                "counts": dict(counts),
                "timeline": timeline,
                "methodology": "parsed-events-plus-silver-labels-v1",
            }
        finally:
            connection.close()

    def _analytics_snapshot(self) -> tuple[dict[str, dict], dict[str, dict]]:
        """Aggregate event and tactical nodes without adding a second datastore."""
        connection = self._connect()
        try:
            player_rows = connection.execute(
                "SELECT node_id,label,properties FROM nodes WHERE node_type='player'"
            ).fetchall()
            players = {}
            for row in player_rows:
                props = json.loads(row["properties"])
                players[row["node_id"]] = {
                    "graph_id": row["node_id"],
                    "player_id": props.get("steamid") or row["node_id"].removeprefix("player:"),
                    "name": props.get("name") or row["label"],
                    "team_events": Counter(),
                    "team_maps": defaultdict(Counter),
                    "observed_rounds": set(),
                    "matches": set(),
                    "maps": set(),
                    "sources": set(),
                    "combat": Counter(),
                    "utility": Counter(),
                    "tactics": Counter(),
                    "map_metrics": defaultdict(Counter),
                }

            teams = {}

            def team_bucket(name: Any) -> dict | None:
                display = _team_name(name)
                key = _team_key(display)
                if not key:
                    return None
                return teams.setdefault(key, {
                    "team": display,
                    "rounds": set(),
                    "matches": set(),
                    "maps": set(),
                    "labels": Counter(),
                    "map_labels": defaultdict(Counter),
                    "map_rounds": defaultdict(set),
                    "sources": set(),
                })

            event_rows = connection.execute(
                "SELECT node_id,map_name,match_id,round_number,properties "
                "FROM nodes WHERE node_type='event'"
            ).fetchall()
            event_by_id = {}
            for row in event_rows:
                props = json.loads(row["properties"])
                event_by_id[row["node_id"]] = (row, props)
                round_key = (row["match_id"], row["map_name"], row["round_number"])
                for field in (
                    "killer_team", "victim_team", "assister_team", "thrower_team",
                    "attacker_team", "planter_team",
                ):
                    bucket = team_bucket(props.get(field))
                    if not bucket:
                        continue
                    bucket["rounds"].add(round_key)
                    bucket["matches"].add(row["match_id"])
                    bucket["maps"].add((row["match_id"], row["map_name"]))
                    bucket["map_rounds"][row["map_name"]].add(round_key)

            role_team_fields = {
                "KILLER": "killer_team",
                "VICTIM": "victim_team",
                "ASSISTER": "assister_team",
                "THROWER": "thrower_team",
                "FLASHER": "attacker_team",
                "BLINDED": "victim_team",
                "PLANTER": "planter_team",
            }
            role_rows = connection.execute(
                "SELECT e.source_id,e.relation,e.target_id FROM edges e "
                "JOIN nodes n ON n.node_id=e.source_id "
                "WHERE n.node_type='event' AND e.relation IN "
                "('KILLER','VICTIM','ASSISTER','THROWER','FLASHER','BLINDED','PLANTER')"
            ).fetchall()
            for edge in role_rows:
                player = players.get(edge["target_id"])
                event_item = event_by_id.get(edge["source_id"])
                if not player or not event_item:
                    continue
                row, props = event_item
                relation = edge["relation"]
                kind = props.get("kind")
                round_key = (row["match_id"], row["map_name"], row["round_number"])
                source = f"graph:{row['match_id']}:{row['map_name']}:{row['round_number']}"
                player["observed_rounds"].add(round_key)
                player["matches"].add(row["match_id"])
                player["maps"].add((row["match_id"], row["map_name"]))
                player["sources"].add(source)
                team = _team_name(props.get(role_team_fields[relation]))
                if team != "Unknown":
                    player["team_events"][team] += 1
                    player["team_maps"][(row["match_id"], row["map_name"])][team] += 1
                metric = None
                if kind == "kill" and relation == "KILLER":
                    metric = "kills"
                    player["combat"]["kills"] += 1
                    if props.get("is_headshot"):
                        player["combat"]["headshots"] += 1
                    if props.get("is_first_kill"):
                        player["combat"]["opening_kills"] += 1
                elif kind == "kill" and relation == "VICTIM":
                    metric = "deaths"
                    player["combat"]["deaths"] += 1
                    if props.get("is_first_kill"):
                        player["combat"]["opening_deaths"] += 1
                elif kind == "kill" and relation == "ASSISTER":
                    metric = "assists"
                    player["combat"]["assists"] += 1
                elif kind == "grenade" and relation == "THROWER":
                    metric = "utility_thrown"
                    player["utility"]["thrown"] += 1
                elif kind == "flash" and relation == "FLASHER":
                    metric = "flash_blinds"
                    player["utility"]["flash_blinds"] += 1
                elif kind == "flash" and relation == "BLINDED":
                    metric = "times_blinded"
                    player["utility"]["times_blinded"] += 1
                elif kind == "plant" and relation == "PLANTER":
                    metric = "plants"
                    player["utility"]["plants"] += 1
                if metric:
                    player["map_metrics"][row["map_name"]][metric] += 1

            tactic_rows = connection.execute(
                "SELECT node_id,label,map_name,match_id,round_number,properties "
                "FROM nodes WHERE node_type='tactical_sequence'"
            ).fetchall()
            tactics_by_id = {}
            for row in tactic_rows:
                props = json.loads(row["properties"])
                tactics_by_id[row["node_id"]] = (row, props)
                bucket = team_bucket(props.get("team"))
                if not bucket:
                    continue
                label = props.get("label_type") or row["label"]
                bucket["labels"][label] += 1
                bucket["map_labels"][row["map_name"]][label] += 1
                bucket["sources"].add(
                    f"graph:{row['match_id']}:{row['map_name']}:{row['round_number']}"
                )

            participant_rows = connection.execute(
                "SELECT source_id,target_id FROM edges WHERE relation='INVOLVES_PLAYER'"
            ).fetchall()
            for edge in participant_rows:
                player = players.get(edge["target_id"])
                tactic_item = tactics_by_id.get(edge["source_id"])
                if not player or not tactic_item:
                    continue
                row, props = tactic_item
                label = props.get("label_type") or row["label"]
                player["tactics"][label] += 1
                player["map_metrics"][row["map_name"]]["tactical_sequences"] += 1
                source = f"graph:{row['match_id']}:{row['map_name']}:{row['round_number']}"
                player["sources"].add(source)
                details = props.get("details") or {}
                steamid = player["player_id"]
                if label == "TRADE_KILL" and details.get("trader_steamid") == steamid:
                    player["combat"]["trade_kills"] += 1
                elif label == "TRADE_KILL" and details.get("traded_player_steamid") == steamid:
                    player["combat"]["traded_deaths"] += 1

            rendered_players = {}
            for graph_id, raw in players.items():
                ordered_teams = raw["team_events"].most_common()
                primary_team = ordered_teams[0][0] if ordered_teams else "Unknown"
                player_rounds = set()
                map_rounds = defaultdict(set)
                for (match_id, map_name), counts in raw["team_maps"].items():
                    match_team = counts.most_common(1)[0][0]
                    bucket = teams.get(_team_key(match_team))
                    if not bucket:
                        continue
                    for round_key in bucket["rounds"]:
                        if round_key[:2] == (match_id, map_name):
                            player_rounds.add(round_key)
                            map_rounds[round_key[1]].add(round_key)
                player_rounds = player_rounds or raw["observed_rounds"]
                combat = {key: raw["combat"][key] for key in (
                    "kills", "deaths", "assists", "headshots", "opening_kills",
                    "opening_deaths", "trade_kills", "traded_deaths",
                )}
                deaths = combat["deaths"]
                opening_attempts = combat["opening_kills"] + combat["opening_deaths"]
                combat["kd_ratio"] = round(combat["kills"] / deaths, 2) if deaths else None
                combat["headshot_pct"] = round(100 * combat["headshots"] / combat["kills"], 1) if combat["kills"] else 0.0
                combat["opening_duel_win_pct"] = round(100 * combat["opening_kills"] / opening_attempts, 1) if opening_attempts else None
                utility = {key: raw["utility"][key] for key in (
                    "thrown", "flash_blinds", "times_blinded", "plants",
                )}
                rounds = len(player_rounds)
                rate_inputs = {
                    "kills": combat["kills"], "deaths": combat["deaths"],
                    "assists": combat["assists"], "opening_kills": combat["opening_kills"],
                    "trade_kills": combat["trade_kills"], "utility_thrown": utility["thrown"],
                    "flash_blinds": utility["flash_blinds"], "plants": utility["plants"],
                }
                rendered_players[graph_id] = {
                    "player_id": raw["player_id"],
                    "graph_id": graph_id,
                    "name": raw["name"],
                    "team": primary_team,
                    "teams": [
                        {"team": team, "event_appearances": count}
                        for team, count in ordered_teams
                    ],
                    "sample_size": {
                        "matches": len(raw["matches"]), "maps": len(raw["maps"]),
                        "map_pool_size": len({item[1] for item in raw["maps"]}),
                        "rounds": rounds,
                    },
                    "combat": combat,
                    "utility": utility,
                    "tactical_participation": {
                        label: raw["tactics"][label] for label in TACTICAL_LABELS
                    },
                    "rates_per_100_rounds": {
                        key: round(100 * count / rounds, 2) if rounds else 0.0
                        for key, count in rate_inputs.items()
                    },
                    "map_breakdown": [
                        {
                            "map": map_name,
                            "rounds": len(map_rounds.get(map_name, set())),
                            **{key: value for key, value in metrics.items()},
                        }
                        for map_name, metrics in sorted(raw["map_metrics"].items())
                    ],
                    "source_round_ids": sorted(raw["sources"])[:12],
                    "methodology": {
                        "version": "graph-analytics-v1",
                        "rounds": "team rounds on maps where the player was observed",
                        "scope": "parsed events and deterministic silver tactical labels",
                        "flash_metric_available": any(
                            props.get("kind") == "flash" for _, props in event_by_id.values()
                        ),
                    },
                }

            rendered_teams = {}
            for key, raw in teams.items():
                rounds = len(raw["rounds"])
                labels = {
                    label: {
                        "count": raw["labels"][label],
                        "per_100_rounds": round(100 * raw["labels"][label] / rounds, 2) if rounds else 0.0,
                    }
                    for label in TACTICAL_LABELS
                }
                rendered_teams[key] = {
                    "team": raw["team"],
                    "sample_size": {
                        "matches": len(raw["matches"]), "maps": len(raw["maps"]),
                        "map_pool_size": len({item[1] for item in raw["maps"]}),
                        "rounds": rounds,
                    },
                    "tactical_sequences": sum(raw["labels"].values()),
                    "labels": labels,
                    "map_breakdown": [
                        {
                            "map": map_name,
                            "rounds": len(raw["map_rounds"].get(map_name, set())),
                            "labels": {
                                label: raw["map_labels"][map_name][label]
                                for label in TACTICAL_LABELS
                            },
                        }
                        for map_name in sorted(raw["map_rounds"])
                    ],
                    "source_round_ids": sorted(raw["sources"])[:12],
                }
            return rendered_players, rendered_teams
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
            tactic_limit = min(24, remaining // 3 or remaining)
            tactics = connection.execute(
                f"SELECT {columns} FROM nodes WHERE (? IS NULL OR map_name=?) "
                "AND node_type='tactical_sequence' ORDER BY match_id,round_number,node_id LIMIT ?",
                (map_name, map_name, tactic_limit),
            ).fetchall()
            remaining -= len(tactics)
            event_limit = max(0, remaining * 2 // 3)
            events = connection.execute(
                f"SELECT {columns} FROM nodes WHERE (? IS NULL OR map_name=?) "
                "AND node_type='event' ORDER BY match_id,round_number,node_id LIMIT ?",
                (map_name, map_name, event_limit),
            ).fetchall()
            remaining -= len(events)
            source_ids = {row["node_id"] for row in [*events, *tactics]}
            players = []
            if source_ids and remaining:
                source_placeholders = ",".join("?" for _ in source_ids)
                players = connection.execute(
                    f"SELECT DISTINCT n.{columns.replace(',', ',n.')} FROM edges e "
                    "JOIN nodes n ON n.node_id=e.target_id "
                    f"WHERE e.source_id IN ({source_placeholders}) AND n.node_type='player' "
                    "ORDER BY n.label LIMIT ?",
                    [*source_ids, remaining],
                ).fetchall()
            rows = [*anchors, *rounds, *tactics, *events, *players]
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
                for index, event in enumerate(events, start=1):
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

        annotations = annotate_match(parsed, source_demo=demo_path.name, match_id=match_id)
        for annotation in annotations:
            number = str(annotation["round_number"])
            round_node = f"round:{match_id}:{map_name}:{number}"
            for label in annotation["labels"]:
                sequence_id = f"tactic:{label['label_id']}"
                props = {**label, "kind": "tactical_sequence"}
                nodes.append((
                    sequence_id,
                    "tactical_sequence",
                    label["label_type"],
                    map_name,
                    match_id,
                    number,
                    _json(props),
                ))
                edges.append((round_node, "HAS_TACTICAL_SEQUENCE", sequence_id, "{}"))
                for evidence_id in label["evidence_event_ids"]:
                    edges.append((sequence_id, "SUPPORTED_BY", f"event:{evidence_id}", "{}"))
                for player_id in label["participant_ids"]:
                    edges.append((sequence_id, "INVOLVES_PLAYER", f"player:{player_id}", "{}"))
        return list({row[0]: row for row in nodes}.values()), list({(row[0], row[1], row[2]): row for row in edges}.values())

    def _retrieve_sync(self, query: str, metadata: dict, task_id: str | None, k: int) -> list[Evidence]:
        map_name = _map_name(metadata["map"]) if metadata.get("map") else None
        expanded_query = _query_text(query)
        terms = set(re.findall(r"[a-z0-9_]+", expanded_query))
        topic = self._topic(task_id, terms, expanded_query)
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
                events = []
                for item in event_rows:
                    event = json.loads(item["properties"])
                    events.append((event.get("kind", item["label"]), event))
                score = self._round_score(events, props, topic, terms, expanded_query)
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
            sequence_types = {
                event.get("label_type") for event in events if event.get("kind") == "tactical_sequence"
            }
            if topic == "opening" and not (
                any(event.get("is_first_kill") for event in events)
                or sequence_types & {"OPENING_DUEL", "TRADE_KILL"}
            ):
                continue
            if topic == "utility" and not (
                kinds["grenade"] or kinds["flash"]
                or sequence_types & {"UTILITY_BURST", "EXECUTE_CANDIDATE"}
            ):
                continue
            if topic == "round_flow" and not (
                kinds["kill"] or kinds["plant"]
                or sequence_types & {"POST_PLANT", "RETAKE_CONTACT"}
            ):
                continue
            selected.append((round_row, events))
        selected = selected or round_data
        source_ids = [row["node_id"] for row, _ in selected]
        matches = {row["match_id"] for row, _ in selected}
        kills = [event for _, events in selected for event in events if event.get("kind") == "kill"]
        grenades = [event for _, events in selected for event in events if event.get("kind") == "grenade"]
        flashes = [event for _, events in selected for event in events if event.get("kind") == "flash"]
        plants = [event for _, events in selected for event in events if event.get("kind") == "plant"]
        sequences = [
            event for _, events in selected for event in events
            if event.get("kind") == "tactical_sequence"
        ]
        sequence_types = Counter(event.get("label_type", "Unknown") for event in sequences)
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
            "tactical_sequences": dict(sequence_types),
        }
        winner_text = ", ".join(f"{name} {count}" for name, count in winners.most_common(4)) or "none"
        player_text = ", ".join(f"{name} {count}" for name, count in opening_players.most_common(5)) or "none"
        death_text = ", ".join(f"{name} {count}" for name, count in opening_deaths.most_common(5)) or "none"
        weapon_text = ", ".join(f"{name} {count}" for name, count in opening_weapons.most_common(5)) or "none"
        utility_text = ", ".join(f"{name} {count}" for name, count in utility_types.most_common(5)) or "none"
        sequence_text = ", ".join(f"{name} {count}" for name, count in sequence_types.most_common()) or "none"
        thrower_text = ", ".join(f"{name} {count}" for name, count in utility_throwers.most_common(5)) or "none"
        reason_text = ", ".join(f"{name} {count}" for name, count in end_reasons.most_common(5)) or "none"
        prefix = (
            f"[Community Summary | {map_name} | {topic}] Based on {len(matches)} matches and "
            f"{len(selected)} parsed rounds. "
        )
        if topic == "opening":
            body = (
                f"Opening duels: {len(first_kills)}. First-kill players: {player_text}. "
                f"First-death players: {death_text}. Opening weapons: {weapon_text}. "
                f"Tactical labels: {sequence_text}."
            )
        elif topic == "utility":
            body = (
                f"Utility usage: {len(grenades)} detonations and {len(flashes)} recorded blind events. "
                f"Types: {utility_text}. Throwers: {thrower_text}. Tactical labels: {sequence_text}."
            )
        elif topic == "round_flow":
            body = (
                f"Round flow: {len(kills)} kills and {len(plants)} bomb plants. "
                f"Round winners: {winner_text}. End reasons: {reason_text}. Tactical labels: {sequence_text}."
            )
        else:
            body = (
                f"Overview: {len(kills)} kills, {properties['first_kills']} first kills, "
                f"{len(grenades)} utility detonations, {len(flashes)} recorded blind events, "
                f"and {len(plants)} bomb plants. Round winners: {winner_text}."
                f" Tactical labels: {sequence_text}."
            )
        summary = prefix + body + " This is an extractive factual summary; it does not establish tactical causality."
        return summary, source_ids, properties

    def _tactical_query_context(self, query: str, fallback_map: str | None) -> dict:
        connection = self._connect()
        try:
            available_teams = [
                row[0] for row in connection.execute(
                    "SELECT DISTINCT json_extract(properties, '$.team') FROM nodes "
                    "WHERE node_type='tactical_sequence' "
                    "AND json_extract(properties, '$.team') IS NOT NULL"
                )
            ]
        finally:
            connection.close()
        lowered = query.lower()
        mentions = []
        for alias, name in TEAM_ALIASES.items():
            position = lowered.find(alias.lower())
            if position >= 0:
                mentions.append((position, TEAM_DISPLAY_NAMES.get(name, name.title())))
        for name in available_teams:
            position = lowered.find(str(name).lower())
            if position >= 0:
                mentions.append((position, _team_name(name)))
        teams = []
        seen = set()
        for _, name in sorted(mentions):
            key = _team_key(name)
            if key not in seen:
                seen.add(key)
                teams.append(name)

        has_t = bool(re.search(r"(?<![a-z0-9])t(?:\s*side|侧)?(?![a-z0-9])", lowered)) or "进攻侧" in query or "进攻方" in query
        has_ct = bool(re.search(r"(?<![a-z0-9])ct(?:\s*side|侧)?(?![a-z0-9])", lowered)) or "防守侧" in query or "防守方" in query
        side = "T" if has_t and not has_ct else "CT" if has_ct and not has_t else None
        return {
            "teams": teams,
            "map": _query_map_name(query) or fallback_map,
            "side": side,
            "comparison": len(teams) > 1 and any(
                word in lowered for word in ("compare", "comparison", "difference", "对比", "比较", "区别", "差异")
            ),
        }

    def _tactical_query_evidence(
        self, query: str, fallback_map: str | None,
    ) -> list[Evidence]:
        context = self._tactical_query_context(query, fallback_map)
        teams = context["teams"]
        if not teams:
            return []
        if context["comparison"]:
            profiles = [
                self.team_tactics(team, map_name=context["map"], side=context["side"])
                for team in teams[:2]
            ]
            profiles = [profile for profile in profiles if profile]
            if not profiles:
                return []
            lines = [
                f"[Graph Tactical Comparison | {' vs '.join(profile['team'] for profile in profiles)}]"
            ]
            for profile in profiles:
                sample = profile["sample_size"]
                conversions = profile["conversions"]
                lines.append(
                    f"{profile['team']}: {sample['matches']} matches, {sample['maps']} maps, "
                    f"{sample['rounds']} rounds; round win {_pct_text(profile['outcomes']['round_win_pct'])}; "
                    f"opening-to-win {_pct_text(conversions['opening_won']['round_win_pct'])}; "
                    f"trade-round win {_pct_text(conversions['trade_round']['round_win_pct'])}; "
                    f"post-plant win {_pct_text(conversions['post_plant']['round_win_pct'])}; "
                    f"retake-contact win {_pct_text(conversions['retake_contact']['round_win_pct'])}."
                )
            sources = sorted({
                source for profile in profiles for source in profile["source_round_ids"]
            })
            source_id = "graph-comparison:" + ":".join(_team_key(item["team"]) for item in profiles)
            return [Evidence(
                content=" ".join(lines) + " Descriptive silver-label evidence only; no causal claim. Graph source paths: " + ", ".join(sources[:12]),
                metadata={
                    "map": context["map"] or "All",
                    "side": context["side"] or "Both",
                    "teams": [profile["team"] for profile in profiles],
                    "tactic_type": "Graph Tactical Comparison",
                    "source": source_id,
                    "topic": self._topic(None, set(), query) or "overview",
                    "context_level": "team_tactical_comparison",
                    "profiles": [{
                        "team": profile["team"],
                        "sample_size": profile["sample_size"],
                        "outcomes": profile["outcomes"],
                        "conversions": profile["conversions"],
                    } for profile in profiles],
                    "source_round_count": len(sources),
                    "source_round_ids": sources[:12],
                },
                score=1.0 if any(profile["sample_size"]["rounds"] for profile in profiles) else 0.6,
                source_id=source_id,
            )]

        opponent = teams[1] if len(teams) > 1 else None
        profile = self.team_tactics(
            teams[0], map_name=context["map"], side=context["side"], opponent=opponent,
        )
        if not profile:
            return []
        sample = profile["sample_size"]
        conversions = profile["conversions"]
        leaders = profile["role_leaders"]
        leader_text = ", ".join(
            f"{label} {items[0]['name']} ({items[0]['count']})"
            for label, items in (
                ("opening", leaders["opening_kills"]),
                ("trade", leaders["trade_kills"]),
                ("utility", leaders["utility_burst_participation"]),
            )
            if items
        ) or "none"
        source_id = "graph-profile:" + ":".join(filter(None, (
            _team_key(profile["team"]), context["map"], context["side"], _team_key(opponent),
        )))
        content = (
            f"[Graph Team Tactical Profile | {profile['team']} | {context['map'] or 'All maps'} | "
            f"{context['side'] or 'Both sides'}{f' | vs {opponent}' if opponent else ''}] "
            f"Sample: {sample['matches']} matches, {sample['maps']} maps, {sample['rounds']} rounds. "
            f"Round win: {_pct_text(profile['outcomes']['round_win_pct'])}. "
            f"Opening won: {conversions['opening_won']['opportunities']} rounds, then won "
            f"{_pct_text(conversions['opening_won']['round_win_pct'])}; opening lost: "
            f"{conversions['opening_lost_recovery']['opportunities']} rounds, recovered "
            f"{_pct_text(conversions['opening_lost_recovery']['round_win_pct'])}. "
            f"Trade-round win: {_pct_text(conversions['trade_round']['round_win_pct'])}; "
            f"post-plant win: {_pct_text(conversions['post_plant']['round_win_pct'])}; "
            f"retake-contact win: {_pct_text(conversions['retake_contact']['round_win_pct'])}; "
            f"execute-candidate win: {_pct_text(conversions['execute_candidate']['round_win_pct'])}. "
            f"Role leaders: {leader_text}. Descriptive silver-label evidence only; no causal claim. "
            f"Graph source paths: {', '.join(profile['source_round_ids'])}."
        )
        return [Evidence(
            content=content,
            metadata={
                "map": context["map"] or "All",
                "side": context["side"] or "Both",
                "team": profile["team"],
                "opponent": opponent,
                "tactic_type": "Graph Team Tactical Profile",
                "source": source_id,
                "topic": self._topic(None, set(), query) or "overview",
                "context_level": "team_tactical_profile",
                "sample_size": sample,
                "outcomes": profile["outcomes"],
                "conversions": conversions,
                "role_leaders": leaders,
                "source_round_count": len(profile["source_round_ids"]),
                "source_round_ids": profile["source_round_ids"],
            },
            score=1.0 if sample["rounds"] else 0.6,
            source_id=source_id,
        )]

    def _global_search_sync(self, query: str, metadata: dict, k: int) -> list[Evidence]:
        map_name = _query_map_name(query) or (
            _map_name(metadata["map"]) if metadata.get("map") else None
        )
        tactical = self._tactical_query_evidence(query, map_name)
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
            communities = [
                self._community_evidence(score, row)
                for score, row in ranked[:max(0, k - len(tactical))]
            ]
            return [*tactical, *communities][:k]
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
    def _round_score(
        events: list[tuple[str, dict]], props: dict, topic: str | None, terms: set[str], query: str = "",
    ) -> float:
        kinds = Counter(kind for kind, _ in events)
        sequence_types = {
            event.get("label_type") for kind, event in events if kind == "tactical_sequence"
        }
        score = 0.0
        if topic == "opening":
            score += 0.5 if any(event.get("is_first_kill") for kind, event in events if kind == "kill") else 0
            score += 0.5 if sequence_types & {"OPENING_DUEL", "TRADE_KILL"} else 0
        elif topic == "utility":
            score += min(0.5, (kinds["grenade"] + kinds["flash"]) / 8)
            score += 0.5 if sequence_types & {"UTILITY_BURST", "EXECUTE_CANDIDATE"} else 0
        elif topic == "round_flow":
            score += min(0.5, (kinds["kill"] + kinds["plant"]) / 12)
            score += 0.5 if sequence_types & {"POST_PLANT", "RETAKE_CONTACT"} else 0
        elif topic == "overview":
            score += min(1.0, len(events) / 8)
        lowered = query.lower()
        requested_types = set()
        if "execute" in lowered or "爆弹" in lowered:
            requested_types.add("EXECUTE_CANDIDATE")
        if "trade" in lowered or "补枪" in lowered:
            requested_types.add("TRADE_KILL")
        if "retake" in lowered or "回防" in lowered:
            requested_types.add("RETAKE_CONTACT")
        if "post-plant" in lowered or "postplant" in lowered or "下包后" in lowered:
            requested_types.add("POST_PLANT")
        if requested_types:
            score += 0.4 if requested_types & sequence_types else -0.4
        identity_keys = {
            "team", "killer", "killer_team", "victim", "victim_team", "assister",
            "thrower", "thrower_team", "attacker", "planter", "planter_team",
        }
        identity_text = " ".join(
            str(value).lower()
            for _, event in events
            for key, value in event.items()
            if key in identity_keys and value
        )
        score += min(0.6, sum(
            1 for term in terms if len(term) >= 3 and term in identity_text
        ) * 0.3)
        text = " ".join([props.get("winner", ""), props.get("reason", "")] + [kind for kind, _ in events]).lower()
        score += min(0.5, sum(1 for term in terms if term in text) * 0.05)
        return score

    @staticmethod
    def _evidence(item: tuple, topic: str | None) -> Evidence:
        score, row, props, events = item
        lines = [
            f"[Graph path] Match {row['match_id']} -> {row['map_name']} -> Round {row['round_number']}",
            f"Round winner: {_text(props.get('winner'))}; end reason: {_text(props.get('reason'))}.",
        ]
        tactical_labels = []
        tactical_label_details = []
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
            elif kind == "tactical_sequence":
                label_type = event.get("label_type", "Unknown")
                tactical_labels.append(label_type)
                source = event.get("label_source", "unknown")
                confidence = float(event.get("confidence", 0.0))
                tactical_label_details.append({
                    key: event.get(key)
                    for key in (
                        "label_id", "label_type", "label_source", "confidence", "team", "site",
                        "participant_ids", "evidence_event_ids",
                    )
                })
                lines.append(
                    f"Tactical label {label_type}: team {event.get('team') or 'Unknown'}, "
                    f"site {event.get('site') or 'Unknown'}, ticks {event.get('start_tick', '?')}-"
                    f"{event.get('end_tick', '?')}, label_source={source}, "
                    f"confidence={confidence:.2f}, label_id={event.get('label_id', 'Unknown')}."
                )
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
                "tactical_labels": sorted(set(tactical_labels)),
                "tactical_label_details": tactical_label_details,
            },
            score=float(min(1.0, score)),
            source_id=source,
        )
