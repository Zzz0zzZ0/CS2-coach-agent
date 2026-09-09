import sqlite3
from fastapi import APIRouter, HTTPException, Query
from celery.result import AsyncResult
from app.core.celery_app import celery_app
from app.services.analysis_runs import AnalysisRunStore

router = APIRouter()

@router.get("")
def list_analysis_runs(limit: int = Query(default=20, ge=1, le=100)):
    try:
        return {"runs": AnalysisRunStore().recent(limit)}
    except sqlite3.Error:
        raise HTTPException(status_code=503, detail="Analysis history unavailable") from None


@router.get("/{task_id}")
async def get_task_status(task_id: str):
    """
    查询 MQ 中的异步任务状态和结果
    """
    try:
        saved = AnalysisRunStore().get(task_id)
    except sqlite3.Error:
        raise HTTPException(status_code=503, detail="Analysis history unavailable") from None
    if saved is not None:
        return saved
    task_result = AsyncResult(task_id, app=celery_app)
    
    response = {
        "task_id": task_id,
        "status": task_result.status,
    }
    
    if task_result.status == "SUCCESS":
        response["result"] = task_result.result
    elif task_result.status == "FAILURE":
        response["error"] = str(task_result.result)
        
    return response
