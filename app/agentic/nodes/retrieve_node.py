import asyncio
import logging
from typing import Any

from app.agentic.states import GraphState
from app.services.rag_service import KnowledgeBaseClient, RetrievalResult
from app.services.relation_query_service import relation_intent, MESSAGES

logger = logging.getLogger(__name__)


def _evidence_key(item: Any) -> str:
    return item.source_id if hasattr(item, "source_id") else item.get("source_id", "")


def _evidence_score(item: Any) -> float:
    return float(item.score if hasattr(item, "score") else item.get("score", 0.0))


def _evidence_dict(item: Any) -> dict:
    return item.as_dict() if hasattr(item, "as_dict") else item


def _evidence_metadata(item: Any) -> dict:
    return item.metadata if hasattr(item, "metadata") else item.get("metadata", {})


def create_retrieve_node(kb_client, graph_client=None):
    async def node_retrieve(state: GraphState) -> dict:
        logger.info(">>> 执行图节点: [Retrieve] 并行执行分析任务检索...")
        metadata = state.get("retrieval_metadata", {})
        plan = state.get("analysis_plan", [])
        retry_tasks = set(state.get("retrieval_retry_tasks", []))
        tasks = [task for task in plan if not retry_tasks or task["id"] in retry_tasks]
        if not tasks:
            tasks = plan
        if not tasks:
            tasks = [{
                "id": "general",
                "goal": "general tactical review",
                "query": state.get("retrieval_query") or str(state.get("raw_data", ""))[:500],
                "query_variants": state.get("retrieval_queries", []),
                "required_tactic_types": [],
            }]

        relation_plan = any(relation_intent(task["query"]) for task in tasks)
        if relation_plan:
            tasks = plan or tasks  # Re-evaluate the plan; old unverified evidence must not survive a retry.
        feedback = state.get("critique_feedback", "")

        async def retrieve_task(task: dict):
            query = task["query"]
            if relation_intent(query):
                try:
                    if graph_client and hasattr(graph_client, "retrieve_relations"):
                        result = await graph_client.retrieve_relations(query, metadata, 4)
                    else:
                        result = None
                    if result is None:
                        result = RetrievalResult(query=query,rewritten_query=query,strategy="relation_requires_source",
                            warnings=[MESSAGES["unknown"]],relation={"status":"unknown","reason":"graph_unavailable","complete":False})
                except Exception as error:
                    result = RetrievalResult(query=query,rewritten_query=query,strategy="relation_requires_source",
                        warnings=[MESSAGES["unknown"]],relation={"status":"unknown","reason":"source_read_failed","complete":False})
                    logger.warning("Relation source query failed: %s", type(error).__name__)
                return task, result, "", []
            if feedback:
                query = f"{query}. Address these retrieval gaps: {feedback}"
            async def retrieve_milvus():
                if not kb_client:
                    return None, "knowledge base unavailable"
                try:
                    return await kb_client.retrieve(
                        query,
                        metadata_filter=metadata,
                        query_variants=task.get("query_variants", []),
                        k=4,
                        fetch_k=10,
                    ), ""
                except Exception as error:
                    logger.error("[Retrieve] Milvus task %s failed: %s", task["id"], error)
                    return None, type(error).__name__

            async def retrieve_graph():
                if not graph_client or not graph_client.available():
                    return [], ""
                try:
                    return await graph_client.retrieve(
                        query,
                        metadata_filter=metadata,
                        task_id=task["id"],
                        k=4,
                        global_search=task["id"] == "map_context",
                    ), ""
                except Exception as error:
                    logger.error("[Retrieve] Graph task %s failed: %s", task["id"], error)
                    return [], type(error).__name__

            (result, milvus_error), (graph_evidence, graph_error) = await asyncio.gather(
                retrieve_milvus(), retrieve_graph()
            )
            errors = ", ".join(
                f"{name}={value}"
                for name, value in (("milvus", milvus_error), ("graph", graph_error))
                if value
            )
            if result is None and not graph_evidence:
                return task, None, errors or "retrieval unavailable", []
            return task, result, errors, graph_evidence

        task_results = await asyncio.gather(*(retrieve_task(task) for task in tasks))
        evidence_by_key = {
            _evidence_key(item): item
            for item in ([] if relation_plan else state.get("retrieval_evidence", []))
            if _evidence_key(item)
        }
        task_summary = [
            item for item in ([] if relation_plan else state.get("retrieval_task_results", []))
            if item.get("task_id") not in {task["id"] for task in tasks}
        ]
        warnings = []

        graph_count = 0
        for task, result, error, graph_evidence in task_results:
            if error:
                warnings.append(f"{task['id']}: {error}")
            milvus_evidence = result.evidence if result else []
            combined_evidence = [*milvus_evidence, *graph_evidence]
            relation = getattr(result, "relation", None)
            graph_count += len(combined_evidence) if relation else len(graph_evidence)
            for item in combined_evidence:
                evidence_by_key.setdefault(_evidence_key(item), item)
            required_types = set(task.get("required_tactic_types", []))
            graph_topic = {
                "opening_duel": "opening",
                "utility": "utility",
                "round_flow": "round_flow",
                "map_context": "overview",
            }.get(task["id"])
            covered = bool(combined_evidence) if not required_types else (
                any(_evidence_metadata(item).get("tactic_type") in required_types for item in milvus_evidence)
                or any(_evidence_metadata(item).get("topic") == graph_topic for item in graph_evidence)
            )
            if relation:
                covered = relation["status"] in ("found", "not_found")
            task_summary.append({
                "task_id": task["id"],
                "count": len(combined_evidence),
                "milvus_count": 0 if relation else len(milvus_evidence),
                "graph_count": len(combined_evidence) if relation else len(graph_evidence),
                "relation": relation,
                "covered": covered,
                "confidence": result.confidence if result else 0.0,
                "strategy": (result.strategy if result else "graph_only") + ("+graph" if graph_evidence else ""),
                "warnings": result.warnings if result else [],
            })
            warnings.extend(f"{task['id']}: {warning}" for warning in (result.warnings if result else []))

        # Take a small slice from every task first, then fill by global score.
        selected = []
        selected_keys = set()
        for task, result, error, graph_evidence in task_results:
            task_evidence = graph_evidence[:2]
            if result:
                task_evidence = [*result.evidence[:2], *task_evidence]
            for item in task_evidence:
                key = _evidence_key(item)
                if key not in selected_keys:
                    selected.append(item)
                    selected_keys.add(key)
        for item in sorted(evidence_by_key.values(), key=_evidence_score, reverse=True):
            if len(selected) >= 12:
                break
            if _evidence_key(item) not in selected_keys:
                selected.append(item)
                selected_keys.add(_evidence_key(item))

        evidence = [_evidence_dict(item) for item in selected]
        return {
            "rag_context": "\n".join([
                KnowledgeBaseClient.format_evidence_context(evidence),
                *[f"{task['id']}: {result.context}" for task,result,_,_ in task_results
                  if getattr(result,"relation",None) and not result.evidence],
            ]),
            "retrieval_query": "; ".join(task["query"] for task in tasks),
            "retrieval_evidence": evidence,
            "retrieval_task_results": task_summary,
            "retrieval_trace": {
                "filters": metadata,
                "warnings": list(dict.fromkeys(warnings)),
                "evidence_count": len(evidence),
                "graph_evidence_count": graph_count,
                "graph_available": bool(graph_client and graph_client.available()),
                "global_search_tasks": [
                    item["task_id"] for item in task_summary
                    if item["task_id"] == "map_context"
                ],
                "task_coverage": {item["task_id"]: item["covered"] for item in task_summary},
                "task_results": task_summary,
                "retried_tasks": sorted(retry_tasks),
            },
            "retrieval_available": bool(kb_client or graph_client),
            "graph_available": bool(graph_client and graph_client.available()),
            "agent_trace": state.get("agent_trace", []) + [{
                "node": "Retrieve",
                "task_count": len(tasks),
                "parallel": True,
            }],
        }

    return node_retrieve
