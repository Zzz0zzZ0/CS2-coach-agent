import logging
from fastapi import APIRouter, HTTPException
from app.domain.knowledge_models import KnowledgeIngestPayload, KnowledgeIngestResponse
from app.services.tasks import ingest_knowledge_task

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/ingest", response_model=KnowledgeIngestResponse)
async def ingest_knowledge(payload: KnowledgeIngestPayload):
    """
    接收原始战术分析文本/战报，异步调用 Celery 提取并插入知识库
    """
    logger.info(f"收到知识库摄取请求，来源: {payload.source_name}")
    try:
        # 发送给 Celery 后台执行
        task = ingest_knowledge_task.delay(
            source_text=payload.source_text,
            source_name=payload.source_name
        )
        return KnowledgeIngestResponse(
            status="accepted",
            message="知识摄取任务已提交至后台处理",
            task_id=task.id
        )
    except Exception as e:
        logger.error(f"提交知识摄取任务失败: {e}")
        raise HTTPException(status_code=500, detail="提交处理任务失败")
