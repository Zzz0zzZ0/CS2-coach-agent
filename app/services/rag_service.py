import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from langchain_core.prompts import PromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.vectorstores import VectorStore
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

QUERY_EXPANSIONS = {
    "猎鹰": "falcons",
    "绿龙": "spirit",
    "蜜蜂": "vitality",
    "黑豹": "furia",
    "老鼠": "mouz",
    "荒漠迷城": "mirage",
    "首杀": "opening duel first kill",
    "道具": "utility grenade grenades",
    "烟闪火": "smoke flash molotov utility",
    "闪光": "flash",
    "烟雾": "smoke",
    "投掷物": "utility grenade grenades",
    "下包": "bomb plant",
    "回防": "retake",
    "职业录像": "professional demo",
}
MAP_TERMS = {
    "ancient", "anubis", "cache", "dust2", "inferno", "mirage", "nuke",
    "overpass", "vertigo",
}
TEAM_TERMS = {"falcons", "spirit", "vitality", "furia", "mouz"}
DOMAIN_TERMS = MAP_TERMS | TEAM_TERMS | {
    "cs2", "counter-strike", "grenade", "molotov", "retake", "post-plant",
}
# Grammar words are not entity names, even next to a map or "performance".
ENTITY_GRAMMAR = DOMAIN_TERMS | {
    "show", "review", "analyze", "analyse", "compare", "comparison", "summarize",
    "player", "players", "team", "teams", "performance", "profile", "stats",
    "statistics", "on", "in", "at", "for", "of", "and", "versus", "vs", "against",
    "the", "a", "an", "my", "their", "his", "her", "recent", "overall",
    "professional", "match", "matches", "map", "round", "rounds", "demo",
    "opening", "duel", "first", "kill", "kills", "utility", "smoke", "flash",
    "bomb", "plant", "trade", "execute", "tactical", "evidence", "summary",
    "t", "ct", "side", "win", "rate", "context", "control",
}


def contains_entity(text: str, entity: str) -> bool:
    """Match a complete handle, not a substring inside another name or ID."""
    return bool(re.search(rf"(?<![a-z0-9_$-]){re.escape(entity)}(?![a-z0-9_$-])", text.lower()))


def explicit_entity_terms(query: str) -> list[str]:
    """Extract ASCII subjects from map, profile, opponent and comparison syntax.

    This is a bounded query grammar, not general-purpose named entity recognition.
    Unknown subjects must remain constraints instead of becoming optional keywords.
    """
    lowered = query.lower()
    handle = r"(?<![a-z0-9_$-])([a-z0-9_$-]{2,32})(?![a-z0-9_$-])"
    maps = r"(?:de_)?(?:" + "|".join(sorted(MAP_TERMS)) + r")(?![a-z0-9_])"
    patterns = [
        r"^(?:(?:show|review|analyze|analyse|summarize)\s+)?"
        + handle + r"\s+(?:(?:在|on|in)\s+)?" + maps,
        handle + r"\s+在\s+" + maps,
        handle + r"(?:['’]s)?\s+(?:(?:player|team)\s+)?(?:performance|profile|stats|statistics)\b",
        r"\b(?:player|team|against|versus|vs|compare)\s+" + handle,
        r"\b(?:and)\s+" + handle + r"(?=\s+(?:on|in)\s+" + maps + r")",
    ]
    if re.search(r"\bcompar(?:e|ison)\b", lowered):
        patterns.append(r"\band\s+" + handle)
    terms = []
    for pattern in patterns:
        for match in re.finditer(pattern, lowered):
            term = match.group(1)
            if term not in ENTITY_GRAMMAR and not term.isdigit() and term not in terms:
                terms.append(term)
    # Canonical team names are also valid subjects; only grammar words are excluded.
    for name in sorted(TEAM_TERMS):
        if contains_entity(lowered, name):
            terms.append(name)
    for alias, expansion in QUERY_EXPANSIONS.items():
        if alias in query and expansion in TEAM_TERMS:
            terms.append(expansion)
    return list(dict.fromkeys(terms))


