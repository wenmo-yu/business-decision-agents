"""请求级上下文预算、可追溯工具产物与轨迹记录。

这里刻意不把完整网页、SSE 事件或文档分块塞回主 Agent 的消息历史：原始产物
保存在当前会话目录，模型只得到有上限的结构化摘要。预算是程序级约束，而不是
依赖提示词的约定。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class BudgetExceeded(RuntimeError):
    """工具调用将超出本轮资源预算。"""


@dataclass
class RunState:
    session_dir: Path
    max_expert_calls: int
    max_context_tokens: int
    deadline: float
    expert_calls: int = 0
    context_tokens: int = 0
    sequence: int = 0
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)


_run_ctx: ContextVar[RunState | None] = ContextVar("context_engineering_run", default=None)


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def start_run(session_dir: str) -> Token[RunState | None]:
    """启动一次受预算约束的 Agent 运行。"""
    timeout_seconds = _int_env("AGENT_MAX_WALL_TIME_SECONDS", 180)
    state = RunState(
        session_dir=Path(session_dir),
        max_expert_calls=_int_env("AGENT_MAX_EXPERT_CALLS", 8),
        max_context_tokens=_int_env("AGENT_MAX_CONTEXT_TOKENS", 12_000),
        deadline=time.monotonic() + timeout_seconds,
    )
    state.session_dir.joinpath("artifacts").mkdir(parents=True, exist_ok=True)
    token = _run_ctx.set(state)
    trace("run_started", limits=budget_snapshot())
    return token


def end_run(token: Token[RunState | None]) -> dict[str, Any]:
    state = _run_ctx.get()
    summary = budget_snapshot()
    if state:
        trace("run_finished", budget=summary)
    _run_ctx.reset(token)
    return summary


def current_state() -> RunState | None:
    return _run_ctx.get()


def budget_snapshot() -> dict[str, Any]:
    state = current_state()
    if not state:
        return {"enabled": False}
    return {
        "enabled": True,
        "expert_calls": state.expert_calls,
        "max_expert_calls": state.max_expert_calls,
        "context_tokens": state.context_tokens,
        "max_context_tokens": state.max_context_tokens,
        "remaining_seconds": max(0, round(state.deadline - time.monotonic(), 2)),
    }


def trace(event: str, **data: Any) -> None:
    """追加 JSONL 轨迹；写入失败不能影响业务链路。"""
    state = current_state()
    if not state:
        return
    state.sequence += 1
    record = {"sequence": state.sequence, "event": event, "at": time.time(), **data}
    try:
        with state.session_dir.joinpath("trace.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def reserve_expert_call(expert: str, input_context: str = "") -> None:
    """在联网/问数/RAG 真正开始前强制检查调用数、时限与上下文预算。"""
    state = current_state()
    if not state:
        return
    if time.monotonic() > state.deadline:
        trace("budget_rejected", expert=expert, reason="wall_time_exceeded")
        raise BudgetExceeded("本轮专家调用已超过时间预算。")
    if state.expert_calls >= state.max_expert_calls:
        trace("budget_rejected", expert=expert, reason="expert_call_limit")
        raise BudgetExceeded("本轮专家调用已达到最大次数。")
    estimate = estimate_tokens(input_context)
    if state.context_tokens + estimate > state.max_context_tokens:
        trace("budget_rejected", expert=expert, reason="context_token_limit")
        raise BudgetExceeded("本轮上下文预算不足，已拒绝继续扩展检索。")
    state.expert_calls += 1
    state.context_tokens += estimate
    trace("expert_started", expert=expert, input_tokens=estimate, budget=budget_snapshot())


def estimate_tokens(value: Any) -> int:
    """稳定、无模型依赖的保守估算；仅用于预算，不将其伪装成供应商精确计费。"""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    # 中文常接近每字一个 token，英文约四字符一个 token，取较保守的较大值。
    return max(1, max(len(text) // 4, sum(1 for char in text if "\u4e00" <= char <= "\u9fff")))


def compact_for_agent(value: Any, max_chars: int = 6_000) -> tuple[Any, bool]:
    """把工具回传压缩到固定上下文上限，完整原始值仍保存在 artifact。"""
    rendered = json.dumps(value, ensure_ascii=False, default=str)
    if len(rendered) <= max_chars:
        return value, False
    # 保留有效 JSON，避免字符串硬截断产生不可解析 payload。
    if isinstance(value, dict):
        compact = {key: value[key] for key in list(value)[:12]}
        compact["_context_truncated"] = True
        compact["_raw_artifact_available"] = True
        return compact, True
    return {"preview": rendered[:max_chars], "_context_truncated": True, "_raw_artifact_available": True}, True


def record_evidence(source_type: str, content: Any, metadata: dict[str, Any] | None = None) -> str:
    """注册证据并保存不可变原始快照，返回可被结论引用的 evidence_id。"""
    state = current_state()
    normalized = {"source_type": source_type, "content": content, "metadata": metadata or {}}
    digest = hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]
    evidence_id = f"ev_{digest}"
    if state:
        state.evidence[evidence_id] = normalized
        try:
            state.session_dir.joinpath("artifacts", f"{evidence_id}.json").write_text(
                json.dumps(normalized, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
        except OSError:
            pass
        trace("evidence_registered", evidence_id=evidence_id, source_type=source_type)
    return evidence_id


def get_evidence(evidence_id: str) -> dict[str, Any] | None:
    state = current_state()
    if not state:
        return None
    return state.evidence.get(evidence_id)


def record_expert_result(expert: str, result: Any, source_type: str) -> tuple[str, Any, bool]:
    evidence_id = record_evidence(source_type, result, {"expert": expert})
    state = current_state()
    # 为后续专家和最终报告预留至少一部分预算；工具输出绝不能无上限地挤占上下文。
    max_chars = 6_000
    if state:
        max_chars = max(200, min(max_chars, (state.max_context_tokens - state.context_tokens) * 3))
    compact, truncated = compact_for_agent(result, max_chars=max_chars)
    if state:
        tokens = estimate_tokens(compact)
        if state.context_tokens + tokens > state.max_context_tokens:
            compact = {"evidence_id": evidence_id, "_context_truncated": True, "_raw_artifact_available": True}
            tokens = estimate_tokens(compact)
            truncated = True
        state.context_tokens += tokens
        trace("expert_finished", expert=expert, evidence_id=evidence_id, output_tokens=tokens, truncated=truncated, budget=budget_snapshot())
    return evidence_id, compact, truncated
