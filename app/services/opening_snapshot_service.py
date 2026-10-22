"""Observation-only opening records; fixtures and raw snapshots are not tactical labels."""

import math

import pandas as pd


def _side(value) -> str | None:
    return {"CT": "CT", "COUNTERTERRORIST": "CT", "T": "T",
            "TERRORIST": "T"}.get(str(value).upper())


def build_opening_snapshots(windows: list[dict], frame: pd.DataFrame, seconds: tuple) -> list[dict]:
    records = []
    required = {"tick", "steamid", "team_name", "X", "Y", "Z", "health", "current_equip_value"}
    for window in windows:
        for side in ("CT", "T"):
            record = {key: window[key] for key in (
                "round_number", "start_tick", "freeze_end_tick", "end_tick"
            )}
            record.update(side=side, status="insufficient_data", reason=None, snapshots=[])
            records.append(record)
            freeze = window["freeze_end_tick"]
            if freeze is None:
                record["reason"] = "missing_freeze_end"
                continue
            if freeze + max(seconds) * 64 > window["end_tick"]:
                record["reason"] = "round_ended_before_final_snapshot"
                continue
            roster = [p for p in window.get("participants", []) if p["side"] == side]
            expected = {str(p["steamid"]) for p in roster}
            if len(expected) != 5 or not window.get("participants_complete"):
                record["reason"] = "incomplete_freeze_roster"
                continue
            teams = {p.get("team") for p in roster if p.get("team")}
            if len(teams) != 1:
                record["reason"] = "ambiguous_team"
                continue
            record["team"] = next(iter(teams))
            if not required.issubset(frame.columns):
                record["reason"] = "missing_tick_fields"
                continue
            snapshots = []
            for second in seconds:
                tick = freeze + second * 64
                rows = frame[(frame["tick"] == tick) & (frame["team_name"].map(_side) == side)]
                ids = rows["steamid"].map(str)
                if len(rows) != 5 or set(ids) != expected:
                    record["reason"] = "snapshot_roster_mismatch"
                    break
                players = []
                for _, row in rows.assign(_id=ids).sort_values("_id").iterrows():
                    try:
                        values = [float(row[key]) for key in (
                            "X", "Y", "Z", "health", "current_equip_value"
                        )]
                    except (ValueError, TypeError):
                        record["reason"] = "invalid_player_state"
                        break
                    if not all(math.isfinite(v) for v in values) or not 0 <= values[3] <= 100 or values[4] < 0:
                        record["reason"] = "invalid_player_state"
                        break
                    place = row.get("last_place_name")
                    players.append({
                        "steamid": str(row["steamid"]),
                        "position": values[:3], "health": values[3],
                        "equipment_value": values[4], "alive": values[3] > 0,
                        "place": str(place) if pd.notna(place) and str(place).strip() else None,
                    })
                if record["reason"]:
                    break
                snapshots.append({"second": second, "tick": tick, "players": players})
            if record["reason"] is None:
                record.update(status="ok", snapshots=snapshots,
                              missing_place_count=sum(p["place"] is None for s in snapshots for p in s["players"]))
    return records
