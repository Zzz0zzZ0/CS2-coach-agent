import logging
from app.agentic.states import GraphState
from langchain_core.prompts import PromptTemplate

logger = logging.getLogger(__name__)

def create_critique_node(llm):
    async def node_critique(state: GraphState) -> dict:
        logger.info(">>> 执行图节点: [Critique] 裁判查验检索结果质量...")
        rag_context = state.get("rag_context", "")
        
        score = 1.0 
        if llm and "暂无匹配" not in rag_context:
            try:
                prompt = PromptTemplate.from_template(
                    "作为一名苛刻的 CS2 战术法官，你必须评估下方的【检索出的历史战术文档】有没有实质性的意义。"
                    "请严格按 0.0 到 1.0 给出一个准确的分数。（例如 0.85）\n"
                    "满分 1.0 表示高度相关可直接用于复盘，0.0 表示全是前言不搭后语的垃圾废话。\n\n"
                    "【检索出的文档】\n{context}\n\n"
                    "请仅回复一个浮点数，不要带任何其他字符："
                )
                chain = prompt | llm
                resp = await chain.ainvoke({"context": rag_context[:2000]})
                content = resp.content if hasattr(resp, 'content') else str(resp)
                score = float(content.strip())
                logger.info(f"[Critique] 检索质量评分为: {score:.2f}")
            except Exception as e:
                logger.warning(f"[Critique] 解析评分失败: {e}，默认放行。")
        
        new_retry_count = state.get("retry_count", 0) + 1
        return {
            "critique_score": score,
            "retry_count": new_retry_count
        }
    return node_critique
