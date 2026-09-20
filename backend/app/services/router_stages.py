"""Bounded, side-effect-free provider parsing shared by the router stages."""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import Future, TimeoutError
from contextvars import copy_context
from dataclasses import dataclass, field
from threading import BoundedSemaphore, Thread
from typing import Any

from pydantic import BaseModel, ValidationError

from ..config import positive_seconds
from ..execution import current_execution, execution_stage
from .llm_client import (
    AgentLLMClient,
    AIUnavailableError,
    is_schema_unsupported,
    strict_json_schema,
)

logger = logging.getLogger("optishift.router")
# Timed-out workers can finish only an HTTP request / parse, never business work.
# Bound their count even if a transport ignores its own timeout.
_provider_slots = BoundedSemaphore(8)


def schema_bytes(schema: dict) -> int:
    return len(json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


@dataclass
class RouterRun:
    started: float = field(default_factory=time.monotonic)
    budget: float = field(
        default_factory=lambda: min(60, positive_seconds("LLM_ROUTER_BUDGET_SECONDS", 60))
    )
    fallback_used: bool = False
    stages: list[dict[str, Any]] = field(default_factory=list)
    results: dict[str, dict] = field(default_factory=dict)
    error_type: str | None = None
    completed_ms: int | None = None

    def remaining(self) -> float:
        remaining = self.budget - (time.monotonic() - self.started)
        trace = current_execution.get()
        if trace:
            remaining = min(remaining, trace.remaining("agent_route"))
        # Do not start another provider request with only a clock tick left.
        if remaining <= 0.01:
            raise AIUnavailableError(
                "Agent Router 已超过总时间预算。",
                error_type="router_budget_exceeded",
                stage="agent_route",
            )
        return remaining

    @property
    def latency_ms(self) -> int:
        return (
            self.completed_ms
            if self.completed_ms is not None
            else round((time.monotonic() - self.started) * 1000)
        )


def compatible_failure(exc: AIUnavailableError) -> bool:
    return is_schema_unsupported(exc)


def parse_stage(
    llm: AgentLLMClient,
    run: RouterRun,
    model: type[BaseModel],
    *,
    name: str,
    system: str,
    user: dict,
) -> BaseModel:
    schema = strict_json_schema(model.model_json_schema())
    for fallback in (False, True):
        semantic = name != "agent_route_lite"
        stage_limit = (
            positive_seconds("LLM_SEMANTIC_BUDGET_SECONDS", 20)
            if semantic
            else positive_seconds("LLM_ROUTER_TIMEOUT_SECONDS", 25)
        )
        limit = min(30, stage_limit, run.remaining())
        if fallback:
            limit = min(limit, positive_seconds("LLM_SCHEMA_RETRY_BUDGET_SECONDS", 10))
        record = {
            "stage": name,
            "parser_name": name,
            "model": llm.model,
            "schema_name": name,
            "schema_bytes": schema_bytes(schema),
            "message_count": 2,
            "request_bytes": None,
            "fallback_used": fallback,
            "error_type": None,
            "attempt": 2 if fallback else 1,
            "budget_seconds": limit,
            "retry_reason": "schema_unsupported" if fallback else None,
        }
        started = time.monotonic()
        future: Future = Future()
        if not _provider_slots.acquire(blocking=False):
            raise AIUnavailableError(
                "Agent Router 正忙，请稍后重试。", error_type="router_busy", stage=name
            )

        # Capture each attempt's values: an expired worker must never see the
        # next attempt's Future, timeout or response-format flag.
        def invoke(attempt=fallback, timeout=limit, result=future):
            try:
                options = {"strict_output": False} if attempt else {}
                payload = llm.complete_json(
                    system=system,
                    user=user,
                    schema_name=name,
                    schema=schema,
                    stage=name,
                    read_timeout_seconds=timeout,
                    **options,
                )
                metrics = getattr(llm, "last_request_metrics", {})
                parsed = model.model_validate(payload)
                result.set_result((parsed, metrics))
            except BaseException as exc:
                exc.router_request_metrics = getattr(llm, "last_request_metrics", {})
                result.set_exception(exc)
            finally:
                _provider_slots.release()

        context = copy_context()
        Thread(target=context.run, args=(invoke,), daemon=True, name="router-provider").start()
        try:
            with execution_stage("router_fallback" if fallback else name):
                try:
                    parsed, metrics = future.result(timeout=limit)
                except TimeoutError as exc:
                    raise AIUnavailableError(
                        "Agent Router 等待响应超时。", error_type="read_timeout", stage=name
                    ) from exc
                except ValidationError as exc:
                    record.update(getattr(exc, "router_request_metrics", {}))
                    raise AIUnavailableError(
                        "Agent Router 返回格式无效。",
                        error_type="structured_output_error",
                        stage=name,
                    ) from exc
                run.remaining()
                record.update(metrics)
                run.results[name] = parsed.model_dump(mode="json")
                return parsed
        except AIUnavailableError as exc:
            record.update(getattr(exc, "router_request_metrics", {}))
            record["error_type"] = exc.error_type
            if fallback or run.fallback_used or not compatible_failure(exc):
                run.error_type = exc.error_type
                raise
            run.remaining()
            run.fallback_used = True
            record["retry_reason"] = "schema_unsupported"
        finally:
            record["latency_ms"] = record["parser_latency_ms"] = round(
                (time.monotonic() - started) * 1000
            )
            run.stages.append(record)
            # Metadata only. Raw DTOs are available to explicit evals, not logs.
            logger.info("router_stage %s", record)
    raise AssertionError("unreachable")
