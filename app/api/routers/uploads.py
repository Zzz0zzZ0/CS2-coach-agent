import os
import uuid
import shutil
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File

from app.services.tasks import parse_and_analyze_demo_task

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/upload-demo", status_code=200)
async def upload_and_analyze_demo(file: UploadFile = File(...)):
    """
    接受直接从客户端上传的 .dem 物理文件。
    将文件流转交给 Celery 后台解析。
    """
    if not file.filename.endswith('.dem'):
        raise HTTPException(status_code=400, detail="Only .dem files are allowed.")
    
    os.makedirs("data", exist_ok=True)
    safe_filename = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = Path("data") / safe_filename
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        logger.error(f"保存上传 Demo 失败: {e}")
        raise HTTPException(status_code=500, detail="Failed to save demo file.")
        
    # 交给 MQ 独立解析
    task = parse_and_analyze_demo_task.delay(str(file_path), safe_filename)
    
    return {
        "status": "processing_in_mq", 
        "message": "Demo file uploaded and parsing engaged.", 
        "temp_filename": safe_filename,
        "task_id": task.id
    }
