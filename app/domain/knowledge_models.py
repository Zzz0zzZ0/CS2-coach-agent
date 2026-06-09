from pydantic import BaseModel, Field
from typing import Optional

class KnowledgeIngestPayload(BaseModel):
    source_text: str = Field(..., description="原始战术分析文本、战报或日志")
    source_name: Optional[str] = Field(default="unknown_source", description="数据来源标识，如 hltv_news, user_upload")
    
class KnowledgeIngestResponse(BaseModel):
    status: str
    message: str
    task_id: Optional[str] = None
