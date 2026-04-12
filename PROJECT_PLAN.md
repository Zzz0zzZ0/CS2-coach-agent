# 项目名称：CS2 Multi-Agent Tactical Analysis Service (基于 Webhook 与状态机的战术分析服务)

## 1. 项目愿景与架构概览 (Event-Driven & State-Machine)
本项目是一个生产级 (Production-ready) 的 AI 数据流服务。它通过 FastAPI 监听第三方平台（如 FACEIT Webhook）实时推送的 CS2 赛后 JSON 数据，并利用 LangGraph 构建的复杂状态机，唤醒多智能体工作流（Data Analyst & Tactical Coach）进行深度的战术复盘。

## 2. 核心技术栈 (Resume Highlights)
* **Web 框架:** FastAPI (异步架构，负责 Webhook 接收与高并发处理)
* **多智能体编排:** **LangGraph (StateGraph)** (实现 Agent 间的状态隔离与循环调度)
* **大模型框架:** LangChain (Prompt 模板管理与 LLM 接口调用)
* **高级检索 (Advanced RAG):** ChromaDB (集成 MMR 最大边界相关性与 PRF 查询重写)
* **核心语言:** Python 3.10+ (强制 PEP 8，使用 TypedDict 与异步编程)

## 3. 核心流转机制 (The Workflow)
整个系统被设计为一个异步的流水线：
1. **数据入口 (FastAPI):** `/api/webhook/match-end` 接收 JSON 数据，立即返回 200，将负载推入 `BackgroundTasks`。
2. **状态图初始化 (LangGraph):** 定义全局状态 `GraphState(TypedDict)`，包含原始数据、RAG 上下文、数据报告、战术建议。
3. **图节点执行 (Nodes):**
    * `Node_Retriever`: 解析基础数据，触发高级 RAG 检索历史相似对局的战术解法。
    * `Node_Analyst`: (客观角色) 接收 RAG 上下文，严格计算并提取 ADR、KAST、首杀率等硬核指标。
    * `Node_Coach`: (战术角色) 接收 Analyst 的报告，结合 Map Control、交叉火力等高阶概念，输出最终战术复盘。

## 4. 实施路线图 (Phases)
* **Phase 1: 基础设施搭建** -> 实现 FastAPI Webhook 路由与 Advanced RAG 检索器模块。
* **Phase 2: 核心状态机编排** -> 基于 LangGraph 编写 Agent 节点逻辑，注入极度硬核的 CS2 专属 System Prompts。
* **Phase 3: 系统集成与测试** -> 使用 Mock JSON 测试 Webhook 触发整个图的流转，并在终端打印战术报告