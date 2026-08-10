import logging
from langgraph.graph import StateGraph, START, END

from app.agentic.states import GraphState
from app.agentic.nodes.router_node import create_router_node
from app.agentic.nodes.retrieve_node import create_retrieve_node
from app.agentic.nodes.critique_node import create_critique_node
from app.agentic.nodes.analyst_node import create_analyst_node
from app.agentic.nodes.coach_node import create_coach_node
from app.agentic.nodes.verify_node import create_verify_node
from app.agentic.nodes.supervisor_node import create_supervisor_node
from app.agentic.nodes.tool_node import create_tool_node

logger = logging.getLogger(__name__)

def create_workflow_app(llm, kb_client, graph_client=None):
    """
    基于依赖注入创建的纯粹无副作用状态机流水线。
    """
    workflow = StateGraph(GraphState)

    # 初始化节点闭包
    node_router = create_router_node(llm)
    node_supervisor = create_supervisor_node(llm)
    node_tools = create_tool_node()
    node_retrieve = create_retrieve_node(kb_client, graph_client)
    node_critique = create_critique_node(llm)
    node_analyst = create_analyst_node(llm)
    node_coach = create_coach_node(llm)
    node_verify = create_verify_node()

    # 注入节点
    workflow.add_node("Supervisor", node_supervisor)
    workflow.add_node("Tools", node_tools)
    workflow.add_node("Router", node_router)
    workflow.add_node("Retrieve", node_retrieve)
    workflow.add_node("Critique", node_critique)
    workflow.add_node("Analyst", node_analyst)
    workflow.add_node("Coach", node_coach)
    workflow.add_node("Verifier", node_verify)

    # 构建边
    workflow.add_edge(START, "Supervisor")
    workflow.add_edge("Supervisor", "Tools")
    workflow.add_edge("Tools", "Router")
    workflow.add_edge("Router", "Retrieve")
    workflow.add_edge("Retrieve", "Critique")

    def decide_to_analyze(state: GraphState):
        score = state.get("critique_score", 0.0)
        retries = state.get("retry_count", 0)

        if not state.get("retrieval_available", True):
            logger.warning("[LangGraph] 知识库不可用，跳过检索重试并继续确定性数据分析。")
            return "Analyst"
        
        retry_tasks = state.get("retrieval_retry_tasks", [])
        if score < 0.7 and retries < 3 and retry_tasks:
            logger.warning(f"[LangGraph] 🚨 触发 Refine Loop: 检索质量过低 ({score:.2f})，启动第 {retries} 次反思重试！")
            return "Retrieve"
            
        logger.info(f"[LangGraph] ✅ 评判达标 ({score:.2f}) 或超过重试阈值，向后路 Analyst 节点放行。")
        return "Analyst"

    workflow.add_conditional_edges(
        "Critique",
        decide_to_analyze,
        {
            "Retrieve": "Retrieve",
            "Analyst": "Analyst"
        }
    )

    workflow.add_edge("Analyst", "Coach")
    workflow.add_edge("Coach", "Verifier")
    workflow.add_edge("Verifier", END)

    return workflow.compile()
