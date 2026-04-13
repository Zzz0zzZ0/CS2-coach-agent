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
    _vectorstore = Chroma(persist_directory=_chroma_dir, embedding_function=_embeddings, collection_name="cs2_tactical_knowledge")
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
    retrieval_metadata: dict
    critique_score: float
    retry_count: int

async def node_router(state: GraphState) -> dict:
    """节点 0：路由节点，拦截并在检索之前识别过滤元数据"""
    logger.info(">>> 执行图节点: [Router] 抽取过滤信号...")
    llm = agent_deps["llm"]
    raw_data = state.get("raw_data", "")
    
    metadata = {}
    if llm and len(raw_data) > 20: # 保证有效数据量
        try:
            from langchain_core.prompts import PromptTemplate
            prompt = PromptTemplate.from_template(
                "你是一个极其强大的信息抽取器。从以下提供的CS2比赛原始数据中提取出'map_name'字段对应的地图名称。"
                "仅仅回复一个合法的 JSON 字典，例如: {{\"map\": \"Mirage\"}} 或 {{\"map\": \"Inferno\"}} 等等。"
                "如果没有找到，请回复空字典 {{}}。千万不要返回多余的内容。\n\n数据片段: {data}"
            )
            chain = prompt | llm
            # 仅喂前1500字符以防速度过慢
            resp = await chain.ainvoke({"data": str(raw_data)[:1500]})
            content = resp.content if hasattr(resp, 'content') else str(resp)
            # 清理可能的 markdown 代码块
            content = content.replace("```json", "").replace("```", "").strip()
            import json
            metadata = json.loads(content)
            logger.info(f"[Router] 成功捕获标量元数据: {metadata}")
        except Exception as e:
            logger.warning(f"[Router] 提取元数据失败，将退化为全局检索: {e}")
            
    return {
        "retrieval_metadata": metadata,
        "retry_count": state.get("retry_count", 0)
    }

async def node_retrieve(state: GraphState) -> dict:
    """节点 1：调用混合检索 (Hybrid Search) 寻找历史切片"""
    logger.info(">>> 执行图节点: [Retrieve] 正在寻找相似对局上下文...")
    raw_data = state.get("raw_data", "")
    metadata = state.get("retrieval_metadata", {})
    retriever: TacticalRetriever = agent_deps["retriever"]

    rag_context = "暂无匹配的历史上下文数据"
    if retriever:
        try:
            initial_query = str(raw_data)[:500] 
            complex_query = await retriever.rewrite_query(initial_query)
            docs = retriever.hybrid_search(query=complex_query, metadata_filter=metadata)
            if docs:
                rag_context = "\n---\n".join([doc.page_content for doc in docs])
        except Exception as e:
            logger.error(f"[Retrieve] 节点抓取失败: {e}")
    
    return {"rag_context": rag_context}

async def node_critique(state: GraphState) -> dict:
    """节点 1.5：(Self-RAG) 反思节点，评判上一步的检索上下文是否达标"""
    logger.info(">>> 执行图节点: [Critique] 裁判查验检索结果质量...")
    llm = agent_deps["llm"]
    rag_context = state.get("rag_context", "")
    
    score = 1.0 # 默认宽容
    if llm and "暂无匹配" not in rag_context:
        try:
            from langchain_core.prompts import PromptTemplate
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
# 核心编排：Agentic RAG 的循环状态机
# ==========================================

# 1. 实例化状态图与依赖字典
workflow = StateGraph(GraphState)

# 2. 注入所有新老节点
workflow.add_node("Router", node_router)
workflow.add_node("Retrieve", node_retrieve)
workflow.add_node("Critique", node_critique)
workflow.add_node("Analyst", node_analyst)
workflow.add_node("Coach", node_coach)

# 3. 构建起流与条件判决边
workflow.add_edge(START, "Router")
workflow.add_edge("Router", "Retrieve")
workflow.add_edge("Retrieve", "Critique")

def decide_to_analyze(state: GraphState):
    """Refine Loop 条件判决逻辑"""
    score = state.get("critique_score", 1.0)
    retries = state.get("retry_count", 0)
    
    if score < 0.7 and retries < 3:
        logger.warning(f"[LangGraph] 🚨 触发 Refine Loop: 检索质量过低 ({score:.2f})，启动第 {retries} 次反思重试！")
        return "Retrieve"
        
    logger.info(f"[LangGraph] ✅ 评判达标 ({score:.2f}) 或超过重试阈值，向后路 Analyst 节点放行。")
    return "Analyst"

# 注入打回循环机制
workflow.add_conditional_edges(
    "Critique",
    decide_to_analyze,
    {
        "Retrieve": "Retrieve",
        "Analyst": "Analyst"
    }
)

workflow.add_edge("Analyst", "Coach")
workflow.add_edge("Coach", END)

# 4. 封装成完整的 App，暴露给外部入口使用
workflow_app = workflow.compile()
