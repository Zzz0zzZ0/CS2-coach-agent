import logging
import asyncio
import hashlib
import time
from functools import lru_cache
from pathlib import Path
from app.core.celery_app import celery_app
from app.domain.match_models import MatchWebhookPayload
from app.core.providers import get_graph_client, get_llm, get_kb_client
from app.core.config import settings
from app.services.analysis_pipeline import AnalysisPipeline
from app.services.parser_service import TacticalDemoParser
from app.services.analysis_runs import AnalysisRunStore, RunAlreadyStarted

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _worker_runner():
    # Celery's solo/prefork execution slot reuses clients and their owning loop.
    return asyncio.Runner()


def _claim(store, task_id, metadata):
    if store.start(task_id, metadata):
        return None
    existing = store.get(task_id)
    if existing["status"] == "SUCCESS":
        return existing["result"]
    # A duplicate delivery must not replay a paid or interrupted operation.
    raise RunAlreadyStarted("Analysis already started; inspect the saved run before any new execution")


def _run_match_analysis(payload: MatchWebhookPayload, task_id: str):
    store = AnalysisRunStore()
    cached = _claim(store, task_id, {"source": "payload", "match_id": payload.match_id, "map": payload.map_name})
    if cached is not None:
        return cached
    try:
        return _analyze_owned_match(payload, task_id, store)
    except BaseException as error:
        store.finish(task_id, error=type(error).__name__)
        raise


def _analyze_owned_match(payload: MatchWebhookPayload, task_id: str, store):
    logger.info(f"====== [Celery Worker] 开始处理 Webhook 任务: {task_id} ======")
    logger.info(f"比赛 ID: {payload.match_id} | 地图名称: {payload.map_name}")

    store.save_input(task_id, payload.model_dump())
    start = time.monotonic()
    store.event(task_id, {"node": "Initialize", "status": "started", "attempt": 1, "at": time.time()})
    try:
        pipeline = AnalysisPipeline(get_llm(), get_kb_client(), get_graph_client())
    except BaseException as error:
        store.event(task_id, {"node": "Initialize", "status": "failed", "attempt": 1,
                             "at": time.time(), "error_type": type(error).__name__})
        raise
    store.event(task_id, {"node": "Initialize", "status": "completed", "attempt": 1,
                         "at": time.time(), "duration_ms": round((time.monotonic()-start)*1000, 2)})
    result = _worker_runner().run(pipeline.analyze(payload, lambda event: store.event(task_id, event)))
    coach_advice = result.coach_advice or "教练由于未知原因未给出战术建议。"

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    with open(output_dir / "analysis.log", "a", encoding="utf-8") as f:
        f.write(f"\n[{payload.match_id} | {payload.map_name} | CeleryTask:{task_id}]\n")
        f.write("=== Coach Tactical Advice ===\n")
        f.write(coach_advice + "\n")
        f.write("=========================================\n")

    verification = result.verification_report or {}
    quality_status = "success" if verification.get("status") == "pass" else "needs_review"
    approved = bool(payload.extra_data.get("knowledge_approved", False))
    review_reasons = []
    if not settings.AUTO_INGEST_ENABLED:
        review_reasons.append("auto_ingest_disabled")
    if not payload.is_high_quality:
        review_reasons.append("source_not_marked_high_quality")
    if not approved:
        review_reasons.append("explicit_human_approval_required")
    if verification.get("status") != "pass":
        review_reasons.append("verification_not_passed")

    knowledge_task_id = None
    if not review_reasons and coach_advice:
        knowledge_task = ingest_knowledge_task.delay(
            source_text=(
                f"【数据分析报告】\n{result.analyst_report}\n\n"
                f"【教练战术复盘】\n{coach_advice}"
            ),
            source_name=f"self_learning_loop:{payload.match_id}",
        )
        knowledge_task_id = knowledge_task.id

    knowledge_review = {
        "status": "approved" if not review_reasons else "pending_review",
        "eligible": not review_reasons,
        "reasons": review_reasons,
    }
    result.knowledge_review = knowledge_review

    logger.info(f"====== [Celery Worker] 任务完成: {task_id} ======")
    output = {
        "status": quality_status,
        "coach_advice": coach_advice,
        "analyst_report": result.analyst_report,
        "metrics": result.metrics.model_dump(),
        "analysis": result.model_dump(),
        "knowledge_task_id": knowledge_task_id,
        "knowledge_review": knowledge_review,
    }
    store.finish(task_id, result=output)
    return output


