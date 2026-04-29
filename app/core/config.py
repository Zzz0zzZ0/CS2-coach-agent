import os
from dotenv import load_dotenv

# 加载 .env 环境变量
load_dotenv()

class Settings:
    # 阿里大模型相关配置
    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")
    MODEL_NAME: str = os.getenv("MODEL_NAME", "qwen-plus")
    EMBEDDING_MODEL: str = "text-embedding-v2"
    
    # 向量库配置 (Milvus 替换 Chroma)
    MILVUS_URI: str = os.getenv("MILVUS_URI", "http://localhost:19530")
    MILVUS_TOKEN: str = os.getenv("MILVUS_TOKEN", "")
    
    # 消息队列配置 (Celery + Redis)
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
    
    # 应用配置
    APP_NAME: str = "CS2 Multi-Agent Tactical Analysis Service"

settings = Settings()
