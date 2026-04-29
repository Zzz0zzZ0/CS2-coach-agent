import logging
import uvicorn
from fastapi import FastAPI
from app.core.config import settings
from app.api.routers import webhooks, uploads, tasks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.APP_NAME,
    description="基于 Webhook 与状态机的战术分析服务"
)

# 挂载路由
app.include_router(webhooks.router, prefix="/api/webhook", tags=["webhooks"])
app.include_router(uploads.router, prefix="/api", tags=["uploads"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
