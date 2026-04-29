import logging
from langchain_openai import ChatOpenAI
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_milvus import Milvus
from app.core.config import settings
from app.services.rag_service import KnowledgeBaseClient

logger = logging.getLogger(__name__)

# 全局缓存单例
_llm_instance = None
_kb_client_instance = None

def get_llm():
    global _llm_instance
    if _llm_instance is None:
        try:
            _llm_instance = ChatOpenAI(
                api_key=settings.DASHSCOPE_API_KEY,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                model=settings.MODEL_NAME
            )
        except Exception as e:
            logger.warning(f"底层模型引擎加载失败 (请检查 .env 配置): {e}")
    return _llm_instance

def get_kb_client():
    global _kb_client_instance
    if _kb_client_instance is None:
        try:
            embeddings = DashScopeEmbeddings(
                model=settings.EMBEDDING_MODEL,
                dashscope_api_key=settings.DASHSCOPE_API_KEY
            )
            vectorstore = Milvus(
                embedding_function=embeddings,
                connection_args={
                    "uri": settings.MILVUS_URI,
                    "token": settings.MILVUS_TOKEN
                },
                collection_name="cs2_tactical_knowledge",
                auto_id=True
            )
            _kb_client_instance = KnowledgeBaseClient(vectorstore=vectorstore, llm=get_llm())
        except Exception as e:
            logger.warning(f"知识库(Milvus)加载失败 (请检查 .env 配置或 Milvus 连通性): {e}")
    return _kb_client_instance
