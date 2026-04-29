"""
统一的本地分析 CLI，实现从 .dem 文件读取到大模型报告输出的一键流转。
用法: python scripts/analyze_local.py [data/sample.dem]
"""
import sys
import asyncio
import json
import logging
from pathlib import Path

# 将项目根目录加入可用模块路径
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.services.parser_service import TacticalDemoParser
from app.api.dependencies import get_llm, get_kb_client
from app.agentic.workflow import create_workflow_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_LOG_PATH = Path("output/analysis.log")

async def analyze_demo(demo_path: str):
    logger.info(f"=== [Phase 1: 数据解剖] 初始化解析器对准 {demo_path} ===")
    parser = TacticalDemoParser(demo_path)
    demo_dict = parser.parse_to_dict()
    
    if not demo_dict or not demo_dict.get("rounds"):
        logger.error("解析器未能提取到有效战术特征，退出流转。")
        return

    match_id = demo_dict.get("match_id", "unknown")
    map_name  = demo_dict.get("map_name", "unknown")
    total_rounds = len(demo_dict.get("rounds", []))
    
    logger.info(f"提取成功！比赛ID: {match_id} | 地图: {map_name} | 回合数: {total_rounds}")

    # ===== 状态机构建 =====
    raw_data_str = json.dumps(demo_dict, ensure_ascii=False)
    if len(raw_data_str) > 8000:
        logger.warning(f"数据量极大 ({len(raw_data_str)} chars)，截断至 8000 字符喂给分析师以防爆 Token。")
        raw_data_str = raw_data_str[:8000] + "\n... [truncated for token limit]"

    initial_state = {
        "raw_data": raw_data_str,
        "rag_context": "",
        "analyst_report": "",
        "coach_advice": ""
    }

    logger.info("=== [Phase 2: 编排节点流转] 唤醒 LangGraph 多智能体... ===")
    try:
        llm = get_llm()
        kb_client = get_kb_client()
        workflow_app = create_workflow_app(llm, kb_client)
        final_state = await workflow_app.ainvoke(initial_state)
    except Exception as e:
        logger.error(f"流转过程中发生异常: {e}", exc_info=True)
        return

    analyst_report = final_state.get("analyst_report", "")
    coach_advice   = final_state.get("coach_advice", "")

    # ===== 结果落地 =====
    OUTPUT_LOG_PATH.parent.mkdir(exist_ok=True)
    with open(OUTPUT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*70}\n")
        f.write(f"[实战文件分析] ID: {match_id} | MAP: {map_name} | ROUNDS: {total_rounds}\n")
        f.write("=== Analyst Precise Report ===\n")
        f.write(analyst_report + "\n\n")
        f.write("=== Coach Tactical Enforcer ===\n")
        f.write(coach_advice + "\n")
        f.write(f"{'='*70}\n")

    logger.info(f"流转竣工！报告已写入: {OUTPUT_LOG_PATH}")
    logger.info(f"\n{'─'*60}\n【极简复盘预览】:\n{coach_advice[:500]}...\n{'─'*60}")


if __name__ == "__main__":
    target_demo = sys.argv[1] if len(sys.argv) > 1 else "data/sample.dem"
    if not Path(target_demo).exists():
        logger.error(f"找不到 Demo 文件: {target_demo}")
        sys.exit(1)
        
    asyncio.run(analyze_demo(target_demo))
