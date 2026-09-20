"""Minimal diagnostic script to isolate the root cause of AgentRoute 120s read_timeout.

Tests A, B, and C with identical prompt, model, base_url, and employee inputs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Literal

from dotenv import load_dotenv
import httpx
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()

from backend.app.database import DEMO_EMPLOYEES
from backend.app.models import Employee
from backend.app.services.agent_router import (
    AgentRoute,
    AgentRouter,
    agent_route_json_schema,
)
from backend.app.services.llm_client import (
    AgentLLMClient,
    strict_json_schema,
    validate_strict_json_schema,
)


class SimplifiedRouteDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str
    mutation_requested: bool
    employees: list[str] = Field(default_factory=list)
    target_week: str | None = None
    operation: Literal["add", "set", "remove", "clear"] = "add"


def build_simplified_schema() -> dict[str, Any]:
    raw = SimplifiedRouteDTO.model_json_schema()
    schema = strict_json_schema(raw)
    validate_strict_json_schema(schema)
    return schema


def get_common_context() -> tuple[list[Employee], str, str, str, dict[str, Any]]:
    employees = [Employee(**item) for item in DEMO_EMPLOYEES]
    test_message = "把 E17 随便排到哪一天都行"
    system_prompt = (
        "Route a scheduling assistant message into the supplied JSON schema. "
        "For read-only ASK/EXPLAIN/ADVICE populate read_query with question_type and "
        "requested_facts. A question about removing an assignment is a read-only "
        "counterfactual, not replan or what_if. Only explicitly referenced suggestions "
        "may set reference; concrete schedule questions never inherit a suggestion. "
        "The backend supplies the workbench week when unspecified: do not ask which "
        "week merely because history mentions other weeks. Skill eligibility of assigned "
        "people and rule validation are coverage_analysis. Employee why/absence and "
        "employee removal questions are assignment_explanation. Counts are staffing_explanation; "
        "only inability to produce a schedule is feasibility_explanation. Explicit suggestion "
        "explanations use general_question with reference_mode suggestion. "
        "Separate analysis from mutation: advice about leave is read only unless the "
        "user explicitly asks to generate or replan. Never treat confirmation words as "
        "permission to confirm a schedule; confirmation remains a UI-only action. Use "
        "only supplied employee IDs. Resolve references such as 'second one' to a "
        "suggestion reference when supported by recent messages. Set operation to "
        "add, set, remove, or clear from the structured plan; preserve one change "
        "per employee/day and do not invent a cross-product. Populate operations with "
        "ordered per-employee add/set/remove/clear operations; a clear operation may "
        "have day null. Use null for unspecified nullable fields. For changes of type "
        "preference, assign, or unassign, shift must be specified. Treat only direct "
        "statements such as 'force generate' or 'I authorize this exception' as an "
        "override request. An override needs exact rule/day/shift scope: R08 also needs "
        "an employee, while R01-R04 need allowed_shortage. Do not infer an override "
        "from 'try', 'continue', or other ambiguous wording."
    )
    user_payload = {
        "message": test_message,
        "conversation_summary": None,
        "valid_employee_ids": [employee.id for employee in employees],
        "recent_messages": [],
    }
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    api_key = os.getenv("LLM_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", "gpt-5.6-sol").strip()
    return employees, base_url, api_key, model, {
        "system": system_prompt,
        "user": user_payload,
    }


def run_diagnostic_http_post(
    *,
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    read_timeout: float,
    stage: str,
    schema_bytes: int = 0,
) -> dict[str, Any]:
    body_str = json.dumps(payload, ensure_ascii=False)
    request_bytes = len(body_str.encode("utf-8"))
    message_count = len(payload.get("messages", []))
    model = payload.get("model", "")

    print(
        f"\n[{stage}] STARTING: model={model} request_bytes={request_bytes} "
        f"schema_bytes={schema_bytes} message_count={message_count} timeout={read_timeout}s"
    )

    timeout = httpx.Timeout(connect=10.0, read=read_timeout, write=30.0, pool=10.0)
    client = httpx.Client(timeout=timeout)

    started = time.perf_counter()
    connected = False
    provider_status = None
    provider_message = None
    error_type = None
    raw_response_text = None
    success = False

    try:
        response = client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            content=body_str.encode("utf-8"),
        )
        connected = True
        provider_status = response.status_code
        raw_response_text = response.text
        latency_ms = round((time.perf_counter() - started) * 1000)

        if 200 <= response.status_code < 300:
            success = True
            error_type = "none"
        else:
            error_type = f"http_{response.status_code}"
            try:
                err_data = response.json()
                if isinstance(err_data, dict):
                    err_obj = err_data.get("error")
                    provider_message = (
                        err_obj.get("message")
                        if isinstance(err_obj, dict)
                        else err_data.get("message")
                    )
            except Exception:
                provider_message = raw_response_text[:300]
    except httpx.ConnectTimeout as exc:
        latency_ms = round((time.perf_counter() - started) * 1000)
        error_type = "connect_timeout"
        provider_message = f"TCP/TLS connection timed out after {latency_ms / 1000:.2f}s"
    except httpx.ReadTimeout as exc:
        connected = True  # Connection succeeded, request body sent, waited for response
        latency_ms = round((time.perf_counter() - started) * 1000)
        error_type = "read_timeout"
        provider_message = f"Read timeout: connection established and request sent, but no response bytes received after {latency_ms / 1000:.2f}s"
    except httpx.WriteTimeout as exc:
        connected = True
        latency_ms = round((time.perf_counter() - started) * 1000)
        error_type = "write_timeout"
        provider_message = f"Write timeout after {latency_ms / 1000:.2f}s"
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000)
        error_type = type(exc).__name__
        provider_message = str(exc)[:300]
    finally:
        client.close()

    result = {
        "stage": stage,
        "model": model,
        "request_bytes": request_bytes,
        "schema_bytes": schema_bytes,
        "message_count": message_count,
        "latency_ms": latency_ms,
        "provider_status": provider_status,
        "connected": connected,
        "error_type": error_type,
        "provider_message": provider_message,
        "success": success,
        "raw_response_text": raw_response_text,
    }

    print(
        f"[{stage}] FINISHED in {latency_ms / 1000:.2f}s: success={success} "
        f"status={provider_status} error_type={error_type} connected={connected}"
    )
    if provider_message:
        print(f"[{stage}] Provider Message: {provider_message}")
    return result


def test_a(read_timeout: float = 125.0) -> dict[str, Any]:
    """A. 当前真实 AgentRoute (strict=True, agent_route_json_schema)"""
    employees, base_url, api_key, model, ctx = get_common_context()
    schema = agent_route_json_schema()
    schema_bytes = len(json.dumps(schema).encode("utf-8"))

    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": ctx["system"]},
            {
                "role": "user",
                "content": json.dumps(ctx["user"], ensure_ascii=False, default=str),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "agent_route",
                "strict": True,
                "schema": schema,
            },
        },
    }

    res = run_diagnostic_http_post(
        base_url=base_url,
        api_key=api_key,
        payload=payload,
        read_timeout=read_timeout,
        stage="Test A (Real AgentRoute Strict)",
        schema_bytes=schema_bytes,
    )

    if res["success"]:
        try:
            parsed = json.loads(
                json.loads(res["raw_response_text"])["choices"][0]["message"]["content"]
            )
            route = AgentRoute.model_validate(parsed)
            res["validated_intent"] = route.intent
            res["validated_mutation"] = route.mutation_requested
            res["validated_employees"] = route.employees
            print(f"[Test A] Validated route: intent={route.intent}, mutation={route.mutation_requested}, employees={route.employees}")
        except Exception as exc:
            res["validation_error"] = str(exc)
            print(f"[Test A] Validation error: {exc}")

    return res


def test_b(read_timeout: float = 60.0) -> dict[str, Any]:
    """B. 同样 prompt，普通 JSON (no response_format=json_schema)"""
    employees, base_url, api_key, model, ctx = get_common_context()

    system_content = (
        ctx["system"]
        + "\n\nIMPORTANT: You must reply with ONLY a single valid JSON object, without any Markdown formatting or code fences. "
        "The JSON object must contain at least: intent, mutation_requested, employees, target_week, operation. "
        'For example: {"intent": "replan", "mutation_requested": true, "employees": ["E17"], "target_week": null, "operation": "add"}'
    )

    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system_content},
            {
                "role": "user",
                "content": json.dumps(ctx["user"], ensure_ascii=False, default=str),
            },
        ],
    }

    res = run_diagnostic_http_post(
        base_url=base_url,
        api_key=api_key,
        payload=payload,
        read_timeout=read_timeout,
        stage="Test B (Plain JSON prompt)",
        schema_bytes=0,
    )

    if res["success"]:
        try:
            content_str = json.loads(res["raw_response_text"])["choices"][0]["message"]["content"].strip()
            # remove code fences if any
            if content_str.startswith("```"):
                lines = content_str.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content_str = "\n".join(lines).strip()
            parsed = json.loads(content_str)
            res["raw_output_json"] = parsed
            validated = SimplifiedRouteDTO.model_validate(parsed)
            res["validated_dto"] = validated.model_dump()
            print(f"[Test B] Parsed JSON output successfully: {validated.model_dump()}")
        except Exception as exc:
            res["validation_error"] = str(exc)
            print(f"[Test B] Validation/Parse error: {exc}")

    return res


def test_c(read_timeout: float = 60.0) -> dict[str, Any]:
    """C. 简化版 strict schema (response_format=json_schema, strict=True)"""
    employees, base_url, api_key, model, ctx = get_common_context()
    simplified_schema = build_simplified_schema()
    schema_bytes = len(json.dumps(simplified_schema).encode("utf-8"))

    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": ctx["system"]},
            {
                "role": "user",
                "content": json.dumps(ctx["user"], ensure_ascii=False, default=str),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "agent_route_simplified",
                "strict": True,
                "schema": simplified_schema,
            },
        },
    }

    res = run_diagnostic_http_post(
        base_url=base_url,
        api_key=api_key,
        payload=payload,
        read_timeout=read_timeout,
        stage="Test C (Simplified Strict Schema)",
        schema_bytes=schema_bytes,
    )

    if res["success"]:
        try:
            parsed = json.loads(
                json.loads(res["raw_response_text"])["choices"][0]["message"]["content"]
            )
            validated = SimplifiedRouteDTO.model_validate(parsed)
            res["validated_dto"] = validated.model_dump()
            print(f"[Test C] Parsed Simplified strict output successfully: {validated.model_dump()}")
        except Exception as exc:
            res["validation_error"] = str(exc)
            print(f"[Test C] Validation/Parse error: {exc}")

    return res


def main():
    parser = argparse.ArgumentParser(description="AgentRoute A/B/C Diagnostic Tool")
    parser.add_argument(
        "--test",
        choices=["all", "A", "B", "C"],
        default="all",
        help="Which test to run (A, B, C, or all)",
    )
    parser.add_argument(
        "--timeout-a",
        type=float,
        default=125.0,
        help="Timeout in seconds for Test A (default 125s)",
    )
    parser.add_argument(
        "--timeout-bc",
        type=float,
        default=60.0,
        help="Timeout in seconds for Tests B & C (default 60s)",
    )
    args = parser.parse_args()

    results = {}

    if args.test in ("A", "all"):
        results["A"] = test_a(read_timeout=args.timeout_a)

    if args.test in ("B", "all"):
        results["B"] = test_b(read_timeout=args.timeout_bc)

    if args.test in ("C", "all"):
        results["C"] = test_c(read_timeout=args.timeout_bc)

    print("\n" + "=" * 60)
    print("DIAGNOSTIC SUMMARY TABLE")
    print("=" * 60)
    for test_key, res in results.items():
        print(f"Test {test_key}:")
        print(f"  Stage:           {res['stage']}")
        print(f"  Success:         {res['success']}")
        print(f"  Latency:         {res['latency_ms']} ms ({res['latency_ms']/1000:.2f}s)")
        print(f"  HTTP Status:     {res['provider_status']}")
        print(f"  Error Type:      {res['error_type']}")
        print(f"  Connected:       {res['connected']}")
        print(f"  Request Bytes:   {res['request_bytes']}")
        print(f"  Schema Bytes:    {res['schema_bytes']}")
        if res.get("provider_message"):
            print(f"  Provider Message:{res['provider_message']}")
        if res.get("validated_dto"):
            print(f"  Validated Output:{res['validated_dto']}")
        elif res.get("validated_intent"):
            print(f"  Validated Intent:{res['validated_intent']}")
        print("-" * 60)


if __name__ == "__main__":
    main()