class MilvusHybridSearcher:
    """Small adapter for Milvus native dense + BM25 retrieval."""

    def __init__(self, client: Any, collection_name: str, embeddings: Any):
        self.client = client
        self.collection_name = collection_name
        self.embeddings = embeddings

    def search(self, query: str, expr: str | None, limit: int) -> List[Tuple[Document, float]]:
        from pymilvus import AnnSearchRequest, RRFRanker

        dense_request = AnnSearchRequest(
            data=[self.embeddings.embed_query(query)],
            anns_field="vector",
            param={"metric_type": "COSINE", "params": {}},
            limit=limit,
            filter=expr,
        )
        sparse_request = AnnSearchRequest(
            data=[query],
            anns_field="sparse",
            param={"metric_type": "BM25", "params": {}},
            limit=limit,
            filter=expr,
        )
        hits = self.client.hybrid_search(
            collection_name=self.collection_name,
            reqs=[dense_request, sparse_request],
            ranker=RRFRanker(),
            limit=limit,
            output_fields=[
                "map",
                "side",
                "tactic_type",
                "source",
                "match_id",
                "round_number",
                "parent_id",
                "context_level",
                "parent_content",
                "text",
            ],
        )
        rows = hits[0] if hits and isinstance(hits[0], list) else hits
        result = []
        for hit in rows or []:
            entity = hit.get("entity", {})
            content = entity.get("text", "")
            if not content:
                continue
            metadata = {
                key: entity.get(key)
                for key in (
                    "map",
                    "side",
                    "tactic_type",
                    "source",
                    "match_id",
                    "round_number",
                    "parent_id",
                    "context_level",
                    "parent_content",
                )
                if entity.get(key) is not None
            }
            result.append(
                (
                    Document(page_content=content, metadata=metadata),
                    float(hit.get("distance", hit.get("score", 0.0))),
                )
            )
        return result


@dataclass(frozen=True)
class Evidence:
    """One traceable knowledge-base hit returned to the agent graph."""

    content: str
    metadata: Dict[str, Any]
    score: float
    source_id: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "metadata": self.metadata,
            "score": self.score,
            "source_id": self.source_id,
        }


@dataclass
class RetrievalResult:
    """Structured retrieval output; callers may still use ``context``."""

    query: str
    rewritten_query: str
    filters: Dict[str, Any] = field(default_factory=dict)
    evidence: List[Evidence] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    strategy: str = "dense_lexical"
    confidence: float = 0.0
    corrected: bool = False

    @property
    def context(self) -> str:
        return KnowledgeBaseClient.format_evidence_context(self.evidence)


