import sqlite3
from fastapi import APIRouter, HTTPException, Query, Request
from celery.result import AsyncResult
from app.core.celery_app import celery_app
from app.services.analysis_runs import AnalysisRunStore
from app.services.followup_service import answer_question, QuestionKind, QuestionUnavailable, SourceDetail

router = APIRouter()


@router.get("/{task_id}/questions")
def ask_saved_analysis(request: Request, task_id: str, kind: QuestionKind, round_number: int | None = Query(default=None, ge=1),
                       player: str | None = Query(default=None, min_length=1, max_length=100),
                       max_steps: int = Query(default=2, ge=1, le=2), detail: SourceDetail = 'full',
                       expected_payload_sha256: str | None = Query(default=None, pattern=r'^[a-f0-9]{64}$')):
    if set(request.query_params) - {'kind', 'round_number', 'player', 'max_steps', 'detail', 'expected_payload_sha256'}:
        raise HTTPException(status_code=422, detail="Unsupported question parameter")
    try:
        return answer_question(AnalysisRunStore(), task_id, kind, round_number, player, max_steps,
                               detail, expected_payload_sha256)
    except QuestionUnavailable as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from None
    except sqlite3.Error:
        raise HTTPException(status_code=503, detail="Analysis history unavailable") from None

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
