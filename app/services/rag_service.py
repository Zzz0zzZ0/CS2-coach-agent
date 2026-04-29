import logging
from typing import List

from langchain_core.prompts import PromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.vectorstores import VectorStore
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

class KnowledgeBaseClient:
    """
    高级战术检索器 (Advanced RAG System) 的服务封装。
    实现了基于 MMR 的多样性检索，以及基于 LLM 的 PRF 查询重写。
    """

    def __init__(self, vectorstore: VectorStore, llm: BaseChatModel):
        self.vectorstore = vectorstore
        self.llm = llm

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
        complex_query = await self._rewrite_query(query)
        docs = self._hybrid_search(complex_query, metadata_filter)
        if not docs:
            return "暂无匹配的历史上下文数据"
        return "\n---\n".join([doc.page_content for doc in docs])

    async def _rewrite_query(self, original_query: str) -> str:
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

    def _retrieve_with_mmr(self, query: str, metadata_filter: dict = None, k: int = 4, fetch_k: int = 20) -> List[Document]:
        logger.info(f"[MMR] 开始多边际检索 | 过滤: {metadata_filter} | 返回数: {k}")
        try:
            search_kwargs = {"k": k, "fetch_k": fetch_k, "lambda_mult": 0.5}
            if metadata_filter:
                # 适配 Milvus 的 expr 语法 (k == 'v')
                expr_parts = []
                for key, val in metadata_filter.items():
                    if isinstance(val, str):
                        expr_parts.append(f"{key} == '{val}'")
                    else:
                        expr_parts.append(f"{key} == {val}")
                if expr_parts:
                    search_kwargs["expr"] = " and ".join(expr_parts)

            retriever = self.vectorstore.as_retriever(search_type="mmr", search_kwargs=search_kwargs)
            docs = retriever.invoke(query)
            return docs
        except Exception as e:
            logger.error(f"[MMR] 检索时发生异常: {e}")
            return []

    def _sparse_search(self, query: str, docs: List[Document]) -> List[tuple[Document, float]]:
        import re
        import math
        from collections import Counter
        
        query_words = re.findall(r'\w+', query.lower())
        if not query_words:
            return [(d, 0.0) for d in docs]
        
        num_docs = len(docs)
        df = Counter()
        doc_words_list = []
        
        for doc in docs:
            words = re.findall(r'\w+', doc.page_content.lower())
            doc_words_list.append(words)
            for word in set(words):
                df[word] += 1
                
        idf = {}
        for word in query_words:
            idf[word] = math.log((num_docs + 1) / (df[word] + 1)) + 1
            
        scored_docs = []
        for i, doc in enumerate(docs):
            words = doc_words_list[i]
            tf = Counter(words)
            score = 0.0
            for word in query_words:
                tf_score = tf[word] / (len(words) + 1e-6)
                score += tf_score * idf.get(word, 0)
            scored_docs.append((doc, score))
            
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        return scored_docs

    def _hybrid_search(self, query: str, metadata_filter: dict = None, k: int = 4) -> List[Document]:
        logger.info("[HybridSearch] 启动混合检索")
        dense_docs = self._retrieve_with_mmr(query, metadata_filter=metadata_filter, k=k, fetch_k=20)
        
        filter_kwargs = {"where": metadata_filter} if metadata_filter else {}
        try:
            raw_coll = self.vectorstore._collection
            candidate_resp = raw_coll.get(**filter_kwargs)
            candidate_docs = []
            if candidate_resp and candidate_resp.get('ids'):
                for i in range(len(candidate_resp['ids'])):
                    doc = Document(page_content=candidate_resp['documents'][i], metadata=candidate_resp['metadatas'][i])
                    candidate_docs.append(doc)
        except Exception as e:
            logger.warning(f"[HybridSearch] 提取稀疏层候选集失败: {e}，将直接回落至单纯 Dense。")
            return dense_docs

        if not candidate_docs:
            return dense_docs

        sparse_scored = self._sparse_search(query, candidate_docs)
        
        doc_scores = {}
        for rank, doc in enumerate(dense_docs):
            doc_scores[doc.page_content] = {"doc": doc, "score": 1.0 / (60 + rank)}
            
        for rank, (doc, raw_score) in enumerate(sparse_scored[:20]):
            content = doc.page_content
            if content not in doc_scores:
                doc_scores[content] = {"doc": doc, "score": 0.0}
            doc_scores[content]["score"] += 1.0 / (60 + rank)
            
        fused = sorted(doc_scores.values(), key=lambda x: x["score"], reverse=True)
        final_docs = [item["doc"] for item in fused[:k]]
        
        return final_docs
