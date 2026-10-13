"""用于报告前的确定性证据完整度检查。"""

import json
import re
from typing import Any
from urllib.parse import urlparse

from langchain_core.tools import tool

from app.api.monitor import monitor
from app.context_engineering.runtime import get_evidence, trace


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
            if source_type == "公开来源":
                url = str(source.get("url", ""))
                if urlparse(url).scheme not in {"http", "https"} or not urlparse(url).netloc:
                    issues.append("公开来源缺少有效 URL")
                if not source.get("published_at"):
                    issues.append("公开来源缺少发布日期")
            if source_type == "经营数据":
                if not source.get("time_range"):
                    issues.append("经营数据缺少时间范围")
                if not source.get("metric_definition"):
                    issues.append("经营数据缺少指标口径")
            if source_type == "内部材料":
                if not source.get("source"):
                    issues.append("内部材料缺少来源文件")
                if not isinstance(source.get("chunk_index"), int):
                    issues.append("内部材料缺少分块编号")
                if not source.get("content_excerpt"):
                    issues.append("内部材料缺少原文摘录")
        review.append({"claim_index": index, "source_count": len(sources), "source_types": sorted(types), "status": "needs_evidence" if issues else "citation_complete", "issues": sorted(set(issues))})
    trace("citation_completeness_reviewed", claims=len(review), incomplete=sum(item["status"] != "citation_complete" for item in review))
    return json.dumps({"review": review}, ensure_ascii=False)


@tool
def verify_claim_support(claims_json: str) -> str:
    """做结论级证据校验，而非只检查来源字段。

    输入为数组，每项应含 claim、evidence_ids 和可选 evidence_quote。evidence_ids 必须是
    本轮专家工具返回的编号。返回 direct/partial/conflicting/insufficient；其中 direct
    仅表示引用原文与关键数字可核对，不把相关性伪装成因果证明。
    """
    monitor.report_tool("结论级证据校验", {"payload_length": len(claims_json)})
    try:
        claims = json.loads(claims_json)
    except (TypeError, json.JSONDecodeError):
        return "输入必须是候选结论数组的合法 JSON。"
    if not isinstance(claims, list) or not claims:
        return "至少需要提供一条候选结论。"

    causal_words = ("导致", "因为", "造成", "归因", "因果", "cause")
    review = []
    for index, item in enumerate(claims, start=1):
        claim = str(item.get("claim", "")) if isinstance(item, dict) else ""
        evidence_ids = item.get("evidence_ids", []) if isinstance(item, dict) else []
        quote = str(item.get("evidence_quote", "")) if isinstance(item, dict) else ""
        found = [get_evidence(str(evidence_id)) for evidence_id in evidence_ids] if isinstance(evidence_ids, list) else []
        found = [entry for entry in found if entry]
        issues: list[str] = []
        if not claim:
            issues.append("缺少结论文本")
        if not evidence_ids:
            issues.append("未关联本轮 evidence_id")
        if len(found) != len(evidence_ids):
            issues.append("存在未在本轮真实取证结果中登记的 evidence_id")
        joined = "\n".join(json.dumps(entry["content"], ensure_ascii=False, default=str) for entry in found)
        numbers = re.findall(r"\d+(?:\.\d+)?%?", claim)
        missing_numbers = [number for number in numbers if number not in joined]
        if missing_numbers:
            issues.append(f"证据原文无法核对数值: {', '.join(missing_numbers)}")
        if quote and quote not in joined:
            issues.append("evidence_quote 不存在于登记证据原文")
        is_causal = any(word in claim.lower() for word in causal_words)
        conflict_ids = item.get("conflicts_with_evidence_ids", []) if isinstance(item, dict) else []
        has_declared_conflict = bool(conflict_ids)
        if is_causal:
            issues.append("因果结论只能作为推断；现有引用不能单独证明因果")
        if not found or not claim:
            level = "insufficient"
        elif has_declared_conflict:
            level = "conflicting"
        elif is_causal or missing_numbers or not quote:
            level = "partial"
        else:
            level = "direct"
        review.append({
            "claim_index": index,
            "claim": claim,
            "evidence_ids": evidence_ids,
            "conflicts_with_evidence_ids": conflict_ids,
            "support_level": level,
            "issues": issues,
            "next_action": "补充检索或降级为待验证推断" if level != "direct" else "可保留原文引用，并标明适用范围",
        })
    levels = {level: sum(item["support_level"] == level for item in review) for level in ("direct", "partial", "conflicting", "insufficient")}
    trace("claim_support_reviewed", claims=len(review), support_levels=levels)
    return json.dumps({"review": review}, ensure_ascii=False)
