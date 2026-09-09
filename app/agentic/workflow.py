import logging
import time
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
from app.core.config import settings

logger = logging.getLogger(__name__)

def create_workflow_app(llm, kb_client, graph_client=None, on_event=None):
    """
    基于依赖注入创建的纯粹无副作用状态机流水线。
    """
    workflow = StateGraph(GraphState)

    # 初始化节点闭包
    auxiliary_llm = llm if settings.LLM_AUXILIARY_CALLS_ENABLED else None
    node_router = create_router_node(auxiliary_llm)
    node_supervisor = create_supervisor_node(auxiliary_llm)
    node_tools = create_tool_node()
    node_retrieve = create_retrieve_node(kb_client, graph_client)
    node_critique = create_critique_node(auxiliary_llm)
    node_analyst = create_analyst_node(llm)
    node_coach = create_coach_node(llm)
    node_verify = create_verify_node()

    attempts = {}

    def observed(name, node):
        async def run(state):
            attempts[name] = attempts.get(name, 0) + 1
            base = {"node": name, "attempt": attempts[name]}
            started = time.monotonic()
            if on_event:
                on_event({**base, "status": "started", "at": time.time()})
            try:
                output = await node(state)
            except BaseException as error:
                if on_event:
                    on_event({**base, "status": "failed", "at": time.time(),
                              "duration_ms": round((time.monotonic()-started)*1000, 2),
                              "error_type": type(error).__name__})
                raise
            if on_event:
                details = {}
                if name == "Tools":
                    details["rounds"] = output.get("metrics", {}).get("rounds_total")
                if name == "Retrieve":
                    trace = output.get("retrieval_trace", {})
                    details = {k: trace[k] for k in ("evidence_count", "graph_available", "task_results") if k in trace}
                if name == "Coach":
                    details = {"selection_source": output.get("coach_decision", {}).get("selection_source"),
                               "usage": output.get("model_usage", {})}
                if name == "Verifier":
                    details["verification_status"] = output.get("verification_report", {}).get("status")
                on_event({**base, "status": "completed", "at": time.time(),
                          "duration_ms": round((time.monotonic()-started)*1000, 2), "details": details})
            return output
        return run

    for name, node in (("Supervisor", node_supervisor), ("Tools", node_tools), ("Router", node_router),
                       ("Retrieve", node_retrieve), ("Critique", node_critique), ("Analyst", node_analyst),
                       ("Coach", node_coach), ("Verifier", node_verify)):
        workflow.add_node(name, observed(name, node))

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
