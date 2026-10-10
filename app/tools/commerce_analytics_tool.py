"""电商问数服务适配器，兼容现有 SSE 接口与未来的 JSON 汇总接口。"""

import json
import os
from typing import Any

import requests
from langchain_core.tools import tool

from app.api.context import get_thread_context
from app.api.monitor import monitor


SUCCESS_STATUSES = {"success", "succeeded", "completed", "ok"}


def _bounded(value: Any, *, max_items: int = 50, max_text: int = 2_000) -> tuple[Any, bool]:
    """在数据结构内截断，永远返回可序列化的完整 JSON。"""
    if isinstance(value, str):
        return value[:max_text], len(value) > max_text
    if isinstance(value, list):
        items, truncated = [], len(value) > max_items
        for item in value[:max_items]:
            bounded, item_truncated = _bounded(item, max_items=max_items, max_text=max_text)
            items.append(bounded)
            truncated = truncated or item_truncated
        return items, truncated
    if isinstance(value, dict):
        result, truncated = {}, False
        for key, item in value.items():
            bounded, item_truncated = _bounded(item, max_items=max_items, max_text=max_text)
            result[key] = bounded
            truncated = truncated or item_truncated
        return result, truncated
    return value, False


def _consume_sse(response: requests.Response) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line or not raw_line.startswith("data:"):
            continue
        raw_data = raw_line.removeprefix("data:").strip()
        try:
            event = json.loads(raw_data)
        except json.JSONDecodeError:
            event = {"type": "unparsed", "message": raw_data}
        if isinstance(event, dict) and event.get("type") == "error":
            return {"execution_status": "failed", "data": events, "error": event.get("message", "问数服务返回错误")}
        events.append(event if isinstance(event, dict) else {"type": "data", "data": event})
    bounded_events, truncated = _bounded(events)
    return {"execution_status": "completed", "data": bounded_events, "truncated": truncated, "limitations": "上游当前仅提供 SSE 事件流；未提供标准化的最终结果、时间范围和 SQL 审计字段。"}


@tool
def commerce_analytics_query(question: str, context: str = "") -> str:
    """查询独立问数项目，只消费其只读执行后的结果，不暴露 SQL 执行能力。"""
    monitor.report_tool("经营问数服务", {"question": question, "has_context": bool(context)})
    base_url = os.getenv("ECOM_ANALYTICS_API_URL", "").rstrip("/")
    protocol = os.getenv("ECOM_ANALYTICS_PROTOCOL", "sse").lower()
    if not base_url:
        return "经营问数服务未配置。请设置 ECOM_ANALYTICS_API_URL。"

    try:
        if protocol == "sse":
            response = requests.post(f"{base_url}/api/query", json={"query": question, "session_id": get_thread_context() or "decision-platform"}, headers={"Accept": "text/event-stream"}, stream=True, timeout=float(os.getenv("ECOM_ANALYTICS_TIMEOUT_SECONDS", "60")))
            response.raise_for_status()
            payload = _consume_sse(response)
        elif protocol == "json":
            response = requests.post(f"{base_url}/api/analytics/query", json={"question": question, "context": context, "caller": "business_decision_agents"}, timeout=float(os.getenv("ECOM_ANALYTICS_TIMEOUT_SECONDS", "30")))
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or "data" not in payload or "execution_status" not in payload:
                return "经营问数 JSON 接口响应缺少 data 或 execution_status。"
            if str(payload["execution_status"]).lower() not in SUCCESS_STATUSES:
                return f"经营问数服务执行失败：{payload.get('error') or payload.get('message') or payload['execution_status']}"
            payload, truncated = _bounded(payload)
            payload["upstream_execution_status"] = payload["execution_status"]
            payload["execution_status"] = "completed"
            payload["truncated"] = truncated
        else:
            return "ECOM_ANALYTICS_PROTOCOL 仅支持 sse 或 json。"
    except requests.RequestException as error:
        return f"经营问数服务调用失败：{error}"
    except ValueError:
        return "经营问数服务返回了非 JSON 响应。"

    if payload["execution_status"] != "completed":
        return f"经营问数服务执行失败：{payload.get('error', payload['execution_status'])}"
    return json.dumps(payload, ensure_ascii=False, default=str)
