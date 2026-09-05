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

    def parse_to_dict(self) -> dict:
        if not self.parser:
            logger.error("解析引擎空转，因为并未成功持有一个真实的 .dem 文件句柄。")
            return {}

        logger.info(f"🚀 核心解析引擎已挂载！开始切入 Demo: {self.demo_path}")
        
        try:
            df_rounds_end = self._parse_event("round_end")
            if "round" in df_rounds_end.columns:
                df_rounds_end = df_rounds_end[df_rounds_end["round"] > 0].reset_index(drop=True)
            if df_rounds_end.empty:
                logger.warning("并未捕获到有效回合数据，文件可能已损坏。")
                return {}

            player_fields = ["X", "Y", "Z", "team_name", "team_clan_name", "last_place_name"]
            df_kills = self._parse_event("player_death", player=player_fields)
            df_blind = self._parse_event("player_blind")
            df_bomb = self._parse_event("bomb_planted", player=player_fields)
            df_freeze_end = self._parse_event("round_freeze_end")
            
            df_smokes = self._parse_event("smokegrenade_detonate", player=player_fields)
            df_flashes = self._parse_event("flashbang_detonate", player=player_fields)
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

                if not df_freeze_end.empty and "tick" in df_freeze_end.columns:
                    freeze_ticks = df_freeze_end[
                        (df_freeze_end["tick"] > prev_tick)
                        & (df_freeze_end["tick"] <= current_tick)
                    ]["tick"]
                    if not freeze_ticks.empty:
                        round_detail["freeze_end_tick"] = self._safe_convert(freeze_ticks.min())
                
                if not df_kills.empty and 'tick' in df_kills.columns:
                    kills_in_round = df_kills[(df_kills['tick'] > prev_tick) & (df_kills['tick'] <= current_tick)]
                    if not kills_in_round.empty:
                        first_kill_tick = kills_in_round['tick'].min()
                        for _, kill in kills_in_round.iterrows():
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
                        round_detail["flash_blinds"].append({
                            "tick": self._safe_convert(blind.get("tick")),
                            "victim": str(blind.get("user_name", "Unknown")),
                            "victim_steamid": self._safe_convert(blind.get("user_steamid")),
                            "attacker": str(blind.get("attacker_name", "Unknown")),
                            "attacker_steamid": self._safe_convert(blind.get("attacker_steamid")),
                            "blind_duration": self._safe_convert(blind.get("blind_duration", 0.0))
                        })

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
