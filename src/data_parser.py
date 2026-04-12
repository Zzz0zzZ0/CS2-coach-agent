import os
import json
import logging
import traceback
from collections import defaultdict
import numpy as np
import pandas as pd

# AWPy v2.x 原生引入，基于极速的 demoparser2 底层
from awpy import Demo
from demoparser2 import DemoParser

# ==========================================
# 生产级日志与环境准备
# ==========================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
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
                # 显式使用底层的 DemoParser，保障获取细粒度事件如 player_blind，以防 AWPy 没有全量 wrap。
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

    def parse_to_dict(self) -> dict:
        if not self.parser:
            logger.error("解析引擎空转，因为并未成功持有一个真实的 .dem 文件句柄。")
            return {}

        logger.info(f"🚀 核心解析引擎已挂载！开始切入 Demo: {self.demo_path}")
        
        try:
            # 1. 解析全局事件表 (一键推入内存池，极大优化计算复杂度)
            logger.info("⏳ 正在请求底层引擎吐出战术帧矩阵...")
            
            df_rounds_end = dict(self.parser.parse_events(["round_end"])).get("round_end", pd.DataFrame())
            if df_rounds_end.empty:
                logger.warning("并未捕获到有效回合数据，文件可能已损坏。")
                return

            # 解析我们关心的高压对峙事件，并一并调取坐标
            df_kills = dict(self.parser.parse_events(["player_death"], player=["X", "Y", "Z"], other=["X", "Y", "Z"])).get("player_death", pd.DataFrame())
            df_blind = dict(self.parser.parse_events(["player_blind"])).get("player_blind", pd.DataFrame())
            df_bomb = dict(self.parser.parse_events(["bomb_planted"])).get("bomb_planted", pd.DataFrame())
            
            # 手雷类爆点落地判定
            # smoke / hegrenade / inferno_startfire
            df_smokes = dict(self.parser.parse_events(["smokegrenade_detonate"], player=["X", "Y", "Z"])).get("smokegrenade_detonate", pd.DataFrame())
            df_inferno = dict(self.parser.parse_events(["inferno_startfire"], player=["X", "Y", "Z"])).get("inferno_startfire", pd.DataFrame())
            df_he = dict(self.parser.parse_events(["hegrenade_detonate"], player=["X", "Y", "Z"])).get("hegrenade_detonate", pd.DataFrame())

            # 2. 定义战果承载桶
            # 我们通过 parsing header 或者假设兜底名称
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

            # 3. 按照回合 Tick 断点对巨量帧进行数据切片与包裹
            round_idx = 1
            for idx, round_row in df_rounds_end.iterrows():
                current_tick = round_row.get("tick", 0)
                prev_tick = df_rounds_end.iloc[idx - 1]["tick"] if idx > 0 else 0
                
                # [基础信息]
                round_detail = {
                    "round_number": round_idx,
                    "winner": str(round_row.get("winner", "Unknown")),
                    "reason": str(round_row.get("reason", "Unknown")),
                    "kills": [],
                    "grenades": [],
                    "flash_blinds": [],
                    "plants": []
                }
                
                # --- [击杀链 (Kills)] ---
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

                # --- [道具爆点 (Grenades)] ---
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

                # --- [闪光分析 (Flash/Blind)] ---
                if not df_blind.empty and 'tick' in df_blind.columns:
                    blinds_in_round = df_blind[(df_blind['tick'] > prev_tick) & (df_blind['tick'] <= current_tick)]
                    for _, blind in blinds_in_round.iterrows():
                        round_detail["flash_blinds"].append({
                            "tick": self._safe_convert(blind.get("tick")),
                            "victim": str(blind.get("user_name", "Unknown")),
                            "attacker": str(blind.get("attacker_name", "Unknown")),
                            "blind_duration": self._safe_convert(blind.get("blind_duration", 0.0))
                        })

                # --- [下包详情 (Plants)] ---
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
            logger.error(f"解析过程中发生致命的血崩级联错误: {str(e)}")
            logger.error(traceback.format_exc())
            return {}

    def process_and_export(self, output_path: str = "output/parsed_demo.json"):
        match_data = self.parse_to_dict()
        if not match_data:
            return 
            
        try:
            # 4. JSON 序列化并落地保存
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(match_data, f, ensure_ascii=False, indent=4)
            
            logger.info(f"🎉 全部解析流转结束！硬核 JSON 数据表已成功落地至: {output_path}")
        except Exception as e:
            logger.error(f"落地 JSON 发生异常: {str(e)}")

if __name__ == "__main__":
    # 使用时，需保证 data 目录下存在一个真实的 cs2 DEMO 以供引擎开凿。
    # 由于是开发阶段，如果文件不存在，依然会打印清晰的失败日志进行柔性容错。
    mock_demo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sample.dem")
    
    parser = TacticalDemoParser(demo_path=mock_demo_path)
    # 调用提炼流线
    parser.process_and_export(output_path="output/parsed_demo.json")
