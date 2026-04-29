import logging
from app.agentic.states import GraphState
from app.agentic.prompts import ANALYST_PROMPT
from langchain_core.prompts import PromptTemplate

logger = logging.getLogger(__name__)

def create_analyst_node(llm):
    async def node_analyst(state: GraphState) -> dict:
        logger.info(">>> 执行图节点: [Analyst] 数据师开始分析比赛指标...")
        
        if not llm:
            raise ValueError("严重错误：未连接真实 LLM，停止分析流转！")
        
        prompt = PromptTemplate.from_template(ANALYST_PROMPT)
        chain = prompt | llm
        
        response = await chain.ainvoke({
            "raw_data": state.get("raw_data", ""),
            "rag_context": state.get("rag_context", "")
        })
        analyst_report = response.content if hasattr(response, 'content') else str(response)

        return {"analyst_report": analyst_report}
    return node_analyst
