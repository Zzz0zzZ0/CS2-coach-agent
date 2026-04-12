import os
import logging
from typing import TypedDict
from dotenv import load_dotenv

from langgraph.graph import StateGraph, START, END
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
from src.prompts import ANALYST_PROMPT, COACH_PROMPT
from src.advanced_rag import TacticalRetriever

logger = logging.getLogger(__name__)

# 加载 .env 环境变量
load_dotenv()

# 初始化真实组件（准备迎接真实的 API 调用）
try:
    _llm = ChatOpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", # 关键：指向阿里服务器
    model=os.getenv("MODEL_NAME") # 比如使用 qwen-plus 或 qwen-max
    )
    _embeddings = DashScopeEmbeddings(
    model="text-embedding-v2", # 阿里推荐的向量模型
    dashscope_api_key=os.getenv("DASHSCOPE_API_KEY")
    )
    _chroma_dir = os.getenv("CHROMA_DB_DIR", "./chroma_db")
    _vectorstore = Chroma(persist_directory=_chroma_dir, embedding_function=_embeddings)
    _retriever = TacticalRetriever(vectorstore=_vectorstore, llm=_llm)
except Exception as e:
    logger.warning(f"底层模型引擎加载失败 (请检查 .env 配置): {e}")
    _llm = None
    _retriever = None

# 全局依赖容器：直接挂载真实的依赖引擎
agent_deps = {
    "llm": _llm,
    "retriever": _retriever
}

class GraphState(TypedDict):
    """全局状态，定义每个节点产生及传递的关键信息流字段"""
    raw_data: str
    rag_context: str
    analyst_report: str
    coach_advice: str

async def node_retrieve(state: GraphState) -> dict[str, str]:
    """节点 1：根据赛后原始数据拉取历史相关对局的战术切片"""
    logger.info(">>> 执行图节点: [Retrieve] 正在寻找相似对局上下文...")
    raw_data = state.get("raw_data", "")
    retriever: TacticalRetriever = agent_deps["retriever"]

    rag_context = "暂无匹配的历史上下文数据"
    if retriever:
        try:
            # 截取一部分负载用于启发 LLM，生成 CS2 术语相关的 Query
            initial_query = str(raw_data)[:500] 
            complex_query = await retriever.rewrite_query(initial_query)
            docs = retriever.retrieve_with_mmr(query=complex_query)
            if docs:
                rag_context = "\n---\n".join([doc.page_content for doc in docs])
        except Exception as e:
            logger.error(f"[Retrieve] 节点抓取失败: {e}")
    
    return {"rag_context": rag_context}

async def node_analyst(state: GraphState) -> dict[str, str]:
    """节点 2：完全理性、冰冷的数据剥离与指标计算"""
    logger.info(">>> 执行图节点: [Analyst] 数据师开始分析比赛指标...")
    llm = agent_deps["llm"]
    
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

async def node_coach(state: GraphState) -> dict[str, str]:
    """节点 3：根据冰冷的报告，注入灵魂发散战术复盘"""
    logger.info(">>> 执行图节点: [Coach] 战术教练开始推演与训话...")
    llm = agent_deps["llm"]
    
    if not llm:
        raise ValueError("严重错误：未连接真实 LLM，无法生成教练复盘！")
        
    prompt = PromptTemplate.from_template(COACH_PROMPT)
    chain = prompt | llm
    
    response = await chain.ainvoke({
        "analyst_report": state.get("analyst_report", "")
    })
    coach_advice = response.content if hasattr(response, 'content') else str(response)

    return {"coach_advice": coach_advice}

# ==========================================
# 核心编排：LangGraph 状态机连线
# ==========================================

# 1. 实例化状态图与依赖字典
workflow = StateGraph(GraphState)

# 2. 注入三大核心节点
workflow.add_node("Retrieve", node_retrieve)
workflow.add_node("Analyst", node_analyst)
workflow.add_node("Coach", node_coach)

# 3. 确立线性流转顺序
workflow.add_edge(START, "Retrieve")
workflow.add_edge("Retrieve", "Analyst")
workflow.add_edge("Analyst", "Coach")
workflow.add_edge("Coach", END)

# 4. 封装成完整的 App，暴露给外部入口使用
workflow_app = workflow.compile()
