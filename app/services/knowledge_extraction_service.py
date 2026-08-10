import logging
from typing import List
from pydantic import BaseModel, Field
from langchain_core.prompts import PromptTemplate
from langchain_core.documents import Document
from langchain_core.output_parsers import PydanticOutputParser

logger = logging.getLogger(__name__)

class TacticInfo(BaseModel):
    map_name: str = Field(description="涉及的地图名称，如 Mirage, Inferno, Dust2。如果没有具体地图，填 General")
    side: str = Field(description="T, CT, 或者 Both")
    tactic_type: str = Field(description="战术类型，如 Mid Control, Exec, Retake, Slow Play 等")
    content: str = Field(description="战术的具体内容，保留战术术语和核心逻辑，要求精确且易于检索")

class ExtractionResult(BaseModel):
    tactics: List[TacticInfo] = Field(description="从文本中提取出的所有战术列表")

class KnowledgeExtractionService:
    def __init__(self, llm, kb_client):
        self.llm = llm
        self.kb_client = kb_client
        self.parser = PydanticOutputParser(pydantic_object=ExtractionResult)
        
        self.prompt = PromptTemplate(
            template="你是一个 CS2 职业战术分析师。请从以下文本中提取出所有有价值的战术片段。\n"
                     "{format_instructions}\n\n"
                     "原始文本：\n{source_text}\n",
            input_variables=["source_text"],
            partial_variables={"format_instructions": self.parser.get_format_instructions()},
        )

    def process_and_ingest(self, source_text: str, source_name: str) -> int:
        """
        处理原始文本并同步插入向量库 (在 Celery 任务中通常使用同步调用)
        """
        logger.info(f"开始提取战术信息，来源: {source_name}")
        chain = self.prompt | self.llm | self.parser
        
        try:
            result = chain.invoke({"source_text": source_text})
        except Exception as e:
            logger.error(f"提取战术信息失败: {e}")
            raise e
            
        docs = []
        for tac in result.tactics:
            doc = Document(
                page_content=f"[{tac.map_name} {tac.tactic_type}] {tac.content}",
                metadata={
                    "map": tac.map_name,
                    "side": tac.side,
                    "tactic_type": tac.tactic_type,
                    "source": source_name
                }
            )
            docs.append(doc)
            
        if not docs:
            logger.info("未提取到任何有效战术")
            return 0
            
        try:
            self.kb_client.vectorstore.add_documents(docs)
            logger.info(f"成功将 {len(docs)} 条战术入库。")
            return len(docs)
        except Exception as e:
            logger.error(f"入库失败: {e}")
            raise e
