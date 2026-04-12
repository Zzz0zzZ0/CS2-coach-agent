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

    def retrieve_with_mmr(self, query: str, k: int = 4, fetch_k: int = 20) -> List[Document]:
        """
        [高级特性 2] MMR (最大边界相关性) 检索
        执行向量检索时强制使用 MMR 算法，在召回的相关性与多样性之间取得平衡，避免由于碎片高度相似导致战术视角单一。
        
        :param query: 用户的查询语句或 PRF 扩展后的查询语句
        :param k: 最终返回的战术片段数量
        :param fetch_k: 从向量数据库中初次拉取的候选池大小，保证充足的多样性选择空间
        """
        logger.info(f"[MMR] 开始多边际检索 | Query: '{query}' | 返回数(k): {k} | 候选池大小(fetch_k): {fetch_k}")
        
        try:
            # 将底层 Retriever 强制配置为 MMR (Maximal Marginal Relevance) 模式
            retriever = self.vectorstore.as_retriever(
                search_type="mmr",
                search_kwargs={
                    "k": k,
                    "fetch_k": fetch_k,
                    "lambda_mult": 0.5  # 0.5 代表在相关性和多样性之间五五开
                }
            )
            
            docs = retriever.invoke(query)
            logger.info(f"[MMR] 检索完成，共召回 {len(docs)} 条具备多样性的战术片段。")
            return docs
            
        except Exception as e:
            logger.error(f"[MMR] 检索时发生异常: {e}")
            return []
