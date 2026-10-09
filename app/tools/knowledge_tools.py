"""供经营知识助手调用的本地 Hybrid RAG 工具。"""

import json

from langchain_core.tools import tool

from app.api.monitor import monitor
from app.rag.hybrid_store import HybridKnowledgeBase


@tool
def search_internal_knowledge(question: str, limit: int = 5) -> str:
    """从平台自建知识库检索内部资料并返回附来源、分块号和融合分数的原始证据。"""
    monitor.report_tool("内部 Hybrid RAG 检索", {"question": question, "limit": limit})
    try:
        evidence = HybridKnowledgeBase().search(question, limit=max(1, min(limit, 8)))
        if not evidence:
            return "内部知识库尚未索引任何资料。请先运行索引命令后再检索。"
        return json.dumps({"query": question, "evidence": evidence}, ensure_ascii=False)
    except Exception as error:
        return f"内部知识库检索失败：{error}"
