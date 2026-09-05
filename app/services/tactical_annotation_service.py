"""Deterministic and weakly supervised labels for parsed CS2 rounds."""

from collections import Counter, defaultdict
from statistics import fmean
from typing import Any

from app.domain.tactical_models import CanonicalEvent, RoundAnnotation, TacticalLabel

RULE_VERSION = "silver-v0.1"
MAP_NAMES = {"de_cache": "Cache", "de_dust2": "Dust2", "de_nuke": "Nuke"}


def _text(value: Any) -> str | None:
    if value is None or str(value) in {"", "None", "nan", "Unknown"}:
        return None
    return str(value)


def _side(value: Any) -> str | None:
    side = _text(value)
    return {"TERRORIST": "T", "COUNTERTERRORIST": "CT"}.get(side or "", side)


def _steamid(value: Any) -> str | None:
    player_id = _text(value)
    return player_id if player_id not in {"0"} else None


def _tick(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _position(value: Any) -> list[float | None] | None:
    if not isinstance(value, list) or len(value) != 3:
        return None
    result = [float(item) if item is not None else None for item in value]
    return result if any(item is not None for item in result) else None


def _site(value: Any) -> str | None:
    site = _text(value)
    if site in {"BombsiteA", "BombSiteA"}:
        return "A"
    if site in {"BombsiteB", "BombSiteB"}:
        return "B"
    return site if site and not site.isdigit() else None


def _event_id(match_id: str, map_name: str, round_number: int, kind: str, index: int) -> str:
    return f"{match_id}:{map_name}:{round_number}:{kind}:{index}"


def _canonical_events(match_id: str, map_name: str, round_data: dict) -> list[CanonicalEvent]:
    round_number = int(round_data.get("round_number", 0))
    events: list[CanonicalEvent] = []

    for index, kill in enumerate(round_data.get("kills", []), start=1):
        events.append(CanonicalEvent(
            event_id=_event_id(match_id, map_name, round_number, "kill", index),
            tick=_tick(kill.get("tick")),
            event_type="kill",
            subtype=_text(kill.get("weapon")),
            actor_steamid=_steamid(kill.get("killer_steamid")),
            actor_name=_text(kill.get("killer")),
            actor_team=_text(kill.get("killer_team")),
            actor_side=_side(kill.get("killer_side")),
            actor_area=_text(kill.get("killer_area")),
            target_steamid=_steamid(kill.get("victim_steamid")),
            target_name=_text(kill.get("victim")),
            target_team=_text(kill.get("victim_team")),
            target_side=_side(kill.get("victim_side")),
            target_area=_text(kill.get("victim_area")),
            assister_steamid=_steamid(kill.get("assister_steamid")),
            position=_position(kill.get("location", {}).get("victim_xyz")),
            origin_position=_position(kill.get("location", {}).get("killer_xyz")),
            details={
                "is_first_kill": bool(kill.get("is_first_kill")),
                "is_headshot": bool(kill.get("is_headshot")),
                "assisted_flash": bool(kill.get("assisted_flash")),
                "through_smoke": bool(kill.get("through_smoke")),
            },
        ))

    for index, grenade in enumerate(round_data.get("grenades", []), start=1):
        events.append(CanonicalEvent(
            event_id=_event_id(match_id, map_name, round_number, "grenade", index),
            tick=_tick(grenade.get("tick")),
            event_type="grenade",
            subtype=_text(grenade.get("type")),
            actor_steamid=_steamid(grenade.get("thrower_steamid")),
            actor_name=_text(grenade.get("thrower")),
            actor_team=_text(grenade.get("thrower_team")),
            actor_side=_side(grenade.get("thrower_side")),
            actor_area=_text(grenade.get("thrower_area")),
            position=_position(grenade.get("detonation_xyz")),
            origin_position=_position(grenade.get("thrower_xyz")),
        ))

    for index, plant in enumerate(round_data.get("plants", []), start=1):
        raw_site = _text(plant.get("site"))
        events.append(CanonicalEvent(
            event_id=_event_id(match_id, map_name, round_number, "plant", index),
            tick=_tick(plant.get("tick")),
            event_type="bomb_plant",
            actor_steamid=_steamid(plant.get("planter_steamid")),
            actor_name=_text(plant.get("planter")),
            actor_team=_text(plant.get("planter_team")),
            actor_side=_side(plant.get("planter_side")),
            actor_area=_text(plant.get("planter_area")),
            site=_site(raw_site),
            position=_position(plant.get("position")),
            details={"site_entity_id": plant.get("site_entity_id")},
        ))

    for index, blind in enumerate(round_data.get("flash_blinds", []), start=1):
        events.append(CanonicalEvent(
            event_id=_event_id(match_id, map_name, round_number, "blind", index),
            tick=_tick(blind.get("tick")),
            event_type="flash_blind",
            actor_steamid=_steamid(blind.get("attacker_steamid")),
            actor_name=_text(blind.get("attacker")),
            target_steamid=_steamid(blind.get("victim_steamid")),
            target_name=_text(blind.get("victim")),
            details={"blind_duration": blind.get("blind_duration")},
        ))

    return sorted(events, key=lambda event: (event.tick, event.event_id))


def _participants(events: list[CanonicalEvent]) -> list[str]:
    return sorted({
        player_id
        for event in events
        for player_id in (event.actor_steamid, event.target_steamid, event.assister_steamid)
        if player_id
    })


def _opening_label(events: list[CanonicalEvent], prefix: str) -> TacticalLabel | None:
    kills = [event for event in events if event.event_type == "kill"]
    if not kills:
        return None
    opening = next((event for event in kills if event.details.get("is_first_kill")), kills[0])
    return TacticalLabel(
        label_id=f"{prefix}:opening",
        label_type="OPENING_DUEL",
        team=opening.actor_team,
        start_tick=opening.tick,
        end_tick=opening.tick,
        participant_ids=_participants([opening]),
        evidence_event_ids=[opening.event_id],
        label_source="event_fact",
        rule_version=RULE_VERSION,
        confidence=1.0,
        review_status="auto_accepted",
        details={"winner_steamid": opening.actor_steamid, "loser_steamid": opening.target_steamid},
    )


def _trade_labels(events: list[CanonicalEvent], prefix: str, window_ticks: int) -> list[TacticalLabel]:
    kills = [event for event in events if event.event_type == "kill"]
    labels = []
    for death in kills:
        if not death.actor_steamid or not death.target_steamid:
            continue
        for trade in kills:
            delay = trade.tick - death.tick
            if delay <= 0:
                continue
            if delay > window_ticks:
                break
            same_team = bool(
                (trade.actor_team and death.target_team and trade.actor_team == death.target_team)
                or (trade.actor_side and death.target_side and trade.actor_side == death.target_side)
            )
            if trade.target_steamid == death.actor_steamid and same_team:
                labels.append(TacticalLabel(
                    label_id=f"{prefix}:trade:{len(labels) + 1}",
                    label_type="TRADE_KILL",
                    team=trade.actor_team,
                    start_tick=death.tick,
                    end_tick=trade.tick,
                    participant_ids=_participants([death, trade]),
                    evidence_event_ids=[death.event_id, trade.event_id],
                    label_source="deterministic_rule",
                    rule_version=RULE_VERSION,
                    confidence=1.0,
                    review_status="auto_accepted",
                    details={
                        "traded_player_steamid": death.target_steamid,
                        "trader_steamid": trade.actor_steamid,
                        "response_ticks": delay,
                    },
                ))
                break
    return labels


def _execute_labels(
    events: list[CanonicalEvent], prefix: str, execute_window_ticks: int, followup_window_ticks: int,
) -> list[TacticalLabel]:
    grenades_by_team: dict[str, list[CanonicalEvent]] = defaultdict(list)
    for event in events:
        if event.event_type == "grenade" and event.actor_team:
            grenades_by_team[event.actor_team].append(event)

    labels = []
    for team, grenades in sorted(grenades_by_team.items()):
        best: list[CanonicalEvent] = []
        for index, first in enumerate(grenades):
            cluster = [event for event in grenades[index:] if event.tick - first.tick <= execute_window_ticks]
            if len(cluster) > len(best):
                best = cluster
        if len(best) < 2:
            continue

        last_tick = best[-1].tick
        followup_kills = [
            event for event in events
            if last_tick <= event.tick <= last_tick + followup_window_ticks
            and event.actor_team == team
            and event.event_type == "kill"
        ]
        plant = next((
            event for event in events
            if event.event_type == "bomb_plant" and event.actor_team == team
            and last_tick <= event.tick <= last_tick + 3 * followup_window_ticks
        ), None)
        evidence = best + followup_kills + ([plant] if plant else [])
        side = next((event.actor_side for event in best if event.actor_side), None)
        common = {
            "utility_count": len(best),
            "utility_types": dict(Counter(event.subtype for event in best if event.subtype)),
            "has_followup_kill": bool(followup_kills),
            "has_plant": bool(plant),
            "side": side,
        }
        labels.append(TacticalLabel(
            label_id=f"{prefix}:utility-burst:{len(labels) + 1}",
            label_type="UTILITY_BURST",
            team=team,
            site=plant.site if plant else None,
            start_tick=best[0].tick,
            end_tick=best[-1].tick,
            participant_ids=_participants(best),
            evidence_event_ids=[event.event_id for event in best],
            label_source="deterministic_rule",
            rule_version=RULE_VERSION,
            confidence=1.0,
            review_status="auto_accepted",
            details=common,
        ))
        if side == "T" and plant and followup_kills:
            labels.append(TacticalLabel(
                label_id=f"{prefix}:execute:{len(labels) + 1}",
                label_type="EXECUTE_CANDIDATE",
                team=team,
                site=plant.site,
                start_tick=best[0].tick,
                end_tick=plant.tick,
                participant_ids=_participants(evidence),
                evidence_event_ids=[event.event_id for event in evidence],
                label_source="weak_rule",
                rule_version=RULE_VERSION,
                confidence=0.85,
                review_status="auto_accepted",
                details=common,
            ))
    return labels


def _post_plant_labels(events: list[CanonicalEvent], prefix: str, round_end_tick: int) -> list[TacticalLabel]:
    labels = []
    for plant in (event for event in events if event.event_type == "bomb_plant"):
        labels.append(TacticalLabel(
            label_id=f"{prefix}:postplant:{len(labels) + 1}",
            label_type="POST_PLANT",
            team=plant.actor_team,
            site=plant.site,
            start_tick=plant.tick,
            end_tick=round_end_tick,
            participant_ids=_participants([plant]),
            evidence_event_ids=[plant.event_id],
            label_source="event_fact",
            rule_version=RULE_VERSION,
            confidence=1.0,
            review_status="auto_accepted",
        ))
        contacts = [
            event for event in events
            if event.event_type == "kill" and event.tick > plant.tick
            and event.actor_side == "CT" and event.target_side == "T"
        ]
        if contacts:
            contact = contacts[0]
            labels.append(TacticalLabel(
                label_id=f"{prefix}:retake-contact:{len(labels)}",
                label_type="RETAKE_CONTACT",
                team=contact.actor_team,
                site=plant.site,
                start_tick=plant.tick,
                end_tick=contact.tick,
                participant_ids=_participants([plant, contact]),
                evidence_event_ids=[plant.event_id, contact.event_id],
                label_source="deterministic_rule",
                rule_version=RULE_VERSION,
                confidence=1.0,
                review_status="auto_accepted",
                details={"scope": "contact only; does not claim a full retake attempt"},
            ))
    return labels


def annotate_match(
    parsed: dict,
    *,
    source_demo: str,
    match_id: str | None = None,
    source_match_url: str | None = None,
    tick_rate: int = 64,
) -> list[dict]:
    """Return JSON-serializable silver annotations for every parsed round."""
    resolved_match_id = match_id or str(parsed.get("match_id") or source_demo)
    raw_map = str(parsed.get("map_name") or "Unknown")
    map_name = MAP_NAMES.get(raw_map.lower(), raw_map.removeprefix("de_").title())
    records = []
    for round_data in parsed.get("rounds", []):
        round_number = int(round_data.get("round_number", 0))
        prefix = f"{resolved_match_id}:{map_name}:{round_number}"
        events = _canonical_events(resolved_match_id, map_name, round_data)
        end_tick = _tick(round_data.get("end_tick")) or max(
            [event.tick for event in events] + [_tick(round_data.get("start_tick"))]
        )
        labels: list[TacticalLabel] = []
        opening = _opening_label(events, prefix)
        if opening:
            labels.append(opening)
        labels.extend(_trade_labels(events, prefix, 5 * tick_rate))
        labels.extend(_execute_labels(events, prefix, 8 * tick_rate, 10 * tick_rate))
        labels.extend(_post_plant_labels(events, prefix, end_tick))
        record = RoundAnnotation(
            match_id=resolved_match_id,
            map_name=map_name,
            round_number=round_number,
            source_demo=source_demo,
            source_match_url=source_match_url,
            tick_rate=tick_rate,
            start_tick=_tick(round_data.get("start_tick")),
            freeze_end_tick=(
                _tick(round_data.get("freeze_end_tick"))
                if round_data.get("freeze_end_tick") is not None else None
            ),
            end_tick=end_tick,
            winner=_text(round_data.get("winner")),
            reason=_text(round_data.get("reason")),
            events=events,
            labels=labels,
        )
        records.append(record.model_dump(mode="json"))
    return records


def summarize_annotations(records: list[dict]) -> dict:
    """Produce a transparent quality summary without pretending silver labels are gold."""
    events = [event for record in records for event in record.get("events", [])]
    labels = [label for record in records for label in record.get("labels", [])]
    player_slots = [event.get("actor_steamid") for event in events]
    player_slots.extend(
        event.get("target_steamid") for event in events if event.get("event_type") == "kill"
    )
    actor_events = [
        event for event in events
        if event.get("event_type") in {"kill", "grenade", "bomb_plant"}
    ]
    plant_events = [event for event in events if event.get("event_type") == "bomb_plant"]
    confidences = [float(label.get("confidence", 0.0)) for label in labels]
    missing_evidence_refs = 0
    duplicate_event_ids = 0
    tick_boundary_violations = 0
    for record in records:
        event_ids = [event.get("event_id") for event in record.get("events", [])]
        event_id_set = set(event_ids)
        duplicate_event_ids += len(event_ids) - len(event_id_set)
        missing_evidence_refs += sum(
            not set(label.get("evidence_event_ids", [])).issubset(event_id_set)
            for label in record.get("labels", [])
        )
        tick_boundary_violations += sum(
            not record.get("start_tick", 0) < event.get("tick", 0) <= record.get("end_tick", 0)
            for event in record.get("events", [])
        )
    return {
        "schema_version": "0.1",
        "label_policy": "AI-assisted silver labels; not expert gold labels",
        "matches": len({record.get("match_id") for record in records}),
        "demos": len({record.get("source_demo") for record in records}),
        "maps": sorted({record.get("map_name") for record in records}),
        "rounds": len(records),
        "events": len(events),
        "labels": len(labels),
        "event_types": dict(sorted(Counter(event.get("event_type") for event in events).items())),
        "label_types": dict(sorted(Counter(label.get("label_type") for label in labels).items())),
        "label_sources": dict(sorted(Counter(label.get("label_source") for label in labels).items())),
        "review_statuses": dict(sorted(Counter(label.get("review_status") for label in labels).items())),
        "player_id_coverage": round(sum(bool(value) for value in player_slots) / len(player_slots), 4) if player_slots else 1.0,
        "actor_team_coverage": round(
            sum(bool(event.get("actor_team")) for event in actor_events) / len(actor_events), 4
        ) if actor_events else 1.0,
        "actor_area_coverage": round(
            sum(bool(event.get("actor_area")) for event in actor_events) / len(actor_events), 4
        ) if actor_events else 1.0,
        "bomb_site_coverage": round(
            sum(event.get("site") in {"A", "B"} for event in plant_events) / len(plant_events), 4
        ) if plant_events else 1.0,
        "mean_label_confidence": round(fmean(confidences), 4) if confidences else 0.0,
        "integrity": {
            "missing_evidence_refs": missing_evidence_refs,
            "duplicate_event_ids": duplicate_event_ids,
            "tick_boundary_violations": tick_boundary_violations,
        },
        "limitations": [
            "EXECUTE_CANDIDATE is a weak-rule label, not tactical-intent ground truth.",
            "Bomb sites use the parser's place name; the numeric entity identifier is retained for audit.",
            "UTILITY_BURST and RETAKE_CONTACT describe temporal patterns, not tactical intent or success.",
            "No missed-trade label is produced without player trajectory and opportunity evidence.",
        ],
    }
