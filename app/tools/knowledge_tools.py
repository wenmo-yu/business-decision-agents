"""供经营知识助手调用的本地 Hybrid RAG 工具。"""

import json

from langchain_core.tools import tool

from app.api.context import get_thread_context
from app.api.monitor import monitor
from app.rag.hybrid_store import HybridKnowledgeBase
from app.rag.session_store import session_database_path


@tool
def search_internal_knowledge(question: str, limit: int = 5) -> str:
    """从平台自建知识库检索内部资料并返回附来源、分块号和融合分数的原始证据。"""
    monitor.report_tool("内部 Hybrid RAG 检索", {"question": question, "limit": limit})
    try:
        result_limit = max(1, min(limit, 8))
        evidence = [{**item, "scope": "global"} for item in HybridKnowledgeBase().search(question, limit=result_limit)]
        thread_id = get_thread_context()
        if thread_id:
            session_evidence = HybridKnowledgeBase(str(session_database_path(thread_id))).search(question, limit=result_limit)
            evidence.extend({**item, "scope": "session"} for item in session_evidence)
        evidence.sort(key=lambda item: item["rrf_score"], reverse=True)
        evidence = evidence[:result_limit]
        if not evidence:
            return "没有找到足够相关的内部知识证据。请补充资料或调整问题。"
        return json.dumps({"query": question, "evidence": evidence}, ensure_ascii=False)
    except Exception as error:
        return f"内部知识库检索失败：{error}"
