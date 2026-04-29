from typing import Any, Dict, List
from pydantic import BaseModel, Field, ConfigDict

class MatchWebhookPayload(BaseModel):
    match_id: str = Field(..., description="比赛唯一标识")
    map_name: str = Field(..., description="地图名称")
    rounds: List[Dict[str, Any]] = Field(default_factory=list, description="各个回合的详细数据")
    extra_data: Dict[str, Any] = Field(default_factory=dict, description="其他未明确定义的结构数据兜底")

    model_config = ConfigDict(extra="allow")
