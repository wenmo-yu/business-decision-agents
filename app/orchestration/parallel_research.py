"""有依赖意识的并行研究入口。

市场、经营问数和内部知识彼此没有数据依赖时用 TaskGroup 并发；证据审查必须
在该工具返回后再执行，避免审查一个尚未完整的证据集。
"""

from __future__ import annotations

import asyncio
import json
from time import perf_counter

from langchain_core.tools import tool

from app.context_engineering.runtime import budget_snapshot, trace
from app.tools.commerce_analytics_tool import commerce_analytics_query
from app.tools.knowledge_tools import search_internal_knowledge
from app.tools.tavily_tool import internet_search


@tool
async def parallel_research(
    question: str,
    include_market: bool = True,
    include_analytics: bool = True,
    include_knowledge: bool = True,
) -> str:
    """并行收集市场、经营数据和内部知识证据，返回结构化专家结果及证据编号。

    适合需要跨源归因的问题。不要在本工具未完成前审查结论；返回后把候选结论和
    evidence_id 交给证据审查助手。可关闭与问题无关的数据源以节省预算。
    """
    started = perf_counter()
    trace("parallel_research_started", question=question, market=include_market, analytics=include_analytics, knowledge=include_knowledge)
    jobs: dict[str, asyncio.Task] = {}
    async with asyncio.TaskGroup() as group:
        if include_market:
            jobs["market_intelligence"] = group.create_task(asyncio.to_thread(internet_search.invoke, {"query": question, "topic": "general", "max_results": 5}))
        if include_analytics:
            jobs["commerce_analytics"] = group.create_task(asyncio.to_thread(commerce_analytics_query.invoke, {"question": question}))
        if include_knowledge:
            jobs["knowledge_base"] = group.create_task(asyncio.to_thread(search_internal_knowledge.invoke, {"question": question, "limit": 5}))
    results = {name: task.result() for name, task in jobs.items()}
    payload = {
        "question": question,
        "experts": results,
        "dependency": "evidence_review must run after these evidence-producing experts",
        "elapsed_ms": round((perf_counter() - started) * 1000, 1),
        "budget": budget_snapshot(),
    }
    trace("parallel_research_finished", experts=list(results), elapsed_ms=payload["elapsed_ms"])
    return json.dumps(payload, ensure_ascii=False, default=str)