class KnowledgeBaseClient:
    """
    战术检索器的服务封装。
    实现了基于 MMR 的多样性检索，以及基于 LLM 的查询重写。
    """

    @staticmethod
    def format_evidence_context(evidence: List[Any]) -> str:
        """Format one or many evidence objects with stable global citations."""
        if not evidence:
            return "暂无匹配的历史上下文数据"
        blocks = []
        for index, item in enumerate(evidence, start=1):
            metadata = item.metadata if hasattr(item, "metadata") else item.get("metadata", {})
            content = item.content if hasattr(item, "content") else item.get("content", "")
            source_id = item.source_id if hasattr(item, "source_id") else item.get("source_id", "unknown")
            score = item.score if hasattr(item, "score") else item.get("score", 0.0)
            source = metadata.get("source", source_id)
            location = "/".join(
                str(value)
                for value in (
                    metadata.get("map"),
                    metadata.get("match_id"),
                    metadata.get("round_number"),
                )
                if value not in (None, "", "0")
            )
            blocks.append(
                f"[E{index}] source={source} location={location or 'unknown'} "
                f"type={metadata.get('tactic_type', 'unknown')} score={score:.3f}\n"
                + (
                    f"Parent context: {metadata['parent_content']}\n"
                    if metadata.get("parent_content") and metadata["parent_content"] != content
                    else ""
                )
                + content
            )
        return "\n---\n".join(blocks)

    def __init__(self, vectorstore: VectorStore, llm: BaseChatModel, hybrid_searcher: Any = None):
        self.vectorstore = vectorstore
        self.llm = llm
        self.hybrid_searcher = hybrid_searcher

        self.rewrite_prompt = PromptTemplate(
            input_variables=["original_query"],
            template=(
                "你是一个 CS2 (反恐精英2) 的战术分析专家。你的任务是将用户的口语化查询转换成包含专业术语的强力搜索引擎查询。\n"
                "请将以下普通查询改写为至少包含某些具体 CS2 战术术语（如 crossfire, default, map control, trade kill, flash assist, lurk, execute 等）的复杂查询词，"
                "以便从向量数据库中精准检索到相关的战术复盘片段。\n\n"
                "原始查询: {original_query}\n"
                "仅输出改写后的查询语句，不要包含任何多余的解释或前后缀："
            )
        )

    async def fetch_tactical_context(self, query: str, metadata_filter: dict = None) -> str:
        """
        供 Agent 调用的高层接口，屏蔽了底层的 PRF 和 MMR 逻辑
        """
        result = await self.retrieve(query, metadata_filter=metadata_filter)
        return result.context

    async def retrieve(
        self,
        query: str,
        metadata_filter: dict = None,
        query_variants: List[str] = None,
        k: int = 6,
        fetch_k: int = 12,
    ) -> RetrievalResult:
        """Retrieve ranked, deduplicated evidence while keeping provenance."""
        normalized_filters = self._normalize_filters(metadata_filter or {})
        expanded_query = self._expand_query(query)
        required_entities = explicit_entity_terms(query)
        has_context = normalized_filters.get("map") or normalized_filters.get("match_id")
        if not has_context and not self._has_domain_signal(expanded_query) and not required_entities:
            return RetrievalResult(
                query=query,
                rewritten_query=expanded_query,
                filters=normalized_filters,
                warnings=["query rejected: no CS2 domain signal"],
                strategy="hybrid_rrf" if self.hybrid_searcher else "dense_lexical",
            )
        rewritten_query = await self._rewrite_query(expanded_query)
        variants = self._unique_queries([rewritten_query, expanded_query, *(query_variants or [])])
        candidates: Dict[str, Dict[str, Any]] = {}
        errors = []
        strategy = "hybrid_rrf" if self.hybrid_searcher else "dense_lexical"

        async def collect(search_variants: List[str], search_limit: int) -> None:
            for variant_index, variant in enumerate(search_variants):
                try:
                    hits = await self._search_variant(variant, normalized_filters, search_limit)
                except Exception as error:
                    logger.warning("[RAG] query variant failed: %s", error)
                    errors.append(f"query variant failed: {type(error).__name__}")
                    continue

                for rank, (document, raw_score) in enumerate(hits, start=1):
                    key = self._evidence_key(document)
                    lexical_score = self._lexical_score(variant, document)
                    parent_bonus = 0.08 if document.metadata.get("parent_content") else 0.0
                    rank_score = lexical_score * 0.62 + (1.0 / (rank + 1)) * 0.3 + parent_bonus
                    candidate = candidates.setdefault(
                        key,
                        {
                            "document": document,
                            "rank_score": 0.0,
                            "raw_score": float(raw_score),
                            "variant_index": variant_index,
                            "lexical_score": 0.0,
                        },
                    )
                    candidate["rank_score"] = max(candidate["rank_score"], rank_score)
                    candidate["lexical_score"] = max(candidate["lexical_score"], lexical_score)

        await collect(variants, min(fetch_k, 20))
        initial_count = len(candidates)
        top_score = max((item["rank_score"] for item in candidates.values()), default=0.0)
        top_lexical = max((item["lexical_score"] for item in candidates.values()), default=0.0)
        corrected = initial_count == 0 or top_score < 0.22 or top_lexical < 0.05
        if corrected:
            corrected_query = f"professional CS2 demo evidence tactical event {query}"
            await collect([corrected_query], min(fetch_k * 2, 40))
            if initial_count == 0 and not candidates:
                errors.append("corrective retrieval returned no evidence")

        ranked = sorted(
            candidates.values(),
            key=lambda item: item["rank_score"],
            reverse=True,
        )
        if required_entities:
            ranked = [
                item for item in ranked
                if all(contains_entity(" ".join([
                    item["document"].page_content,
                    *map(str, item["document"].metadata.values()),
                ]), entity) for entity in required_entities)
            ]
            if not ranked:
                errors.append("explicit entities not found in evidence: " + ", ".join(required_entities))
        evidence = []
        for item in ranked[:k]:
            document = item["document"]
            evidence.append(
                Evidence(
                    content=document.page_content,
                    metadata=dict(document.metadata),
                    score=float(item["rank_score"]),
                    source_id=self._evidence_key(document),
                )
            )

        confidence = min(1.0, max((item.score for item in evidence), default=0.0))
        return RetrievalResult(
            query=query,
            rewritten_query=rewritten_query,
            filters=normalized_filters,
            evidence=evidence,
            warnings=list(dict.fromkeys(errors)),
            strategy=strategy,
            confidence=confidence,
            corrected=corrected,
        )

    async def _search_variant(
        self, query: str, metadata_filter: Dict[str, Any], limit: int
    ) -> List[Tuple[Document, float]]:
        expression = self._metadata_expr(metadata_filter)
        if self.hybrid_searcher:
            return await asyncio.to_thread(self.hybrid_searcher.search, query, expression, limit)
        kwargs = {"k": limit}
        if expression:
            kwargs["expr"] = expression
        return await asyncio.to_thread(
            self.vectorstore.similarity_search_with_score,
            query,
            **kwargs,
        )

    async def _rewrite_query(self, original_query: str) -> str:
        if not self.llm:
            return original_query
        try:
            logger.info(f"[PRF] 开始查询重写，原始查询: '{original_query[:50]}...'")
            chain = self.rewrite_prompt | self.llm
            response = await chain.ainvoke({"original_query": original_query})
            
            rewritten_query = response.content if hasattr(response, 'content') else str(response)
            rewritten_query = rewritten_query.strip()
            
            logger.info(f"[PRF] 查询重写成功，扩展后查询: '{rewritten_query}'")
            return rewritten_query
        except Exception as e:
            logger.error(f"[PRF] 查询重写失败，退回原始查询。错误信息: {e}")
            return original_query

    @staticmethod
    def _unique_queries(queries: List[str]) -> List[str]:
        result = []
        seen = set()
        for query in queries:
            value = str(query or "").strip()
            if value and value.lower() not in seen:
                seen.add(value.lower())
                result.append(value)
        return result or ["CS2 tactical review"]

    @staticmethod
    def _expand_query(query: str) -> str:
        additions = [
            expansion for alias, expansion in QUERY_EXPANSIONS.items()
            if alias in query
        ]
        return " ".join([query, *additions]).strip()

    @staticmethod
    def _has_domain_signal(query: str) -> bool:
        terms = set(re.findall(r"[a-z0-9_-]+", query.lower()))
        return bool(terms & DOMAIN_TERMS) or bool(re.search(
            r"\b(?:opening duel|first kill|trade kill|bomb plant|flash assist)\b", query.lower()
        ))

    @staticmethod
    def _normalize_filters(metadata_filter: Dict[str, Any]) -> Dict[str, Any]:
        filters = dict(metadata_filter)
        map_name = filters.get("map")
        if isinstance(map_name, str) and map_name.lower().startswith("de_"):
            filters["map"] = {
                "de_ancient": "Ancient",
                "de_dust2": "Dust2",
                "de_inferno": "Inferno",
                "de_mirage": "Mirage",
                "de_nuke": "Nuke",
                "de_overpass": "Overpass",
                "de_vertigo": "Vertigo",
            }.get(map_name.lower(), map_name[3:].title())
        return filters

    @staticmethod
    def _metadata_expr(metadata_filter: Dict[str, Any]) -> str | None:
        if not metadata_filter:
            return None
        parts = []
        for key, value in metadata_filter.items():
            if isinstance(value, str):
                escaped = value.replace("\\", "\\\\").replace("'", "\\'")
                parts.append(f"{key} == '{escaped}'")
            else:
                parts.append(f"{key} == {value}")
        return " and ".join(parts)

    @staticmethod
    def _evidence_key(document: Document) -> str:
        metadata = document.metadata
        return "|".join(
            str(value)
            for value in (
                metadata.get("source", "unknown"),
                metadata.get("map", "unknown"),
                metadata.get("round_number", "0"),
                metadata.get("tactic_type", "unknown"),
                document.page_content,
            )
        )

    @staticmethod
    def _lexical_score(query: str, document: Document) -> float:
        tokens = set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", query.lower()))
        if not tokens:
            return 0.0
        haystack = " ".join(
            [document.page_content.lower()]
            + [str(value).lower() for value in document.metadata.values()]
        )
        return sum(token in haystack for token in tokens) / len(tokens)

    def _retrieve_with_mmr(self, query: str, metadata_filter: dict = None, k: int = 4, fetch_k: int = 20) -> List[Document]:
        logger.info(f"[MMR] 开始多边际检索 | 过滤: {metadata_filter} | 返回数: {k}")
        try:
            normalized_filters = self._normalize_filters(metadata_filter or {})
            search_kwargs = {"k": k, "fetch_k": fetch_k, "lambda_mult": 0.5}
            expression = self._metadata_expr(normalized_filters)
            if expression:
                search_kwargs["expr"] = expression

            retriever = self.vectorstore.as_retriever(search_type="mmr", search_kwargs=search_kwargs)
            docs = retriever.invoke(query)
            return docs
        except Exception as e:
            logger.error(f"[MMR] 检索时发生异常: {e}")
            return []
