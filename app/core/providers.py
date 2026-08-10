import logging

from langchain_openai import ChatOpenAI
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_community.vectorstores import Milvus
from pymilvus import MilvusClient

from app.core.config import settings
from app.services.rag_service import KnowledgeBaseClient, MilvusHybridSearcher
from app.services.graph_rag_service import GraphRAGClient

logger = logging.getLogger(__name__)

_llm_instance = None
_kb_client_instance = None
_embeddings_instance = None
_graph_client_instance = None


def get_embeddings():
    global _embeddings_instance
    if _embeddings_instance is None:
        if settings.EMBEDDING_BACKEND.lower() == "fastembed":
            _embeddings_instance = FastEmbedEmbeddings(
                model_name=settings.EMBEDDING_MODEL,
                max_length=512,
            )
        else:
            _embeddings_instance = DashScopeEmbeddings(
                model=settings.EMBEDDING_MODEL,
                dashscope_api_key=settings.DASHSCOPE_API_KEY,
            )
    return _embeddings_instance


def get_llm():
    global _llm_instance
    if _llm_instance is None:
        try:
            _llm_instance = ChatOpenAI(
                api_key=settings.DASHSCOPE_API_KEY,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                model=settings.MODEL_NAME,
            )
        except Exception as e:
            logger.warning(f"底层模型引擎加载失败 (请检查 .env 配置): {e}")
    return _llm_instance


def get_kb_client():
    global _kb_client_instance
    if _kb_client_instance is None:
        try:
            embeddings = get_embeddings()
            fields = MilvusClient(
                uri=settings.MILVUS_URI,
                token=settings.MILVUS_TOKEN,
            ).describe_collection("cs2_tactical_knowledge").get("fields", [])
            field_names = {field.get("name") for field in fields}
            hybrid_searcher = None
            if settings.RAG_HYBRID_ENABLED and {"vector", "sparse"}.issubset(field_names):
                hybrid_searcher = MilvusHybridSearcher(
                    client=MilvusClient(uri=settings.MILVUS_URI, token=settings.MILVUS_TOKEN),
                    collection_name="cs2_tactical_knowledge",
                    embeddings=embeddings,
                )
                vectorstore = None
            else:
                vectorstore = Milvus(
                    embedding_function=embeddings,
                    connection_args={
                        "uri": settings.MILVUS_URI,
                        "token": settings.MILVUS_TOKEN,
                    },
                    collection_name="cs2_tactical_knowledge",
                )
            _kb_client_instance = KnowledgeBaseClient(
                vectorstore=vectorstore,
                llm=get_llm(),
                hybrid_searcher=hybrid_searcher,
            )
        except Exception as e:
            logger.warning(f"知识库(Milvus)加载失败 (请检查 .env 配置或 Milvus 连通性): {e}")
    return _kb_client_instance


def get_graph_client():
    global _graph_client_instance
    if _graph_client_instance is None:
        _graph_client_instance = GraphRAGClient(settings.GRAPH_DB_PATH)
        if not _graph_client_instance.available():
            logger.info("GraphRAG sidecar not found at %s; using Milvus only", settings.GRAPH_DB_PATH)
    return _graph_client_instance
