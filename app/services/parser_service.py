import os
import json
import logging
import traceback
import numpy as np
import pandas as pd

from demoparser2 import DemoParser

logger = logging.getLogger(__name__)

class TacticalDemoParser:
    """
    全能且高阶的战术复盘 Demo 解析器。
    严格剔除了无意义的每秒全图移动帧追踪，专注于关键击杀链、投掷物落地和战术流转事件。
    """
    def __init__(self, demo_path: str):
        self.demo_path = demo_path
        self.parser = None
        
        if not os.path.exists(demo_path):
            logger.warning(f"Demo 文件尚未放置: {demo_path}")
        else:
            try:
                self.parser = DemoParser(demo_path)
            except Exception as e:
                logger.error(f"加载 Demo 库失败: {e}")

    def _safe_convert(self, val):
        """处理 NumPy 数据类型的 JSON 序列化兼容问题"""
        if isinstance(val, (np.bool_, bool)):
            return bool(val)
        if isinstance(val, (np.integer, int)):
            return int(val)
        if isinstance(val, (np.floating, float)):
            return float(val) if not np.isnan(val) else None
        return str(val) if val is not None else None

    def _parse_event(self, event_name: str, *, player=None, other=None) -> pd.DataFrame:
        """Read one event with demoparser2's current API.

        demoparser2 returns an empty list for events that do not occur in a
        demo, while populated events are returned as DataFrames. Normalizing
        both cases here keeps the rest of the pipeline format-independent.
        """
        if not self.parser:
            return pd.DataFrame()
        try:
            frame = self.parser.parse_event(event_name, player=player, other=other)
        except Exception as error:
            logger.warning("Unable to parse demo event %s: %s", event_name, error)
            return pd.DataFrame()
        return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()

    def _parse_ticks(self, wanted_props, ticks) -> pd.DataFrame:
        if not self.parser:
            return pd.DataFrame()
        try:
            frame = self.parser.parse_ticks(wanted_props, ticks=ticks)
        except Exception as error:
            logger.warning("Unable to parse demo ticks for flash recovery: %s", error)
            return pd.DataFrame()
        return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()

    @staticmethod
    def _number(value, default=0.0) -> float:
        try:
            result = float(value)
            return default if np.isnan(result) else result
        except (TypeError, ValueError):
            return default

    def _flash_blind_frame(self, native_blinds: pd.DataFrame, flashes: pd.DataFrame) -> pd.DataFrame:
        """Normalize native blind events or recover them from flash-duration deltas."""
        flashes_by_tick = {}
        if not flashes.empty and "tick" in flashes.columns:
            for tick, rows in flashes.groupby("tick"):
                flashes_by_tick[int(tick)] = [row for _, row in rows.iterrows()]

        records = []
        if not native_blinds.empty and "tick" in native_blinds.columns:
            for _, blind in native_blinds.iterrows():
                candidates = flashes_by_tick.get(int(blind.get("tick", 0)), [])
                flash = candidates[0] if len(candidates) == 1 else None
                records.append(self._flash_record(blind, flash, "player_blind"))
            return pd.DataFrame(records)

        if flashes.empty or "tick" not in flashes.columns:
            return pd.DataFrame()
        flash_ticks = sorted({int(tick) for tick in flashes["tick"]})
        wanted_ticks = sorted({tick + offset for tick in flash_ticks for offset in (-1, 0) if tick + offset >= 0})
        tick_frame = self._parse_ticks(
            [
                "flash_duration", "health", "team_name", "team_clan_name",
                "last_place_name", "X", "Y", "Z",
            ],
            wanted_ticks,
        )
        required = {"tick", "steamid", "name", "flash_duration"}
        if tick_frame.empty or not required.issubset(tick_frame.columns):
            return pd.DataFrame()
        rows = {
            (int(row.get("tick", 0)), str(row.get("steamid", ""))): row
            for _, row in tick_frame.iterrows()
        }
        for tick in flash_ticks:
            candidates = flashes_by_tick.get(tick, [])
            flash = candidates[0] if len(candidates) == 1 else None
            for (row_tick, steamid), current in rows.items():
                if row_tick != tick:
                    continue
                previous = rows.get((tick - 1, steamid))
                current_duration = self._number(current.get("flash_duration"))
                previous_duration = self._number(previous.get("flash_duration")) if previous is not None else 0.0
                if current_duration <= 0 or np.isclose(current_duration, previous_duration):
                    continue
                if "health" in current and self._number(current.get("health")) <= 0:
                    continue
                record = self._flash_record(
                    current,
                    flash,
                    "flash_duration_delta",
                    duration=current_duration,
                )
                if len(candidates) > 1:
                    candidate_records = [{
                        "name": str(candidate.get("user_name", "Unknown")),
                        "steamid": self._safe_convert(candidate.get("user_steamid")),
                        "team": self._safe_convert(candidate.get("user_team_clan_name")),
                        "side": self._safe_convert(candidate.get("user_team_name")),
                        "area": self._safe_convert(candidate.get("user_last_place_name")),
                        "flash_xyz": [
                            self._safe_convert(candidate.get("x")),
                            self._safe_convert(candidate.get("y")),
                            self._safe_convert(candidate.get("z")),
                        ],
                    } for candidate in candidates]
                    teams = {item["team"] for item in candidate_records if item["team"]}
                    sides = {item["side"] for item in candidate_records if item["side"]}
                    record.update({
                        "attacker": " / ".join(item["name"] for item in candidate_records),
                        "attacker_team": next(iter(teams)) if len(teams) == 1 else None,
                        "attacker_side": next(iter(sides)) if len(sides) == 1 else None,
                        "attribution": "simultaneous_flash_candidates",
                        "attacker_candidates": candidate_records,
                    })
                records.append(record)
        logger.info(
            "Recovered %s flash-blind events from %s flash detonations",
            len(records),
            len(flash_ticks),
        )
        return pd.DataFrame(records)

    def _flash_record(self, victim, flash, source: str, duration=None) -> dict:
        if flash is not None:
            attacker_name = flash.get("user_name", "Unknown")
            attacker_steamid = flash.get("user_steamid")
            attacker_team = flash.get("user_team_clan_name")
            attacker_side = flash.get("user_team_name")
            attacker_area = flash.get("user_last_place_name")
            flash_xyz = [flash.get("x"), flash.get("y"), flash.get("z")]
        else:
            attacker_name = victim.get("attacker_name", "Unknown")
            attacker_steamid = victim.get("attacker_steamid")
            attacker_team = victim.get("attacker_team_clan_name")
            attacker_side = victim.get("attacker_team_name")
            attacker_area = victim.get("attacker_last_place_name")
            flash_xyz = [None, None, None]
        return {
            "tick": self._safe_convert(victim.get("tick")),
            "victim": str(victim.get("user_name", victim.get("name", "Unknown"))),
            "victim_steamid": self._safe_convert(victim.get("user_steamid", victim.get("steamid"))),
            "victim_team": self._safe_convert(victim.get("user_team_clan_name", victim.get("team_clan_name"))),
            "victim_side": self._safe_convert(victim.get("user_team_name", victim.get("team_name"))),
            "victim_area": self._safe_convert(victim.get("user_last_place_name", victim.get("last_place_name"))),
            "attacker": str(attacker_name),
            "attacker_steamid": self._safe_convert(attacker_steamid),
            "attacker_team": self._safe_convert(attacker_team),
            "attacker_side": self._safe_convert(attacker_side),
            "attacker_area": self._safe_convert(attacker_area),
            "blind_duration": self._safe_convert(
                duration if duration is not None else victim.get("blind_duration", 0.0)
            ),
            "victim_xyz": [
                self._safe_convert(victim.get("user_X", victim.get("X"))),
                self._safe_convert(victim.get("user_Y", victim.get("Y"))),
                self._safe_convert(victim.get("user_Z", victim.get("Z"))),
            ],
            "flash_xyz": [self._safe_convert(value) for value in flash_xyz],
            "source": source,
        }

    @staticmethod
    def _is_combat_kill(kill) -> bool:
        attacker = str(kill.get("attacker_name") or "")
        victim = str(kill.get("user_name") or "")
        weapon = str(kill.get("weapon") or "").lower()
        attacker_team = str(kill.get("attacker_team_clan_name") or "")
        victim_team = str(kill.get("user_team_clan_name") or "")
        return bool(
            attacker and victim and attacker != victim and weapon != "world"
            and not (attacker_team and victim_team and attacker_team == victim_team)
        )

    def parse_round_rosters(self, round_ends=None, freeze_ends=None) -> dict:
        """Capture the active roster at freeze end; incomplete snapshots stay explicit."""
        ends = self._parse_event("round_end") if round_ends is None else round_ends.copy()
        freezes = self._parse_event("round_freeze_end") if freeze_ends is None else freeze_ends
        if "round" in ends:
            ends = ends[ends["round"] > 0]
        if "winner" in ends:
            ends = ends[ends["winner"].notna()]
        if ends.empty or "tick" not in ends:
            return {}
        round_ticks = {}
        previous = 0
        for number, end_tick in enumerate(ends["tick"], 1):
            choices = freezes[(freezes["tick"] > previous) & (freezes["tick"] <= end_tick)]["tick"] if "tick" in freezes else []
            round_ticks[number] = int(min(choices)) if len(choices) else None
            previous = end_tick
        ticks = sorted({tick for tick in round_ticks.values() if tick is not None})
        frame = self._parse_ticks(["team_name", "team_clan_name"], ticks) if ticks else pd.DataFrame()
        result = {}
        for number, tick in round_ticks.items():
            participants = {}
            rows = frame[frame["tick"] == tick] if "tick" in frame and tick is not None else pd.DataFrame()
            for _, row in rows.iterrows():
                side = {"TERRORIST": "T", "T": "T", "CT": "CT", "COUNTERTERRORIST": "CT"}.get(str(row.get("team_name", "")).upper())
                steamid = self._safe_convert(row.get("steamid"))
                if side and steamid and str(steamid) not in {"0", "nan"}:
                    participants[str(steamid)] = {
                        "steamid": str(steamid), "name": self._safe_convert(row.get("name")),
                        "team": self._safe_convert(row.get("team_clan_name")), "side": side,
                    }
            roster = list(participants.values())
            complete = len(roster) == 10 and all(sum(p["side"] == side for p in roster) == 5 for side in ("T", "CT"))
            result[number] = {"participants": roster, "participants_complete": complete, "roster_tick": tick}
        return result

    def parse_to_dict(self) -> dict:
        if not self.parser:
            logger.error("解析引擎空转，因为并未成功持有一个真实的 .dem 文件句柄。")
            return {}

        logger.info(f"🚀 核心解析引擎已挂载！开始切入 Demo: {self.demo_path}")
        
        try:
            df_rounds_end = self._parse_event("round_end")
            if "round" in df_rounds_end.columns:
                df_rounds_end = df_rounds_end[df_rounds_end["round"] > 0].reset_index(drop=True)
            if "winner" in df_rounds_end.columns:
                df_rounds_end = df_rounds_end[df_rounds_end["winner"].notna()].reset_index(drop=True)
            if df_rounds_end.empty:
                logger.warning("并未捕获到有效回合数据，文件可能已损坏。")
                return {}

            player_fields = ["X", "Y", "Z", "team_name", "team_clan_name", "last_place_name"]
            df_kills = self._parse_event("player_death", player=player_fields)
            df_bomb = self._parse_event("bomb_planted", player=player_fields)
            df_freeze_end = self._parse_event("round_freeze_end")
            
            df_smokes = self._parse_event("smokegrenade_detonate", player=player_fields)
            df_flashes = self._parse_event("flashbang_detonate", player=player_fields)
            df_blind = self._flash_blind_frame(
                self._parse_event("player_blind", player=player_fields),
                df_flashes,
            )
            df_inferno = self._parse_event("inferno_startburn", player=player_fields)
            if df_inferno.empty:
                df_inferno = self._parse_event("inferno_startfire", player=player_fields)
            df_he = self._parse_event("hegrenade_detonate", player=player_fields)

            try:
                map_name = self.parser.parse_header().get('map_name', 'Unknown')
            except:
                map_name = "Unknown"
                
            match_data = {
                "match_id": os.path.basename(self.demo_path).split('.')[0],
                "map_name": map_name,
                "rounds": []
            }

            logger.info(f"=== 地图识别完毕: [{map_name}], 共探测到 {len(df_rounds_end)} 个有效回合 ===")

            rosters = self.parse_round_rosters(df_rounds_end, df_freeze_end)
            round_idx = 1
            for position, (_, round_row) in enumerate(df_rounds_end.iterrows()):
                current_tick = round_row.get("tick", 0)
                prev_tick = df_rounds_end.iloc[position - 1]["tick"] if position > 0 else 0
                
                round_detail = {
                    "round_number": round_idx,
                    "start_tick": self._safe_convert(prev_tick),
                    "freeze_end_tick": None,
                    "end_tick": self._safe_convert(current_tick),
                    "winner": str(round_row.get("winner", "Unknown")),
                    "reason": str(round_row.get("reason", "Unknown")),
                    "kills": [],
                    "grenades": [],
                    "flash_blinds": [],
                    "plants": []
                }

                round_detail.update(rosters.get(round_idx, {}))
                if not df_freeze_end.empty and "tick" in df_freeze_end.columns:
                    freeze_ticks = df_freeze_end[
                        (df_freeze_end["tick"] > prev_tick)
                        & (df_freeze_end["tick"] <= current_tick)
                    ]["tick"]
                    if not freeze_ticks.empty:
                        round_detail["freeze_end_tick"] = self._safe_convert(freeze_ticks.min())
                
                if not df_kills.empty and 'tick' in df_kills.columns:
                    kills_in_round = df_kills[(df_kills['tick'] > prev_tick) & (df_kills['tick'] <= current_tick)]
                    combat_kills = [kill for _, kill in kills_in_round.iterrows() if self._is_combat_kill(kill)]
                    if combat_kills:
                        first_kill_tick = min(kill.get("tick") for kill in combat_kills)
                        for kill in combat_kills:
                            round_detail["kills"].append({
                                "tick": self._safe_convert(kill.get("tick")),
                                "killer": str(kill.get("attacker_name", "Environment")),
                                "killer_steamid": self._safe_convert(kill.get("attacker_steamid")),
                                "killer_team": self._safe_convert(kill.get("attacker_team_clan_name")),
                                "killer_side": self._safe_convert(kill.get("attacker_team_name")),
                                "killer_area": self._safe_convert(kill.get("attacker_last_place_name")),
                                "victim": str(kill.get("user_name", "Unknown")),
                                "victim_steamid": self._safe_convert(kill.get("user_steamid")),
                                "victim_team": self._safe_convert(kill.get("user_team_clan_name")),
                                "victim_side": self._safe_convert(kill.get("user_team_name")),
                                "victim_area": self._safe_convert(kill.get("user_last_place_name")),
                                "assister": str(kill.get("assister_name", "Unknown")),
                                "assister_steamid": self._safe_convert(kill.get("assister_steamid")),
                                "assister_team": self._safe_convert(kill.get("assister_team_clan_name")),
                                "assister_side": self._safe_convert(kill.get("assister_team_name")),
                                "assisted_flash": self._safe_convert(kill.get("assistedflash", False)),
                                "distance": self._safe_convert(kill.get("distance")),
                                "through_smoke": self._safe_convert(kill.get("thrusmoke", False)),
                                "attacker_blind": self._safe_convert(kill.get("attackerblind", False)),
                                "weapon": str(kill.get("weapon", "Unknown")),
                                "is_headshot": self._safe_convert(kill.get("headshot")),
                                "is_first_kill": self._safe_convert(kill.get("tick") == first_kill_tick),
                                "location": {
                                    "victim_xyz": [self._safe_convert(kill.get("user_X")), self._safe_convert(kill.get("user_Y")), self._safe_convert(kill.get("user_Z"))],
                                    "killer_xyz": [self._safe_convert(kill.get("attacker_X")), self._safe_convert(kill.get("attacker_Y")), self._safe_convert(kill.get("attacker_Z"))]
                                }
                            })

                for nade_type, df_nade in [
                    ("Smoke", df_smokes),
                    ("Flash", df_flashes),
                    ("Molotov/Incendiary", df_inferno),
                    ("HE", df_he),
                ]:
                    if not df_nade.empty and 'tick' in df_nade.columns:
                        nades_in_round = df_nade[(df_nade['tick'] > prev_tick) & (df_nade['tick'] <= current_tick)]
                        for _, nade in nades_in_round.iterrows():
                            round_detail["grenades"].append({
                                "tick": self._safe_convert(nade.get("tick")),
                                "type": nade_type,
                                "thrower": str(nade.get("user_name", "Unknown")),
                                "thrower_steamid": self._safe_convert(nade.get("user_steamid")),
                                "thrower_team": self._safe_convert(nade.get("user_team_clan_name")),
                                "thrower_side": self._safe_convert(nade.get("user_team_name")),
                                "thrower_area": self._safe_convert(nade.get("user_last_place_name")),
                                "thrower_xyz": [self._safe_convert(nade.get("user_X")), self._safe_convert(nade.get("user_Y")), self._safe_convert(nade.get("user_Z"))],
                                "detonation_xyz": [self._safe_convert(nade.get("x", nade.get("user_X"))), self._safe_convert(nade.get("y", nade.get("user_Y"))), self._safe_convert(nade.get("z", nade.get("user_Z")))]
                            })

                if not df_blind.empty and 'tick' in df_blind.columns:
                    blinds_in_round = df_blind[(df_blind['tick'] > prev_tick) & (df_blind['tick'] <= current_tick)]
                    for _, blind in blinds_in_round.iterrows():
                        flash_blind = {
                            "tick": self._safe_convert(blind.get("tick")),
                            "victim": str(blind.get("victim", "Unknown")),
                            "victim_steamid": self._safe_convert(blind.get("victim_steamid")),
                            "victim_team": self._safe_convert(blind.get("victim_team")),
                            "victim_side": self._safe_convert(blind.get("victim_side")),
                            "victim_area": self._safe_convert(blind.get("victim_area")),
                            "attacker": str(blind.get("attacker", "Unknown")),
                            "attacker_steamid": self._safe_convert(blind.get("attacker_steamid")),
                            "attacker_team": self._safe_convert(blind.get("attacker_team")),
                            "attacker_side": self._safe_convert(blind.get("attacker_side")),
                            "attacker_area": self._safe_convert(blind.get("attacker_area")),
                            "blind_duration": self._safe_convert(blind.get("blind_duration", 0.0)),
                            "victim_xyz": blind.get("victim_xyz", [None, None, None]),
                            "flash_xyz": blind.get("flash_xyz", [None, None, None]),
                            "source": str(blind.get("source", "player_blind")),
                        }
                        if blind.get("attribution"):
                            flash_blind["attribution"] = str(blind.get("attribution"))
                            flash_blind["attacker_candidates"] = blind.get("attacker_candidates", [])
                        round_detail["flash_blinds"].append(flash_blind)

                if not df_bomb.empty and 'tick' in df_bomb.columns:
                    plants_in_round = df_bomb[(df_bomb['tick'] > prev_tick) & (df_bomb['tick'] <= current_tick)]
                    for _, plant in plants_in_round.iterrows():
                        round_detail["plants"].append({
                            "tick": self._safe_convert(plant.get("tick")),
                            "planter": str(plant.get("user_name", "Unknown")),
                            "planter_steamid": self._safe_convert(plant.get("user_steamid")),
                            "planter_team": self._safe_convert(plant.get("user_team_clan_name")),
                            "planter_side": self._safe_convert(plant.get("user_team_name")),
                            "planter_area": self._safe_convert(plant.get("user_last_place_name")),
                            "position": [self._safe_convert(plant.get("user_X")), self._safe_convert(plant.get("user_Y")), self._safe_convert(plant.get("user_Z"))],
                            "site": str(plant.get("user_last_place_name") or plant.get("site", "Unknown")),
                            "site_entity_id": self._safe_convert(plant.get("site")),
                        })

                match_data["rounds"].append(round_detail)
                logger.info(f"✅ 第 {round_idx} 回合战术切片组装完毕 | 记录了 {len(round_detail['kills'])} 次击杀 & {len(round_detail['grenades'])} 次道具施放。")
                round_idx += 1

            return match_data

        except Exception as e:
            logger.error(f"解析过程中发生致命错误: {str(e)}")
            logger.error(traceback.format_exc())
            return {}
