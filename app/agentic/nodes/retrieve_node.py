import logging
from app.agentic.states import GraphState

logger = logging.getLogger(__name__)

def create_retrieve_node(kb_client):
    async def node_retrieve(state: GraphState) -> dict:
        logger.info(">>> 执行图节点: [Retrieve] 正在寻找相似对局上下文...")
        raw_data = state.get("raw_data", "")
        metadata = state.get("retrieval_metadata", {})

        rag_context = "暂无匹配的历史上下文数据"
        if kb_client:
            try:
                initial_query = str(raw_data)[:500] 
                rag_context = await kb_client.fetch_tactical_context(initial_query, metadata)
            except Exception as e:
                logger.error(f"[Retrieve] 节点抓取失败: {e}")
        
        return {"rag_context": rag_context}
    return node_retrieve
