"""多智能体经营决策平台到独立电商智能问数服务的受控适配器。"""

import json
import os

import requests
from langchain_core.tools import tool

from app.api.monitor import monitor


@tool
def commerce_analytics_query(question: str, context: str = "") -> str:
    """查询已校验的电商经营数据，不直接暴露数据库或 SQL 执行能力。

    服务应提供 POST /api/analytics/query，返回 data、metric_definition、time_range、
    execution_status、sql_audit（脱敏 SQL/校验结果）和 limitations 字段。
    """
    monitor.report_tool("经营问数服务", {"question": question, "has_context": bool(context)})
    base_url = os.getenv("ECOM_ANALYTICS_API_URL", "").rstrip("/")
    if not base_url:
        return "经营问数服务未配置。请设置 ECOM_ANALYTICS_API_URL；该服务应来自独立的电商智能问数项目，且只允许经过校验的只读查询。"

    try:
        response = requests.post(
            f"{base_url}/api/analytics/query",
            json={"question": question, "context": context, "caller": "commerce_compass"},
            timeout=float(os.getenv("ECOM_ANALYTICS_TIMEOUT_SECONDS", "30")),
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as error:
        return f"经营问数服务调用失败：{error}"
    except ValueError:
        return "经营问数服务返回了非 JSON 响应，不能将其作为业务事实使用。"

    required = {"data", "execution_status"}
    missing = sorted(required - payload.keys()) if isinstance(payload, dict) else required
    if missing:
        return f"经营问数服务响应缺少必要字段：{', '.join(missing)}"
    return json.dumps(payload, ensure_ascii=False, default=str)[:12000]
