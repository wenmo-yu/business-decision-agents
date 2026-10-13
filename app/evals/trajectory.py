"""可复现的轨迹评测：不依赖模型判分，验证协作、预算与证据契约。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_trace(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate_trajectory(trace_events: list[dict[str, Any]], expectation: dict[str, Any]) -> dict[str, Any]:
    called = {event.get("expert") for event in trace_events if event.get("event") == "expert_started"}
    required = set(expectation.get("required_experts", []))
    rejected = [event for event in trace_events if event.get("event") == "budget_rejected"]
    registered = [event for event in trace_events if event.get("event") == "evidence_registered"]
    claim_reviews = [event for event in trace_events if event.get("event") == "claim_support_reviewed"]
    support_levels = {"direct": 0, "partial": 0, "conflicting": 0, "insufficient": 0}
    for event in claim_reviews:
        for level, count in event.get("support_levels", {}).items():
            if level in support_levels:
                support_levels[level] += count
    missing = sorted(required - called)
    min_claim_reviews = int(expectation.get("min_claim_reviews", 0))
    passed = not missing and len(claim_reviews) >= min_claim_reviews and (expectation.get("allow_budget_rejection", False) or not rejected)
    return {
        "passed": passed,
        "required_experts": sorted(required),
        "called_experts": sorted(item for item in called if item),
        "missing_experts": missing,
        "budget_rejections": len(rejected),
        "evidence_count": len(registered),
        "claim_reviews": len(claim_reviews),
        "support_levels": support_levels,
    }
