import logging
from app.agentic.states import GraphState
from app.services.knowledge_extraction_service import KnowledgeExtractionService

logger = logging.getLogger(__name__)

def create_ingest_node():
    extractor = KnowledgeExtractionService()
    
    def ingest_node(state: GraphState):
        logger.info("--- 节点: 知识摄取 (Ingest) ---")
        
        is_high_quality = state.get("is_high_quality", False)
        if not is_high_quality:
            logger.info("[Ingest] 当前对局未被标记为高质量对局 (非S级)，跳过战术抽取。")
            state["ingested_tactics_count"] = 0
            return state

        coach_advice = state.get("coach_advice", "")
        analyst_report = state.get("analyst_report", "")
        
        if not coach_advice:
            logger.info("[Ingest] 教练复盘内容为空，跳过战术抽取。")
            state["ingested_tactics_count"] = 0
            return state
            
        source_text = f"【数据分析报告】\n{analyst_report}\n\n【教练战术复盘】\n{coach_advice}"
        
        try:
            inserted = extractor.process_and_ingest(source_text, source_name="self_learning_loop")
            state["ingested_tactics_count"] = inserted
        except Exception as e:
            logger.error(f"[Ingest] 提取战术失败: {e}")
            state["ingested_tactics_count"] = 0
            
        return state
        
    return ingest_node
