"""用于报告前的确定性证据完整度检查。"""

import json
from typing import Any

from langchain_core.tools import tool

from app.api.monitor import monitor


@tool
def evaluate_evidence(claims_json: str) -> str:
    """检查候选结论是否携带可追溯来源。

    参数为 JSON 数组，每项至少包含 claim 和 sources；source 应包含 type，公开来源还应包含 url，经营数据应包含 time_range。工具只做确定性完整度检查，不判断事实真假。
    """
    monitor.report_tool("证据完整度检查", {"payload_length": len(claims_json)})
    try:
        claims: list[dict[str, Any]] = json.loads(claims_json)
    except (TypeError, json.JSONDecodeError):
        return "输入必须是候选结论数组的合法 JSON。"
    if not isinstance(claims, list) or not claims:
        return "至少需要提供一条候选结论。"

    review = []
    for index, item in enumerate(claims, start=1):
        sources = item.get("sources", []) if isinstance(item, dict) else []
        issues = []
        types = set()
        if not isinstance(item, dict) or not item.get("claim"):
            issues.append("缺少结论文本")
        if not isinstance(sources, list) or not sources:
            issues.append("没有来源")
            sources = []
        for source in sources:
            if not isinstance(source, dict) or not source.get("type"):
                issues.append("存在未标注类型的来源")
                continue
            source_type = source["type"]
            types.add(source_type)
            if source_type == "公开来源" and not source.get("url"):
                issues.append("公开来源缺少 URL")
            if source_type == "经营数据" and not source.get("time_range"):
                issues.append("经营数据缺少时间范围")
        review.append({"claim_index": index, "source_count": len(sources), "source_types": sorted(types), "status": "needs_evidence" if issues else "traceable", "issues": sorted(set(issues))})
    return json.dumps({"review": review}, ensure_ascii=False)
