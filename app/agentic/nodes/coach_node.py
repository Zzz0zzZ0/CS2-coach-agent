import logging
from app.agentic.states import GraphState
from app.agentic.prompts import COACH_PROMPT
from langchain_core.prompts import PromptTemplate

logger = logging.getLogger(__name__)

def create_coach_node(llm):
    async def node_coach(state: GraphState) -> dict:
        logger.info(">>> 执行图节点: [Coach] 战术教练开始推演与训话...")
        
        if not llm:
            raise ValueError("严重错误：未连接真实 LLM，无法生成教练复盘！")
            
        prompt = PromptTemplate.from_template(COACH_PROMPT)
        chain = prompt | llm
        
        response = await chain.ainvoke({
            "analyst_report": state.get("analyst_report", "")
        })
        coach_advice = response.content if hasattr(response, 'content') else str(response)

        return {"coach_advice": coach_advice}
    return node_coach
