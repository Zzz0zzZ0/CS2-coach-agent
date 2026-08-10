"""Deterministic match metrics extracted from the normalized round payload."""

from typing import Any, Dict, Iterable, List, Optional


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


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


def _first_kill_index(kills: List[Dict[str, Any]]) -> Optional[int]:
    marked = [index for index, kill in enumerate(kills) if kill.get("is_first_kill") is True]
    return marked[0] if marked else (0 if kills else None)


def _player_bucket(players: Dict[str, Dict[str, int]], name: str) -> Dict[str, int]:
    if name not in players:
        players[name] = {"kills": 0, "deaths": 0, "first_kills": 0}
    return players[name]


def calculate_metrics(rounds: Any) -> Dict[str, Any]:
    """Return only facts supported by the supplied event data.

    ADR, KAST and rating are intentionally not fabricated when damage, assists,
    or player round-presence data is absent.
    """
    round_list = rounds if isinstance(rounds, list) else []
    rounds_won: Dict[str, int] = {}
    players: Dict[str, Dict[str, int]] = {}
    evidence: List[Dict[str, Any]] = []
    kills_total = 0
    first_kills_total = 0

    for index, raw_round in enumerate(round_list, start=1):
        round_data = _as_dict(raw_round)
        winner = str(round_data.get("winner", "Unknown"))
        rounds_won[winner] = rounds_won.get(winner, 0) + 1

        kills = list(_round_kills(round_data))
        first_index = _first_kill_index(kills)
        for kill_index, kill in enumerate(kills):
            killer = str(kill.get("killer") or kill.get("attacker_name") or "Unknown")
            victim = str(kill.get("victim") or kill.get("user_name") or "Unknown")
            is_first_kill = kill_index == first_index

            _player_bucket(players, killer)["kills"] += 1
            _player_bucket(players, victim)["deaths"] += 1
            if is_first_kill:
                _player_bucket(players, killer)["first_kills"] += 1

            evidence.append(
                {
                    "round_number": round_data.get("round_number", index),
                    "tick": kill.get("tick"),
                    "killer": killer,
                    "victim": victim,
                    "weapon": kill.get("weapon"),
                    "is_first_kill": is_first_kill,
                }
            )
            kills_total += 1
            first_kills_total += int(is_first_kill)

    available_metrics = ["rounds_total", "rounds_won", "kills", "deaths", "first_kills"]
    if any(_as_dict(round_data).get("damage") for round_data in round_list):
        available_metrics.append("damage")

    return {
        "rounds_total": len(round_list),
        "rounds_won": rounds_won,
        "kills_total": kills_total,
        "first_kills_total": first_kills_total,
        "players": players,
        "evidence": evidence,
        "available_metrics": available_metrics,
    }
