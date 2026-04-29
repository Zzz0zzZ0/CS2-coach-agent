import logging
from app.agentic.states import GraphState
from langchain_core.prompts import PromptTemplate
import json

logger = logging.getLogger(__name__)

def create_router_node(llm):
    async def node_router(state: GraphState) -> dict:
        logger.info(">>> 执行图节点: [Router] 抽取过滤信号...")
        raw_data = state.get("raw_data", "")
        
        metadata = {}
        if llm and len(raw_data) > 20:
            try:
                prompt = PromptTemplate.from_template(
                    "你是一个极其强大的信息抽取器。从以下提供的CS2比赛原始数据中提取出'map_name'字段对应的地图名称。"
                    "仅仅回复一个合法的 JSON 字典，例如: {{\"map\": \"Mirage\"}} 或 {{\"map\": \"Inferno\"}} 等等。"
                    "如果没有找到，请回复空字典 {{}}。千万不要返回多余的内容。\n\n数据片段: {data}"
                )
                chain = prompt | llm
                resp = await chain.ainvoke({"data": str(raw_data)[:1500]})
                content = resp.content if hasattr(resp, 'content') else str(resp)
                content = content.replace("```json", "").replace("```", "").strip()
                metadata = json.loads(content)
                logger.info(f"[Router] 成功捕获标量元数据: {metadata}")
            except Exception as e:
                logger.warning(f"[Router] 提取元数据失败，将退化为全局检索: {e}")
                
        return {
            "retrieval_metadata": metadata,
            "retry_count": state.get("retry_count", 0)
        }
    return node_router
