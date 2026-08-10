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
        if isinstance(val, (np.integer, int)):
            return int(val)
        if isinstance(val, (np.floating, float)):
            return float(val) if not np.isnan(val) else None
        if isinstance(val, np.bool_):
            return bool(val)
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

            df_kills = self._parse_event("player_death", player=["X", "Y", "Z"])
            df_blind = self._parse_event("player_blind")
            df_bomb = self._parse_event("bomb_planted")
            
            df_smokes = self._parse_event("smokegrenade_detonate", player=["X", "Y", "Z"])
            df_inferno = self._parse_event("inferno_startfire", player=["X", "Y", "Z"])
            df_he = self._parse_event("hegrenade_detonate", player=["X", "Y", "Z"])

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
                    "winner": str(round_row.get("winner", "Unknown")),
                    "reason": str(round_row.get("reason", "Unknown")),
                    "kills": [],
                    "grenades": [],
                    "flash_blinds": [],
                    "plants": []
                }
                
                if not df_kills.empty and 'tick' in df_kills.columns:
                    kills_in_round = df_kills[(df_kills['tick'] > prev_tick) & (df_kills['tick'] <= current_tick)]
                    if not kills_in_round.empty:
                        first_kill_tick = kills_in_round['tick'].min()
                        for _, kill in kills_in_round.iterrows():
                            round_detail["kills"].append({
                                "tick": self._safe_convert(kill.get("tick")),
                                "killer": str(kill.get("attacker_name", "Environment")),
                                "victim": str(kill.get("user_name", "Unknown")),
                                "weapon": str(kill.get("weapon", "Unknown")),
                                "is_headshot": self._safe_convert(kill.get("headshot")),
                                "is_first_kill": self._safe_convert(kill.get("tick") == first_kill_tick),
                                "location": {
                                    "victim_xyz": [self._safe_convert(kill.get("user_X")), self._safe_convert(kill.get("user_Y")), self._safe_convert(kill.get("user_Z"))],
                                    "killer_xyz": [self._safe_convert(kill.get("attacker_X")), self._safe_convert(kill.get("attacker_Y")), self._safe_convert(kill.get("attacker_Z"))]
                                }
                            })

                for nade_type, df_nade in [("Smoke", df_smokes), ("Molotov/Incendiary", df_inferno), ("HE", df_he)]:
                    if not df_nade.empty and 'tick' in df_nade.columns:
                        nades_in_round = df_nade[(df_nade['tick'] > prev_tick) & (df_nade['tick'] <= current_tick)]
                        for _, nade in nades_in_round.iterrows():
                            round_detail["grenades"].append({
                                "tick": self._safe_convert(nade.get("tick")),
                                "type": nade_type,
                                "thrower": str(nade.get("user_name", "Unknown")),
                                "detonation_xyz": [self._safe_convert(nade.get("user_X")), self._safe_convert(nade.get("user_Y")), self._safe_convert(nade.get("user_Z"))]
                            })

                if not df_blind.empty and 'tick' in df_blind.columns:
                    blinds_in_round = df_blind[(df_blind['tick'] > prev_tick) & (df_blind['tick'] <= current_tick)]
                    for _, blind in blinds_in_round.iterrows():
                        round_detail["flash_blinds"].append({
                            "tick": self._safe_convert(blind.get("tick")),
                            "victim": str(blind.get("user_name", "Unknown")),
                            "attacker": str(blind.get("attacker_name", "Unknown")),
                            "blind_duration": self._safe_convert(blind.get("blind_duration", 0.0))
                        })

                if not df_bomb.empty and 'tick' in df_bomb.columns:
                    plants_in_round = df_bomb[(df_bomb['tick'] > prev_tick) & (df_bomb['tick'] <= current_tick)]
                    for _, plant in plants_in_round.iterrows():
                        round_detail["plants"].append({
                            "tick": self._safe_convert(plant.get("tick")),
                            "planter": str(plant.get("user_name", "Unknown")),
                            "site": str(plant.get("site", "Unknown"))
                        })

                match_data["rounds"].append(round_detail)
                logger.info(f"✅ 第 {round_idx} 回合战术切片组装完毕 | 记录了 {len(round_detail['kills'])} 次击杀 & {len(round_detail['grenades'])} 次道具施放。")
                round_idx += 1

            return match_data

        except Exception as e:
            logger.error(f"解析过程中发生致命错误: {str(e)}")
            logger.error(traceback.format_exc())
            return {}
