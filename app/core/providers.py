import logging
import hashlib
import os
import re
import tempfile
from pathlib import Path

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
_llm_key_fingerprint = None
_kb_client_instance = None
_embeddings_instance = None
_graph_client_instance = None


def _usable_api_key(value: str) -> str:
    key = value.strip()
    placeholder = "your-key" in key.lower() or bool(re.fullmatch(r"sk-x+", key.lower()))
    return key if key.startswith("sk-") and 16 <= len(key) <= 512 and not placeholder and "\n" not in key and "\r" not in key else ""


def get_configured_api_key() -> str:
    """Read the runtime key on demand so API and Celery processes stay in sync."""
    key_file = Path(settings.DASHSCOPE_KEY_FILE)
    try:
        runtime_key = _usable_api_key(key_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError):
        runtime_key = ""
    return runtime_key or _usable_api_key(settings.DASHSCOPE_API_KEY)


def save_runtime_api_key(value: str) -> None:
    """Persist a write-only local key with owner-only permissions."""
    key = _usable_api_key(value)
    if not key:
        raise ValueError("A non-placeholder DashScope API key is required")
    key_file = Path(settings.DASHSCOPE_KEY_FILE)
    key_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(dir=key_file.parent)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, key.encode("utf-8"))
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary_name, key_file)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def get_embeddings():
    global _embeddings_instance
    if _embeddings_instance is None:
        if settings.EMBEDDING_BACKEND.lower() == "fastembed":
            _embeddings_instance = FastEmbedEmbeddings(
                model_name=settings.EMBEDDING_MODEL,
                max_length=512,
            )
        else:
            api_key = get_configured_api_key()
            if not api_key:
                raise RuntimeError("DashScope API key is not configured")
            _embeddings_instance = DashScopeEmbeddings(
                model=settings.EMBEDDING_MODEL,
                dashscope_api_key=api_key,
            )
    return _embeddings_instance


def get_llm():
    global _llm_instance, _llm_key_fingerprint
    api_key = get_configured_api_key()
    if not api_key:
        _llm_instance = None
        _llm_key_fingerprint = None
        return None
    fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    if _llm_instance is None or fingerprint != _llm_key_fingerprint:
        try:
            _llm_instance = ChatOpenAI(
                api_key=api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                model=settings.MODEL_NAME,
            )
            _llm_key_fingerprint = fingerprint
        except Exception as e:
            logger.warning(f"底层模型引擎加载失败 (请检查 .env 配置): {e}")
            _llm_instance = None
            _llm_key_fingerprint = None
    return _llm_instance


def get_kb_client():
    global _kb_client_instance
    llm = get_llm()
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
                llm=llm,
                hybrid_searcher=hybrid_searcher,
            )
        except Exception as e:
            logger.warning(f"知识库(Milvus)加载失败 (请检查 .env 配置或 Milvus 连通性): {e}")
    elif _kb_client_instance.llm is not llm:
        _kb_client_instance.llm = llm
    return _kb_client_instance


def get_graph_client():
    global _graph_client_instance
    if _graph_client_instance is None:
        _graph_client_instance = GraphRAGClient(settings.GRAPH_DB_PATH)
        if not _graph_client_instance.available():
            logger.info("GraphRAG sidecar not found at %s; using Milvus only", settings.GRAPH_DB_PATH)
    return _graph_client_instance
