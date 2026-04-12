import os
import json
from pathlib import Path
import uvicorn
import logging
from typing import Any, Dict, List
import uuid
import shutil
from fastapi import FastAPI, BackgroundTasks, HTTPException, UploadFile, File
from pydantic import BaseModel, Field, ConfigDict

from src.data_parser import TacticalDemoParser
from src.agent_orchestrator import workflow_app

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 初始化 FastAPI 异步 Web 服务
app = FastAPI(
    title="CS2 Multi-Agent Tactical Analysis Service",
    description="基于 Webhook 与状态机的战术分析服务"
)

# 定义接收 Webhook 的 Pydantic 模型
class MatchWebhookPayload(BaseModel):
    match_id: str = Field(..., description="比赛唯一标识")
    map_name: str = Field(..., description="地图名称")
    rounds: List[Dict[str, Any]] = Field(default_factory=list, description="各个回合的详细数据")
    # 其余结构兜底
    extra_data: Dict[str, Any] = Field(default_factory=dict, description="其他未明确定义的结构数据兜底")

    # 配置模型以允许未显式声明的额外字段
    model_config = ConfigDict(extra="allow")

# 后台异步函数，收到数据后的处理逻辑
async def process_match_data(payload: MatchWebhookPayload) -> None:
    try:
        logger.info("====== 开始后台处理比赛数据 ======")
        logger.info(f"比赛 ID: {payload.match_id} | 地图名称: {payload.map_name} | 总回合数: {len(payload.rounds)}")
        
        # 将原始数据转为 JSON 字符串
        raw_data_str = json.dumps(payload.model_dump(), ensure_ascii=False)
        
        # 1. 构建初始核心状态 GraphState
        initial_state = {
            "raw_data": raw_data_str,
            "rag_context": "",
            "analyst_report": "",
            "coach_advice": ""
        }
        
        logger.info(">>> [LangGraph] 唤醒多智能体状态机流转...")
        # 2. 异步调用并获取最终状态
        final_state = await workflow_app.ainvoke(initial_state)
        
        coach_advice = final_state.get("coach_advice", "教练由于未知原因未给出战术建议。")
        
        # 3. 结果保存到本地日志文件 output/analysis.log
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        log_file = output_dir / "analysis.log"
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n[{payload.match_id} | {payload.map_name}]\n")
            f.write("=== Coach Tactical Advice ===\n")
            f.write(coach_advice + "\n")
            f.write("=========================================\n")
            
        logger.info(f"====== 赛后数据流转完成，日志已写入: {log_file} ======\n")
        logger.info(f"\n[终端预览] 最新教练复盘:\n{coach_advice}\n")
        
    except Exception as e:
        logger.error(f"后台流转执行时发生阻断级异常: {e}", exc_info=True)

# 创建 POST 路由，接收第三方赛后数据 Webhook
@app.post("/api/webhook/match-end", status_code=200)
async def webhook_match_end(
    payload: MatchWebhookPayload, 
    background_tasks: BackgroundTasks
) -> Dict[str, str]:
    """
    接收第三方平台推送的赛后 JSON 数据。
    将战术复盘等耗时工作交给 BackgroundTasks 后台异步处理，核心服务立即返回 200 并告知状态。
    """
    try:
        background_tasks.add_task(process_match_data, payload)
        return {"status": "processing"}
    except Exception as e:
        logger.error(f"接收 Webhook 请求时发生异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")

@app.post("/api/upload-demo", status_code=200)
async def upload_and_analyze_demo(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    """
    接受直接从客户端上传的 .dem 物理文件。
    将其写入本地临时区域后提取事件流转，复用与 Webhook 相同的后台流转轨道。
    """
    if not file.filename.endswith('.dem'):
        raise HTTPException(status_code=400, detail="Only .dem files are allowed.")
    
    # 将上传的文件临时存放至 data/ 目录
    os.makedirs("data", exist_ok=True)
    safe_filename = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = Path("data") / safe_filename
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        logger.error(f"保存上传 Demo 失败: {e}")
        raise HTTPException(status_code=500, detail="Failed to save demo file.")
        
    # 为了防止接口长时间无响应，我们使用同一种理念：排入队列后即刻返回
    # 但我们需通过包装函数在后台解析，然后再把生成的 JSON 送去流转
    async def parse_and_process(dem_path: str):
        logger.info(f"====== 开始后台解析实网 Demo文件: {dem_path} ======")
        parser = TacticalDemoParser(dem_path)
        dem_dict = parser.parse_to_dict()
        
        if not dem_dict or not dem_dict.get("rounds"):
            logger.error("解析上传的 Demo 失败或其为空！")
            return
            
        logger.info(f"成功将上传的 Demo {dem_path} 解析为 {len(dem_dict['rounds'])} 个回合的超密载荷。正在递送分析器...")
        
        # 兼容到 Webhook 格式
        payload = MatchWebhookPayload(
            match_id=dem_dict.get("match_id", "upload_demo"),
            map_name=dem_dict.get("map_name", "unknown"),
            rounds=dem_dict.get("rounds", []),
            extra_data={"source": "direct_upload", "filename": safe_filename}
        )
        
        # 调用流转中心
        await process_match_data(payload)

    background_tasks.add_task(parse_and_process, str(file_path))
    return {"status": "processing", "message": "Demo file uploaded and parsing engaged.", "temp_filename": safe_filename}

if __name__ == "__main__":
    # 使用 uvicorn 启动 Web 服务
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
