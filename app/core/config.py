import os
from dotenv import load_dotenv

# 加载 .env 环境变量
load_dotenv()

class Settings:
    # 阿里大模型相关配置
    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")
    DASHSCOPE_KEY_FILE: str = os.getenv(
        "DASHSCOPE_KEY_FILE", "data/runtime/dashscope_api_key"
    )
    MODEL_NAME: str = os.getenv("MODEL_NAME", "qwen3.8-flash")
    LLM_TIMEOUT_SECONDS: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "1400"))
    LLM_ENABLE_THINKING: bool = os.getenv("LLM_ENABLE_THINKING", "false").lower() == "true"
    LLM_BUDGET_DB: str = os.getenv("LLM_BUDGET_DB", "data/runtime/llm_budget.sqlite")
    LLM_BUDGET_TOKENS: int = int(os.getenv("LLM_BUDGET_TOKENS", "30000"))
    LLM_BUDGET_MAX_CALLS: int = int(os.getenv("LLM_BUDGET_MAX_CALLS", "100"))
    LLM_AUXILIARY_CALLS_ENABLED: bool = os.getenv(
        "LLM_AUXILIARY_CALLS_ENABLED", "false"
    ).lower() == "true"
    EMBEDDING_BACKEND: str = os.getenv("EMBEDDING_BACKEND", "fastembed")
    EMBEDDING_MODEL: str = os.getenv(
        "EMBEDDING_MODEL",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    )
    
    # 向量库配置 (Milvus)
    MILVUS_URI: str = os.getenv("MILVUS_URI", "http://localhost:19530")
    MILVUS_TOKEN: str = os.getenv("MILVUS_TOKEN", "")
    RAG_HYBRID_ENABLED: bool = os.getenv("RAG_HYBRID_ENABLED", "true").lower() == "true"
    # Self-learning is opt-in and still requires explicit per-match approval.
    AUTO_INGEST_ENABLED: bool = os.getenv("AUTO_INGEST_ENABLED", "false").lower() == "true"
    AUTONOMOUS_TOOL_SELECTION_ENABLED: bool = os.getenv(
        "AUTONOMOUS_TOOL_SELECTION_ENABLED", "false"
    ).lower() == "true"
    
    # 消息队列配置 (Celery + Redis)
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
    DEMO_DOWNLOAD_DIR: str = os.getenv("DEMO_DOWNLOAD_DIR", "data/demos")
    GRAPH_DB_PATH: str = os.getenv("GRAPH_DB_PATH", "data/graph/cs2_graph.sqlite")
    
    # 应用配置
    APP_NAME: str = "CS2 Multi-Agent Tactical Analysis Service"

settings = Settings()