@celery_app.task(bind=True, name="process_webhook_match_task")
def process_webhook_match_task(self, payload_dict: dict):
    """
    处理 Webhook 或爬虫推送的赛后数据任务。
    
    因底层 LangGraph 工作流（Workflow）采用异步调用，
    在 Celery 的同步 worker 执行槽内复用事件循环，保留异步客户端连接的生命周期。
    """
    try:
        payload = MatchWebhookPayload(**payload_dict)
        return _run_match_analysis(payload, self.request.id)
        
    except Exception as e:
        logger.error(f"Celery 执行阻断级异常: {e}", exc_info=True)
        self.update_state(state="FAILURE", meta={"exc_type": type(e).__name__, "exc_message": str(e)})
        raise e

@celery_app.task(bind=True, name="parse_and_analyze_demo_task")
def parse_and_analyze_demo_task(
    self,
    file_path_str: str,
    original_filename: str = "",
    is_high_quality: bool = True,
    auto_delete: bool = False,
    analysis_mode: str = "demo_forensic",
):
    """
    独立任务：解析物理 Demo，然后生成 payload，再进行后续分析
    """
    store = AnalysisRunStore()
    cached = _claim(store, self.request.id, {"source": "demo", "filename": Path(original_filename or file_path_str).name,
                                          "analysis_mode": analysis_mode})
    if cached is not None:
        return cached
    logger.info(f"====== [Celery Worker] 开始解析实网 Demo: {file_path_str} ======")
    parsing = True
    started = time.monotonic()
    store.event(self.request.id, {"node": "Parse", "status": "started", "attempt": 1, "at": time.time()})
    try:
        with open(file_path_str, "rb") as source:
            demo_sha256 = hashlib.file_digest(source, "sha256").hexdigest()
        store.set_metadata(self.request.id, {"demo_sha256": demo_sha256})
        parser = TacticalDemoParser(file_path_str)
        dem_dict = parser.parse_to_dict()
        
        if not dem_dict or not dem_dict.get("rounds"):
            raise ValueError("解析上传的 Demo 失败或其为空！")
            
        store.event(self.request.id, {"node": "Parse", "status": "completed", "attempt": 1,
            "at": time.time(), "duration_ms": round((time.monotonic()-started)*1000, 2),
            "details": {"rounds": len(dem_dict["rounds"]), "demo_sha256": demo_sha256}})
        parsing = False
        payload = MatchWebhookPayload(
            match_id=dem_dict.get("match_id", "upload_demo"),
            map_name=dem_dict.get("map_name", "unknown"),
            rounds=dem_dict.get("rounds", []),
            extra_data={
                "demo_sha256": demo_sha256,
                "source": "direct_upload", 
                "filename": original_filename or Path(file_path_str).name,
                "is_high_quality": is_high_quality,
                "analysis_mode": analysis_mode,
            }
        )
        
        # 解析完成后，复用统一的核心分析接口
        result = _analyze_owned_match(payload, self.request.id, store)
        return result
        
    except Exception as e:
        if parsing:
            store.event(self.request.id, {"node": "Parse", "status": "failed", "attempt": 1,
                "at": time.time(), "duration_ms": round((time.monotonic()-started)*1000, 2), "error_type": type(e).__name__})
        store.finish(self.request.id, error=type(e).__name__)
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
    try:
        from app.services.knowledge_extraction_service import KnowledgeExtractionService
        extractor = KnowledgeExtractionService(get_llm(), get_kb_client())
        inserted_count = extractor.process_and_ingest(source_text, source_name)
        logger.info(f"====== [Celery Worker] 知识摄取任务完成: {self.request.id} ======")
        return {"status": "success", "inserted_count": inserted_count}
    except Exception as e:
        logger.error(f"Celery 知识摄取异常: {e}", exc_info=True)
        self.update_state(state="FAILURE", meta={"exc_type": type(e).__name__, "exc_message": str(e)})
        raise e
