import logging
from typing import List

from langchain_core.prompts import PromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.vectorstores import VectorStore
from langchain_core.documents import Document

# 配置日志
logger = logging.getLogger(__name__)

class TacticalRetriever:
    """
    高级战术检索器 (Advanced RAG System)
    封装了 LangChain 和 ChromaDB，实现基于 MMR 的多样性检索，
    以及基于 LLM 的 PRF 查询重写。
    """

    def __init__(self, vectorstore: VectorStore, llm: BaseChatModel):
        """
        初始化战术检索器
        
        :param vectorstore: 已初始化的向量数据库实例 (通常为 Chroma 实例)
        :param llm: 用于执行查询重写的大语言模型实例
        """
        self.vectorstore = vectorstore
        self.llm = llm

        # 定义 PRF 查询重写的 Prompt 模板，融入 CS2 相关知识
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

    async def rewrite_query(self, original_query: str) -> str:
        """
        [高级特性 1] PRF (伪相关反馈) 查询重写
        接收简单的查询词，使用 LLM 将其扩展为包含专业术语的复杂查询。
        """
        try:
            logger.info(f"[PRF] 开始查询重写，原始查询: '{original_query}'")
            
            # 使用 LangChain Expression Language (LCEL) 构建执行链
            chain = self.rewrite_prompt | self.llm
            response = await chain.ainvoke({"original_query": original_query})
            
            # 提取 LLM 返回的文本内容
            rewritten_query = response.content if hasattr(response, 'content') else str(response)
            rewritten_query = rewritten_query.strip()
            
            logger.info(f"[PRF] 查询重写成功，扩展后查询: '{rewritten_query}'")
            return rewritten_query
            
        except Exception as e:
            # 异常兜底：若 LLM 扩展失败，则回退使用原查询
            logger.error(f"[PRF] 查询重写失败，退回原始查询。错误信息: {e}")
            return original_query

    def retrieve_with_mmr(self, query: str, metadata_filter: dict = None, k: int = 4, fetch_k: int = 20) -> List[Document]:
        """
        [高级特性 2] MMR (最大边界相关性) 检索
        执行向量检索时强制使用 MMR 算法，在召回的相关性与多样性之间取得平衡，避免由于碎片高度相似导致战术视角单一。
        """
        logger.info(f"[MMR] 开始多边际检索 | Query: '{query}' | 过滤: {metadata_filter} | 返回数(k): {k}")
        
        try:
            search_kwargs = {
                "k": k,
                "fetch_k": fetch_k,
                "lambda_mult": 0.5
            }
            if metadata_filter:
                search_kwargs["filter"] = metadata_filter

            retriever = self.vectorstore.as_retriever(
                search_type="mmr",
                search_kwargs=search_kwargs
            )
            
            docs = retriever.invoke(query)
            logger.info(f"[MMR] 检索完成，共召回 {len(docs)} 条具备多样性的战术片段。")
            return docs
            
        except Exception as e:
            logger.error(f"[MMR] 检索时发生异常: {e}")
            return []

    def _sparse_search(self, query: str, docs: List[Document]) -> List[tuple[Document, float]]:
        """
        Python 原生模拟的 TF-IDF 关键字检索
        计算 query 分词在 docs 中的词频来近似 BM25 打分。
        """
        import re
        import math
        from collections import Counter
        
        # 英文词汇及字母粗略分词
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
                
        # 计算 IDF
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

    def hybrid_search(self, query: str, metadata_filter: dict = None, k: int = 4) -> List[Document]:
        """
        [高级特性 3] 基于 RRF (Reciprocal Rank Fusion) 的混合检索。
        将大模型 Dense MMR 的语义结果与字面稀疏搜索进行倒数加权排序。
        """
        logger.info(f"[HybridSearch] 启动混合检索 | Query: '{query}' | 拦截器: {metadata_filter}")
        # 1. 密集检索 (Dense)
        dense_docs = self.retrieve_with_mmr(query, metadata_filter=metadata_filter, k=k, fetch_k=20)
        
        # 2. 获取元数据隔离后的底层集合
        filter_kwargs = {"where": metadata_filter} if metadata_filter else {}
        try:
            # chroma api
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

        # 3. 稀疏降维打击 (Sparse)
        sparse_scored = self._sparse_search(query, candidate_docs)
        
        # 4. RRF 裁判融合
        doc_scores = {}
        for rank, doc in enumerate(dense_docs):
            doc_scores[doc.page_content] = {"doc": doc, "score": 1.0 / (60 + rank)}
            
        for rank, (doc, raw_score) in enumerate(sparse_scored[:20]): # 截取前20打底
            content = doc.page_content
            if content not in doc_scores:
                doc_scores[content] = {"doc": doc, "score": 0.0}
            doc_scores[content]["score"] += 1.0 / (60 + rank)
            
        fused = sorted(doc_scores.values(), key=lambda x: x["score"], reverse=True)
        final_docs = [item["doc"] for item in fused[:k]]
        
        top_score = fused[0]['score'] if fused else 0
        logger.info(f"[HybridSearch] RRF融合决断完毕 | 归一化夺魁得分: {top_score:.4f} | 最终输出 {len(final_docs)} 条干货。")
        return final_docs
