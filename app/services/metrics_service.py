"""Deterministic match metrics extracted from the normalized round payload."""

from collections import Counter
from typing import Any, Dict, Iterable, List, Optional


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"none", "nan", "unknown"} else text


def _side(value: Any) -> str:
    side = _text(value).upper()
    return {"TERRORIST": "T", "COUNTERTERRORIST": "CT"}.get(side, side)


def _round_kills(round_data: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    kills = round_data.get("kills")
    if isinstance(kills, list) and kills:
        return (_as_dict(kill) for kill in kills)
    events = round_data.get("events")
    if not isinstance(events, list):
        return ()
    return (
        _as_dict(event)
        for event in events
        if _as_dict(event).get("type") in {"kill", "player_death"}
    )


def _valid_combat_kill(kill: Dict[str, Any]) -> bool:
    killer = _text(kill.get("killer") or kill.get("attacker_name"))
    victim = _text(kill.get("victim") or kill.get("user_name"))
    if not killer or not victim or killer == victim:
        return False
    if _text(kill.get("weapon")).lower() == "world":
        return False
    killer_team = _text(kill.get("killer_team") or kill.get("attacker_team"))
    victim_team = _text(kill.get("victim_team") or kill.get("user_team"))
    if killer_team and victim_team and killer_team == victim_team:
        return False
    killer_side = _side(kill.get("killer_side") or kill.get("attacker_side"))
    victim_side = _side(kill.get("victim_side") or kill.get("user_side"))
    return not (killer_side and victim_side and killer_side == victim_side)


def _first_kill_index(kills: List[Dict[str, Any]]) -> Optional[int]:
    marked = [index for index, kill in enumerate(kills) if kill.get("is_first_kill") is True]
    return marked[0] if marked else (0 if kills else None)


def _player_bucket(players: Dict[str, Dict[str, int]], name: str) -> Dict[str, int]:
    if name not in players:
        players[name] = {"kills": 0, "deaths": 0, "first_kills": 0}
    return players[name]


def _team_bucket(teams: Dict[str, Dict[str, int]], name: str) -> Dict[str, int]:
    if name not in teams:
        teams[name] = {"kills": 0, "deaths": 0, "first_kills": 0}
    return teams[name]


def _roster_teams_by_side(round_data: Dict[str, Any]) -> Dict[str, str]:
    participants = round_data.get("participants", [])
    pairs = {(_side(p.get("side")), _text(p.get("team")))
             for p in participants if isinstance(p, dict)} if isinstance(participants, list) else set()
    if (round_data.get("participants_complete") is True and len(pairs) == 2
            and {side for side, _ in pairs} == {"T", "CT"}
            and len({team for _, team in pairs if team}) == 2):
        return dict(sorted(pairs))
    return {}


def _teams_by_side(round_data: Dict[str, Any]) -> Dict[str, str]:
    roster_teams = _roster_teams_by_side(round_data)
    if roster_teams:
        return roster_teams
    candidates: Dict[str, Counter] = {}

    def add(side: Any, team: Any) -> None:
        normalized_side, normalized_team = _side(side), _text(team)
        if normalized_side and normalized_team:
            candidates.setdefault(normalized_side, Counter())[normalized_team] += 1

    for kill in _round_kills(round_data):
        add(kill.get("killer_side"), kill.get("killer_team"))
        add(kill.get("victim_side"), kill.get("victim_team"))
    for grenade in round_data.get("grenades", []):
        add(grenade.get("thrower_side"), grenade.get("thrower_team"))
    for plant in round_data.get("plants", []):
        add(plant.get("planter_side"), plant.get("planter_team"))
    return {
        side: counts.most_common(1)[0][0]
        for side, counts in candidates.items()
        if counts
    }


def calculate_metrics(rounds: Any) -> Dict[str, Any]:
    """Return only facts supported by the supplied event data."""
    round_list = rounds if isinstance(rounds, list) else []
    rounds_won: Counter = Counter()
    rounds_won_by_team: Counter = Counter()
    rounds_won_by_team_and_side: Dict[str, Counter] = {}
    side_performance: Dict[str, Dict[str, Dict[str, Any]]] = {}
    players: Dict[str, Dict[str, int]] = {}
    teams: Dict[str, Dict[str, int]] = {}
    evidence: List[Dict[str, Any]] = []
    round_summaries: List[Dict[str, Any]] = []
    grenade_types: Counter = Counter()
    grenades_by_team: Counter = Counter()
    plants_by_team: Counter = Counter()
    post_plant_attempts: Counter = Counter()
    post_plant_wins: Counter = Counter()
    defuses_by_team: Counter = Counter()
    flash_blinds_by_team: Counter = Counter()
    enemy_flash_blinds_by_team: Counter = Counter()
    team_flash_blinds_by_team: Counter = Counter()
    opening_attempts: Counter = Counter()
    opening_wins: Counter = Counter()
    kills_total = first_kills_total = grenades_total = plants_total = flash_blinds_total = 0

    for index, raw_round in enumerate(round_list, start=1):
        round_data = _as_dict(raw_round)
        winner_side = _side(round_data.get("winner")) or "Unknown"
        rounds_won[winner_side] += 1
        team_by_side = _teams_by_side(round_data)
        winner_team = team_by_side.get(winner_side, "")
        if winner_team:
            rounds_won_by_team[winner_team] += 1
            rounds_won_by_team_and_side.setdefault(winner_team, Counter())[winner_side] += 1

        # Side denominators require the full round roster, not only winners or
        # players who happened to emit events. Unknown outcomes are not losses.
        for side, team in _roster_teams_by_side(round_data).items():
            bucket = side_performance.setdefault(team, {}).setdefault(
                side, {"rounds": 0, "known_outcomes": 0, "round_wins": 0, "win_rate_pct": None})
            bucket["rounds"] += 1
            if winner_side in {"CT", "T"}:
                bucket["known_outcomes"] += 1
                bucket["round_wins"] += int(winner_side == side)
            if bucket["known_outcomes"]:
                bucket["win_rate_pct"] = round(100 * bucket["round_wins"] / bucket["known_outcomes"], 1)

        kills = [kill for kill in _round_kills(round_data) if _valid_combat_kill(kill)]
        first_index = _first_kill_index(kills)
        opening_team = ""
        kill_sequence = []
        for kill_index, kill in enumerate(kills):
            killer = _text(kill.get("killer") or kill.get("attacker_name"))
            victim = _text(kill.get("victim") or kill.get("user_name"))
            killer_team = _text(kill.get("killer_team") or kill.get("attacker_team"))
            victim_team = _text(kill.get("victim_team") or kill.get("user_team"))
            is_first_kill = kill_index == first_index

            _player_bucket(players, killer)["kills"] += 1
            _player_bucket(players, victim)["deaths"] += 1
            if killer_team:
                _team_bucket(teams, killer_team)["kills"] += 1
            if victim_team:
                _team_bucket(teams, victim_team)["deaths"] += 1
            if is_first_kill:
                _player_bucket(players, killer)["first_kills"] += 1
                if killer_team:
                    _team_bucket(teams, killer_team)["first_kills"] += 1
                    opening_team = killer_team
                    opening_attempts[killer_team] += 1
                    opening_wins[killer_team] += int(killer_team == winner_team)

            event = {
                "round_number": round_data.get("round_number", index),
                "tick": kill.get("tick"),
                "killer": killer,
                "victim": victim,
                "killer_team": killer_team,
                "victim_team": victim_team,
                "weapon": kill.get("weapon"),
                "is_first_kill": is_first_kill,
            }
            evidence.append(event)
            kill_sequence.append(event)
            kills_total += 1
            first_kills_total += int(is_first_kill)

        round_grenades = Counter()
        for grenade in round_data.get("grenades", []):
            grenade_type = _text(grenade.get("type")) or "Unknown"
            team = _text(grenade.get("thrower_team"))
            grenade_types[grenade_type] += 1
            round_grenades[grenade_type] += 1
            if team:
                grenades_by_team[team] += 1
            grenades_total += 1

        plant_sites = []
        plant_teams = []
        for plant in round_data.get("plants", []):
            team = _text(plant.get("planter_team"))
            if team:
                plants_by_team[team] += 1
                plant_teams.append(team)
            plant_sites.append(_text(plant.get("site")) or "Unknown")
            plants_total += 1

        reason = _text(round_data.get("reason"))
        for team in sorted(set(plant_teams)):
            post_plant_attempts[team] += 1
            post_plant_wins[team] += int(team == winner_team)
        if reason.lower() == "bomb_defused" and winner_team:
            defuses_by_team[winner_team] += 1

        opening_event = next(
            (item for item in kill_sequence if item["is_first_kill"]),
            None,
        )
        if not plant_teams:
            plant_outcome = None
        elif reason.lower() == "bomb_defused" and winner_team:
            plant_outcome = f"{', '.join(sorted(set(plant_teams)))} planted; {winner_team} defused"
        elif winner_team:
            plant_outcome = f"{', '.join(sorted(set(plant_teams)))} planted; {winner_team} won"
        else:
            plant_outcome = f"{', '.join(sorted(set(plant_teams)))} planted; outcome unavailable"

        round_flash_blinds = Counter()
        for blind in round_data.get("flash_blinds", []):
            attacker_team = _text(blind.get("attacker_team"))
            victim_team = _text(blind.get("victim_team"))
            if attacker_team:
                flash_blinds_by_team[attacker_team] += 1
                round_flash_blinds[attacker_team] += 1
                if victim_team == attacker_team:
                    team_flash_blinds_by_team[attacker_team] += 1
                elif victim_team:
                    enemy_flash_blinds_by_team[attacker_team] += 1
            flash_blinds_total += 1
        round_summaries.append({
            "round_number": round_data.get("round_number", index),
            "winner_side": winner_side,
            "winner_team": winner_team or None,
            "reason": reason or None,
            "opening_team": opening_team or None,
            "opening_killer": opening_event["killer"] if opening_event else None,
            "kills": len(kill_sequence),
            "kill_sequence": kill_sequence,
            "grenades": sum(round_grenades.values()),
            "grenades_by_type": dict(sorted(round_grenades.items())),
            "plants": len(plant_sites),
            "plant_sites": plant_sites,
            "plant_teams": sorted(set(plant_teams)),
            "plant_outcome": plant_outcome,
            "flash_blinds": sum(round_flash_blinds.values()),
            "flash_blinds_by_team": dict(sorted(round_flash_blinds.items())),
        })

    opening_duels = {
        team: {
            "attempts": attempts,
            "round_wins": opening_wins[team],
            "conversion_pct": round(100 * opening_wins[team] / attempts, 1),
        }
        for team, attempts in sorted(opening_attempts.items())
    }
    post_plant = {
        team: {
            "attempts": attempts,
            "round_wins": post_plant_wins[team],
            "conversion_pct": round(100 * post_plant_wins[team] / attempts, 1),
        }
        for team, attempts in sorted(post_plant_attempts.items())
    }
    available_metrics = [
        "rounds_total", "rounds_won", "kills", "deaths", "first_kills",
        "rounds_won_by_team", "rounds_won_by_team_and_side", "team_totals",
        "opening_duel_conversion",
    ]
    if grenades_total:
        available_metrics.append("grenades")
    if side_performance:
        available_metrics.append("side_performance_by_team")
    if plants_total:
        available_metrics.extend(["bomb_plants", "post_plant_conversion", "defuses"])
    if flash_blinds_total:
        available_metrics.extend(["flash_blinds", "enemy_flash_blinds", "team_flash_blinds"])
    if any(_as_dict(round_data).get("damage") for round_data in round_list):
        available_metrics.append("damage")

    return {
        "rounds_total": len(round_list),
        "rounds_won": dict(rounds_won),
        "rounds_won_by_team": dict(rounds_won_by_team),
        "rounds_won_by_team_and_side": {
            team: dict(sorted(side_counts.items()))
            for team, side_counts in sorted(rounds_won_by_team_and_side.items())
        },
        "side_performance_by_team": side_performance,
        "kills_total": kills_total,
        "first_kills_total": first_kills_total,
        "players": players,
        "team_totals": teams,
        "grenades_total": grenades_total,
        "grenades_by_type": dict(sorted(grenade_types.items())),
        "grenades_by_team": dict(sorted(grenades_by_team.items())),
        "plants_total": plants_total,
        "plants_by_team": dict(sorted(plants_by_team.items())),
        "post_plant_by_team": post_plant,
        "defuses_by_team": dict(sorted(defuses_by_team.items())),
        "flash_blinds_total": flash_blinds_total,
        "flash_blinds_by_team": dict(sorted(flash_blinds_by_team.items())),
        "enemy_flash_blinds_by_team": dict(sorted(enemy_flash_blinds_by_team.items())),
        "team_flash_blinds_by_team": dict(sorted(team_flash_blinds_by_team.items())),
        "opening_duels_by_team": opening_duels,
        "round_summaries": round_summaries,
        "evidence": evidence,
        "available_metrics": available_metrics,
    }


def build_current_match_evidence(match: Dict[str, Any], metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build compact, citation-ready evidence from the submitted demo itself."""
    match_id = _text(match.get("match_id")) or "current-demo"
    map_name = _text(match.get("map_name")) or "Unknown"
    team_scores = ", ".join(f"{team} {wins}" for team, wins in metrics["rounds_won_by_team"].items()) or "unavailable"
    openings = ", ".join(
        f"{team} {value['round_wins']}/{value['attempts']} ({value['conversion_pct']}%)"
        for team, value in metrics["opening_duels_by_team"].items()
    ) or "unavailable"
    side_splits = ", ".join(
        f"{team} {side_counts}"
        for team, side_counts in metrics["rounds_won_by_team_and_side"].items()
    ) or "unavailable"
    post_plants = ", ".join(
        f"{team} {value['round_wins']}/{value['attempts']} ({value['conversion_pct']}%)"
        for team, value in metrics["post_plant_by_team"].items()
    ) or "unavailable"
    summary = (
        f"Current demo summary: map={map_name}; rounds={metrics['rounds_total']}; "
        f"team score={team_scores}; team wins split by the side played={side_splits}; "
        f"side outcomes from complete rosters (wins/known outcomes; rounds includes unknown outcomes)={metrics.get('side_performance_by_team', {})}; "
        f"valid combat kills={metrics['kills_total']}; "
        f"opening-to-round-win={openings}; grenades={metrics['grenades_total']} "
        f"{metrics['grenades_by_type']}; plants={metrics['plants_total']} "
        f"{metrics['plants_by_team']}; post-plant round wins={post_plants}; "
        f"defuses by winner team={metrics['defuses_by_team']}; "
        f"flash-blind events={metrics['flash_blinds_total']} "
        f"by thrower team={metrics['flash_blinds_by_team']}; enemy blinds="
        f"{metrics['enemy_flash_blinds_by_team']}; same-team blinds (including self)="
        f"{metrics['team_flash_blinds_by_team']}."
    )
    evidence = [{
        "source_id": f"current:{match_id}:{map_name}:summary",
        "score": 1.0,
        "metadata": {
            "source": "current_demo", "evidence_scope": "current_match",
            "map": map_name, "match_id": match_id, "tactic_type": "Current Match Summary",
        },
        "content": summary,
    }]
    for round_data in metrics["round_summaries"]:
        kills = "; ".join(
            f"{item['killer']}({item['killer_team']})>{item['victim']}({item['victim_team']})@{item['tick']}"
            for item in round_data["kill_sequence"]
        ) or "none"
        content = (
            f"Current demo round {round_data['round_number']}: winner={round_data['winner_team'] or round_data['winner_side']}; "
            f"reason={round_data['reason']}; opening={round_data['opening_killer'] or 'none'}"
            f"({round_data['opening_team'] or 'unknown'}); kills={kills}; "
            f"grenades={round_data['grenades']} {round_data['grenades_by_type']}; "
            f"plants={round_data['plants']} teams={round_data['plant_teams']} "
            f"sites={round_data['plant_sites']}; plant outcome={round_data['plant_outcome'] or 'none'}; "
            f"flash blinds={round_data['flash_blinds']} {round_data['flash_blinds_by_team']}."
        )
        evidence.append({
            "source_id": f"current:{match_id}:{map_name}:{round_data['round_number']}",
            "score": 1.0,
            "metadata": {
                "source": "current_demo", "evidence_scope": "current_match",
                "map": map_name, "match_id": match_id,
                "round_number": round_data["round_number"], "tactic_type": "Current Round Evidence",
            },
            "content": content,
        })
    return evidence
