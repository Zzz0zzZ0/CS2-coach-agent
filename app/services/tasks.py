import json
import logging
from pathlib import Path
from asgiref.sync import async_to_sync
from app.core.celery_app import celery_app
from app.domain.match_models import MatchWebhookPayload
from app.api.dependencies import get_llm, get_kb_client
from app.agentic.workflow import create_workflow_app
from app.services.parser_service import TacticalDemoParser

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, name="process_webhook_match_task")
def process_webhook_match_task(self, payload_dict: dict):
    """
    处理 Webhook 或爬虫推送的赛后数据任务。
    
    因底层 LangGraph 工作流（Workflow）采用异步调用，
    在 Celery 的同步 worker 中使用 `async_to_sync` 包装并阻塞执行。
    """
    try:
        payload = MatchWebhookPayload(**payload_dict)
        logger.info(f"====== [Celery Worker] 开始处理 Webhook 任务: {self.request.id} ======")
        logger.info(f"比赛 ID: {payload.match_id} | 地图名称: {payload.map_name}")
        
        raw_data_str = json.dumps(payload.model_dump(), ensure_ascii=False)
        
        is_high_quality = payload.extra_data.get("is_high_quality", False)
        
        initial_state = {
            "raw_data": raw_data_str,
            "rag_context": "",
            "analyst_report": "",
            "coach_advice": "",
            "is_high_quality": is_high_quality
        }
        
        llm = get_llm()
        kb_client = get_kb_client()
        workflow_app = create_workflow_app(llm, kb_client)
        
        # 阻塞等待异步工作流执行完毕
        final_state = async_to_sync(workflow_app.ainvoke)(initial_state)
        
        coach_advice = final_state.get("coach_advice", "教练由于未知原因未给出战术建议。")
        
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        log_file = output_dir / "analysis.log"
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n[{payload.match_id} | {payload.map_name} | CeleryTask:{self.request.id}]\n")
            f.write("=== Coach Tactical Advice ===\n")
            f.write(coach_advice + "\n")
            f.write("=========================================\n")
            
        logger.info(f"====== [Celery Worker] 任务完成: {self.request.id} ======")
        return {"status": "success", "coach_advice": coach_advice}
        
    except Exception as e:
        logger.error(f"Celery 执行阻断级异常: {e}", exc_info=True)
        self.update_state(state="FAILURE", meta={"exc_type": type(e).__name__, "exc_message": str(e)})
        raise e

@celery_app.task(bind=True, name="parse_and_analyze_demo_task")
def parse_and_analyze_demo_task(self, file_path_str: str, original_filename: str = "", is_high_quality: bool = True, auto_delete: bool = False):
    """
    独立任务：解析物理 Demo，然后生成 payload，再进行后续分析
    """
    logger.info(f"====== [Celery Worker] 开始解析实网 Demo: {file_path_str} ======")
    try:
        parser = TacticalDemoParser(file_path_str)
        dem_dict = parser.parse_to_dict()
        
        if not dem_dict or not dem_dict.get("rounds"):
            raise ValueError("解析上传的 Demo 失败或其为空！")
            
        payload = MatchWebhookPayload(
            match_id=dem_dict.get("match_id", "upload_demo"),
            map_name=dem_dict.get("map_name", "unknown"),
            rounds=dem_dict.get("rounds", []),
            extra_data={
                "source": "direct_upload", 
                "filename": original_filename or Path(file_path_str).name,
                "is_high_quality": is_high_quality
            }
        )
        
        # 解析完成后，发送给核心分析队列
        result = process_webhook_match_task(self, payload.model_dump())
        return result
        
    except Exception as e:
        logger.error(f"Celery 解析 Demo 异常: {e}", exc_info=True)
        self.update_state(state="FAILURE", meta={"exc_type": type(e).__name__, "exc_message": str(e)})
        raise e
    finally:
        if auto_delete:
            try:
                Path(file_path_str).unlink(missing_ok=True)
                logger.info(f"=== [Cleanup] 成功删除已解析的 DEMO 文件: {file_path_str} ===")
            except Exception as cleanup_err:
                logger.warning(f"=== [Cleanup Error] 删除 DEMO 文件失败: {cleanup_err} ===")

@celery_app.task(bind=True, name="ingest_knowledge_task")
def ingest_knowledge_task(self, source_text: str, source_name: str):
    """
    独立任务：从原始文本中提取战术片段并插入 Milvus 向量库
    """
    logger.info(f"====== [Celery Worker] 开始知识摄取任务: {self.request.id} ======")
    from app.services.knowledge_extraction_service import KnowledgeExtractionService
    try:
        extractor = KnowledgeExtractionService()
        inserted_count = extractor.process_and_ingest(source_text, source_name)
        logger.info(f"====== [Celery Worker] 知识摄取任务完成: {self.request.id} ======")
        return {"status": "success", "inserted_count": inserted_count}
    except Exception as e:
        logger.error(f"Celery 知识摄取异常: {e}", exc_info=True)
        self.update_state(state="FAILURE", meta={"exc_type": type(e).__name__, "exc_message": str(e)})
        raise e
