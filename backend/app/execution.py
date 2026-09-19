"""Public execution facts, never model reasoning or provider payloads.

ContextVar isolates concurrent synchronous turns, including their nested tools.
Budgets are cooperative: check before work/commits and cap blocking operations;
never interrupt a database transaction or kill a solver thread.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from .config import positive_seconds

logger = logging.getLogger("optishift.execution")

LABELS = {
    "product_lookup": "查询产品知识",
    "response_compose": "组织回复",
    "turn_started": "已收到请求",
    "agent_route": "理解排班请求",
    "agent_route_lite": "Agent Router",
    "agent_mutation": "解析排班变更",
    "agent_force": "解析例外授权",
    "router_fallback": "使用备用 JSON 解析",
    "resolve_context": "定位目标周和排班上下文",
    "load_schedule": "读取当前排班",
    "load_employees": "读取员工信息",
    "solver": "计算排班方案",
    "validator": "校验排班规则",
    "save_draft": "保存排班草稿",
    "explanation": "生成排班说明",
    "response_compose": "生成回复",
    "read_analysis": "分析人数和排班事实",
    "counterfactual": "只读验证移除和替代方案",
    "intent_parse": "解析排班调整",
    "tool": "执行排班操作",
    "turn_completed": "排班处理完成",
    "turn_failed": "排班处理失败",
}


class ExecutionEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    operation_id: str
    turn_id: str
    client_message_id: str
    stage: str
    status: Literal["started", "completed", "failed"]
    label: str
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    duration_ms: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ExecutionTimeout(RuntimeError):
    error_type = "agent_turn_timeout"

    def __init__(self, stage: str, latency_ms: int):
        self.stage = stage
        self.latency_ms = latency_ms
        super().__init__("本轮处理超过执行预算，请查看已保存结果后重试。")


current_execution: ContextVar[ExecutionTrace | None] = ContextVar("execution", default=None)


class ExecutionTrace:
    def __init__(self, conversation_id: str, client_message_id: str, sink=None):
        self.conversation_id = conversation_id
        self.client_message_id = client_message_id
        self.turn_id = f"{conversation_id}:{client_message_id}"
        self.sink = sink
        self.started = time.monotonic()
        self.budget = positive_seconds("AGENT_TURN_TIMEOUT_SECONDS", 300)
        self.events: list[dict[str, Any]] = []
        self.terminal_event: dict[str, Any] | None = None
        self.owner: tuple[dict, str] | None = None

    def remaining(self, stage: str) -> float:
        remaining = self.budget - (time.monotonic() - self.started)
        if remaining <= 0:
            raise ExecutionTimeout(stage, round((time.monotonic() - self.started) * 1000))
        return remaining

    def publish(self, event: dict) -> None:
        logger.info(
            "execution_event %s",
            {
                "conversation_id": self.conversation_id,
                **{
                    key: event[key]
                    for key in ("client_message_id", "turn_id", "stage", "status", "duration_ms")
                },
            },
        )
        if self.sink:
            try:
                self.sink(event)
            except Exception:
                # A disconnected observer must never fail or repeat a mutation.
                logger.warning("execution_sink_unavailable")

    def emit(
        self, stage, status, operation_id=None, duration_ms=None, details=None, *, publish=True
    ):
        # Only typed business facts cross this boundary. No arbitrary tool/LLM text.
        safe = {}
        for key, value in (details or {}).items():
            if key in {"intent", "target_week", "error_type", "solver_status"}:
                if isinstance(value, str) and len(value) <= 64:
                    safe[key] = value
            elif key in {"provider_status", "latency_ms"} and isinstance(value, int):
                safe[key] = value
            elif key == "employees" and isinstance(value, list):
                safe[key] = [
                    v for v in value if isinstance(v, str) and v.isalnum() and len(v) <= 16
                ]
            elif key == "changes" and isinstance(value, list):
                safe[key] = [
                    {k: v for k, v in item.items() if k in {"employee_id", "day", "type"}}
                    for item in value
                    if isinstance(item, dict)
                    and item.get("day") in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
                    and item.get("type")
                    in {"leave", "unavailable", "available", "preference", "assign", "unassign"}
                    and str(item.get("employee_id", "")).isalnum()
                    and len(str(item.get("employee_id", ""))) <= 16
                ]
        event = ExecutionEvent(
            operation_id=operation_id or uuid4().hex,
            turn_id=self.turn_id,
            client_message_id=self.client_message_id,
            stage=stage,
            status=status,
            label=LABELS.get(stage, "执行排班操作"),
            duration_ms=duration_ms,
            details=safe,
        ).model_dump(mode="json")
        self.events.append(event)
        if publish:
            self.publish(event)
        return event

    def finish(self, failed=False):
        # A transaction can fail after staging its completion event. Only publish
        # success once the caller has returned from that transaction.
        if failed and self.terminal_event and self.terminal_event["status"] != "failed":
            self.events.remove(self.terminal_event)
            self.terminal_event = None
        if self.terminal_event is None:
            self.terminal_event = self.emit(
                "turn_failed" if failed else "turn_completed",
                "failed" if failed else "completed",
                duration_ms=round((time.monotonic() - self.started) * 1000),
                publish=False,
            )
        return self.events


@contextmanager
def execution_stage(stage: str):
    trace = current_execution.get()
    if trace is None:
        yield {}
        return
    started = time.monotonic()
    event = trace.emit(stage, "started")
    details: dict[str, Any] = {}
    try:
        trace.remaining(stage)
        yield details
    except Exception as exc:
        trace.emit(
            stage,
            "failed",
            event["operation_id"],
            round((time.monotonic() - started) * 1000),
            {
                "error_type": getattr(exc, "error_type", "operation_failed"),
                "latency_ms": getattr(exc, "latency_ms", None),
                "provider_status": getattr(exc, "provider_status", None),
            },
        )
        raise
    else:
        trace.emit(
            stage,
            "failed" if details.get("error_type") else "completed",
            event["operation_id"],
            round((time.monotonic() - started) * 1000),
            details,
        )


def traced(stage: str):
    def decorate(function: Callable):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with execution_stage(stage) as details:
                result = function(*args, **kwargs)
                if stage == "agent_route":
                    details.update(
                        intent=result.intent.value,
                        employees=result.employees,
                        changes=[c.model_dump(mode="json") for c in result.changes],
                    )
                    if result.target_week:
                        details["target_week"] = result.target_week.isoformat()
                elif stage == "resolve_context":
                    details["target_week"] = result.week_start.isoformat()
                elif stage == "solver":
                    details["solver_status"] = result.status.value
                    if result.status.value == "unknown":
                        details["error_type"] = "solver_timeout"
                return result

        return wrapped

    return decorate
