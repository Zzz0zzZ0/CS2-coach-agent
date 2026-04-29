import logging
from fastapi import APIRouter, HTTPException

from app.domain.match_models import MatchWebhookPayload
from app.services.tasks import process_webhook_match_task

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/match-end", status_code=200)
async def webhook_match_end(payload: MatchWebhookPayload):
    """
    接收第三方平台推送的赛后 JSON 数据。
    将战术复盘交给 Celery MQ 异步处理。
    """
    try:
        # 发送到 Celery 队列
        task = process_webhook_match_task.delay(payload.model_dump())
        return {
            "status": "processing_in_mq", 
            "task_id": task.id
        }
    except Exception as e:
        logger.error(f"接收 Webhook 请求时发生异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")
