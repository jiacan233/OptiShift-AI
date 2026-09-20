from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from copy import deepcopy
from threading import BoundedSemaphore, Lock, Thread, local
from typing import Any, NoReturn
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from jsonschema import Draft202012Validator

from ..config import positive_seconds
from ..execution import ExecutionTimeout, current_execution

logger = logging.getLogger("optishift.llm")
_transport_slots = BoundedSemaphore(16)


def provider_stage_budget(stage: str | None) -> float | None:
    """Independent wall-clock budgets; callers may impose a smaller remaining budget."""
    if stage in {"response_compose", "explanation"}:
        return min(15, positive_seconds("LLM_RESPONSE_BUDGET_SECONDS", 8))
    if stage in {"intent_parse", "agent_semantic", "semantic_parse"}:
        return min(30, positive_seconds("LLM_SEMANTIC_BUDGET_SECONDS", 20))
    return None


def is_schema_unsupported(error: AIUnavailableError) -> bool:
    """Only an explicit feature rejection permits the non-strict compatibility path.

    Invalid schemas and malformed model output are not evidence that the Provider
    lacks structured output. Transport errors never warrant another long request.
    """
    if error.error_type not in {"invalid_request", "provider_not_implemented"}:
        return False
    message = error.provider_message or ""
    feature = r"(?:json[_ ]?schema|response[_ ]?format|structured[ _-]?outputs?|strict)"
    unsupported = (
        r"(?:not\s+support(?:ed)?|unsupported|not\s+available|not\s+implemented|"
        r"does\s+not\s+support|unknown\s+(?:parameter|field))"
    )
    return bool(re.search(feature, message, re.I) and re.search(unsupported, message, re.I))


def _redact_message(value: str | None, limit: int, secrets: tuple[str, ...] = ()) -> str | None:
    if not value:
        return None
    safe = value
    if re.search(
        r"(?i)(<think|<reasoning|system[_ ]?prompt|reasoning_content|hidden_reasoning)", safe
    ):
        return "[REDACTED_PROVIDER_CONTENT]"
    for secret in secrets:
        if secret:
            safe = safe.replace(secret, "[REDACTED]")
    # Remove entire URLs: credentials can occur in userinfo, paths, queries or fragments.
    safe = re.sub(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s<>\"']+", "[REDACTED_URL]", safe)
    safe = re.sub(r"(?i)\bBearer\s+[^\s,;\"']+", "Bearer [REDACTED]", safe)
    # Handle plain header syntax, JSON-quoted values and query-string fragments.
    safe = re.sub(
        r"(?i)(\b(?:authorization|api[_ -]?key|access[_-]?token|refresh[_-]?token|"
        r"token|secret|password|credential|signature|sig)[\"']?\s*[:=]\s*)"
        r"(?:\"[^\"]*\"|'[^']*'|[^\r\n,;&}]+)",
        r"\1[REDACTED]",
        safe,
    )
    safe = re.sub(r"\bsk-[A-Za-z0-9._-]{6,}\b", "[REDACTED_API_KEY]", safe)
    return re.sub(r"\s+", " ", safe).strip()[:limit] or None


class AIUnavailableError(RuntimeError):
    """Raised when a configured LLM cannot produce a trustworthy response."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str = "provider_error",
        provider_status: int | None = None,
        provider_message: str | None = None,
        latency_ms: int | None = None,
        stage: str | None = None,
    ) -> None:
        self.safe_message = message
        self.error_type = error_type
        self.provider_status = provider_status
        self.provider_message = _redact_message(
            provider_message, 300, (os.getenv("LLM_API_KEY", "").strip(),)
        )
        self.latency_ms = latency_ms
        self.stage = stage
        super().__init__(message)

    @property
    def public_details(self) -> dict[str, str | int | None]:
        return {
            "error_type": self.error_type,
            "provider_status": self.provider_status,
            "provider_message": self.provider_message,
            "latency_ms": self.latency_ms,
            "stage": self.stage,
        }


def validate_strict_json_schema(schema: dict[str, Any]) -> None:
    """Validate the subset required by strict JSON Schema providers.

    Strict structured output providers require every property of every object
    to appear in ``required``.  Validate recursively so a future nested field
    cannot silently make requests invalid at runtime.
    """

    if not isinstance(schema, dict):
        raise ValueError("strict JSON schema must be an object")
    if schema.get("type") == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            raise ValueError("strict object schema must define properties and required")
        if schema.get("additionalProperties") is not False:
            raise ValueError("strict object schema must forbid additional properties")
        if any(not isinstance(name, str) for name in required):
            raise ValueError("strict object required must contain property names")
        property_names = set(properties)
        required_names = set(required)
        if property_names != required_names or len(required) != len(required_names):
            missing = sorted(property_names - required_names)
            unknown = sorted(required_names - property_names)
            raise ValueError(
                f"strict object schema required mismatch missing={missing} unknown={unknown}"
            )
        for property_schema in properties.values():
            validate_strict_json_schema(property_schema)
    elif schema.get("type") == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            validate_strict_json_schema(items)
    for keyword in ("anyOf", "oneOf", "allOf", "prefixItems"):
        for variant in schema.get(keyword, []):
            validate_strict_json_schema(variant)
    for definition in schema.get("$defs", {}).values():
        validate_strict_json_schema(definition)


def strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a Pydantic schema strict without changing field types or nullability."""
    result = deepcopy(schema)
    definitions = result.pop("$defs", {})

    def resolve_refs(node: Any) -> Any:
        if isinstance(node, dict):
            reference = node.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/$defs/"):
                definition = definitions.get(reference.removeprefix("#/$defs/"))
                if isinstance(definition, dict):
                    return resolve_refs(deepcopy(definition))
            return {key: resolve_refs(value) for key, value in node.items() if key != "$ref"}
        if isinstance(node, list):
            return [resolve_refs(item) for item in node]
        return node

    result = resolve_refs(result)

    def convert(node: dict[str, Any]) -> None:
        node.pop("default", None)
        if node.get("type") == "object":
            node["additionalProperties"] = False
            node["required"] = list(node.get("properties", {}))
        for keyword in ("properties", "$defs"):
            for child in node.get(keyword, {}).values():
                convert(child)
        if isinstance(node.get("items"), dict):
            convert(node["items"])
        for keyword in ("anyOf", "oneOf", "allOf", "prefixItems"):
            for child in node.get(keyword, []):
                convert(child)

    convert(result)
    validate_strict_json_schema(result)
    return result


class AgentLLMClient:
    """Small OpenAI-compatible client shared by routing and response composition."""

    _STATUS_ERRORS = {
        400: (
            "invalid_request",
            "AI Provider 拒绝了当前请求，请检查模型名称或请求参数。",
        ),
        401: (
            "authentication_error",
            "API Key 无效或未通过 AI Provider 认证。",
        ),
        403: (
            "permission_error",
            "当前 API Key 没有调用该模型或接口的权限。",
        ),
        404: (
            "model_or_endpoint_not_found",
            "AI 模型或 Provider 接口不存在，请检查 LLM_MODEL 和 LLM_BASE_URL。",
        ),
        429: (
            "rate_limit_or_quota",
            "AI Provider 当前触发限流或额度不足。",
        ),
        500: (
            "provider_internal_error",
            "AI Provider 服务内部错误。",
        ),
        501: (
            "provider_not_implemented",
            "AI Provider 当前不支持该请求或接口。",
        ),
        502: (
            "provider_gateway_error",
            "AI Provider 上游网关调用失败。",
        ),
        503: (
            "provider_service_unavailable",
            "AI Provider 服务暂时不可用。",
        ),
        504: (
            "provider_gateway_timeout",
            "AI Provider 上游网关请求超时。",
        ),
    }

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client
        self._owns_client = client is None
        self._client_lock = Lock()
        self._local = local()
        self.enabled = os.getenv("LLM_ENABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        self.api_key = os.getenv("LLM_API_KEY", "").strip()
        self.model = os.getenv("LLM_MODEL", "gpt-4.1-mini").strip()
        self.base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.timeout = httpx.Timeout(
            connect=positive_seconds("LLM_CONNECT_TIMEOUT_SECONDS", 8),
            read=positive_seconds("LLM_READ_TIMEOUT_SECONDS", 120),
            write=positive_seconds("LLM_WRITE_TIMEOUT_SECONDS", 50),
            pool=positive_seconds("LLM_POOL_TIMEOUT_SECONDS", 8),
        )

    @property
    def _last_latency_ms(self) -> int:
        return getattr(self._local, "latency_ms", 0)

    @_last_latency_ms.setter
    def _last_latency_ms(self, value: int) -> None:
        self._local.latency_ms = value

    @property
    def last_request_metrics(self) -> dict[str, Any]:
        return getattr(self._local, "request_metrics", {})

    @property
    def client(self) -> httpx.Client:
        with self._client_lock:
            if self._client is None:
                self._client = httpx.Client(
                    timeout=self.timeout,
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                )
            return self._client

    def close(self) -> None:
        with self._client_lock:
            if self._client is not None and self._owns_client:
                self._client.close()
                self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def _redact_and_truncate(self, value: str | None, limit: int) -> str | None:
        return _redact_message(value, limit, (self.api_key,))

    def _safe_base_url(self) -> str:
        try:
            parsed = urlsplit(self.base_url)
            hostname = parsed.hostname or ""
            if ":" in hostname and not hostname.startswith("["):
                hostname = f"[{hostname}]"
            netloc = hostname
            if parsed.port is not None:
                netloc = f"{netloc}:{parsed.port}"
            safe_url = netloc
        except ValueError:
            safe_url = "invalid-provider-url"
        return self._redact_and_truncate(safe_url, 300) or "<empty>"

    def _provider_error_message(self, response: httpx.Response) -> str | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None
        error = payload.get("error")
        message = error.get("message") if isinstance(error, dict) else payload.get("message")
        if not isinstance(message, str):
            return None
        return self._redact_and_truncate(message, 300)

    @classmethod
    def _classify_provider_error(
        cls,
        provider_status: int,
        provider_message: str | None,
    ) -> tuple[str, str]:
        normalized = (provider_message or "").casefold()
        if "all available accounts exhausted" in normalized:
            return (
                "provider_capacity_exhausted",
                "AI Provider 当前没有可用的上游账号或通道。",
            )
        if "upstream access forbidden" in normalized:
            return (
                "upstream_permission_error",
                "AI Provider 的上游账号未获授权，请联系 Provider 管理员。",
            )
        if "service temporarily unavailable" in normalized:
            return (
                "provider_service_unavailable",
                "AI Provider 服务暂时不可用。",
            )
        return cls._STATUS_ERRORS.get(
            provider_status,
            ("provider_error", "AI Provider 请求失败，请稍后重试。"),
        )

    def _fail(
        self,
        message: str,
        *,
        error_type: str,
        started: float,
        provider_status: int | None = None,
        provider_message: str | None = None,
        cause: Exception | None = None,
        stage: str | None = None,
    ) -> NoReturn:
        latency_ms = max(0, round((time.perf_counter() - started) * 1000))
        self._last_latency_ms = latency_ms
        self.last_request_metrics.update(
            status="failed",
            error_type=error_type,
            latency_ms=latency_ms,
            provider_status=provider_status,
        )
        safe_provider_message = self._redact_and_truncate(provider_message, 300)
        trace = current_execution.get()
        logger.warning(
            "LLM request failed model=%s base_url=%s provider_status=%s "
            "error_type=%s latency_ms=%s stage=%s conversation_id=%s client_message_id=%s "
            "request_id=%s provider_request_count=%s",
            self._redact_and_truncate(self.model, 120) or "<empty>",
            self._safe_base_url(),
            provider_status,
            error_type,
            latency_ms,
            stage,
            trace.conversation_id if trace else None,
            trace.client_message_id if trace else None,
            self.last_request_metrics.get("provider_request_id"),
            self.last_request_metrics.get("provider_request_count", 0),
        )
        error = AIUnavailableError(
            message,
            error_type=error_type,
            provider_status=provider_status,
            provider_message=safe_provider_message,
            latency_ms=latency_ms,
            stage=stage,
        )
        if cause is not None:
            raise error from cause
        raise error

    def _bounded_post(self, payload: dict, timeout: httpx.Timeout, limit: float | None):
        """A slow trickle or custom transport cannot exceed the caller's wall budget.

        Workers only perform HTTP I/O. An expired worker cannot parse or commit a
        business result. Bounds prevent accumulating unlimited abandoned requests.
        """
        transport = self.client
        endpoint = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if limit is None:
            return transport.post(endpoint, headers=headers, json=payload, timeout=timeout)
        if not _transport_slots.acquire(blocking=False):
            raise AIUnavailableError(
                "AI Provider 请求通道正忙，请稍后重试。",
                error_type="provider_busy",
                stage=self.last_request_metrics.get("stage"),
            )
        result: Future = Future()

        def invoke():
            try:
                result.set_result(
                    transport.post(endpoint, headers=headers, json=payload, timeout=timeout)
                )
            except BaseException as exc:
                result.set_exception(exc)
            finally:
                _transport_slots.release()

        self.last_request_metrics["provider_request_count"] = 1
        Thread(target=invoke, daemon=True, name="llm-transport").start()
        try:
            return result.result(timeout=limit)
        except FutureTimeoutError as exc:
            self.last_request_metrics["timeout_source"] = "wall_budget"
            raise httpx.ReadTimeout("provider stage wall-clock budget exhausted") from exc

    def _post(
        self,
        payload: dict[str, Any],
        *,
        stage: str | None = None,
        read_timeout_seconds: float | None = None,
    ) -> tuple[dict[str, Any], int, int]:
        started = time.perf_counter()
        definition = payload.get("response_format", {}).get("json_schema", {})

        def compact(value):
            return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

        self._local.request_metrics = {
            "request_bytes": compact(payload),
            "message_count": len(payload.get("messages", [])),
            "provider_request_id": uuid4().hex,
            "provider_request_count": 0,
            "stage": stage,
            "model": self._redact_and_truncate(self.model, 120),
            "provider": self._safe_base_url(),
            "strict_output": bool(definition),
            "status": "started",
            "error_type": None,
        }
        logger.info(
            "llm_request stage=%s model=%s schema_name=%s schema_bytes=%s "
            "request_bytes=%s message_count=%s",
            stage,
            self._redact_and_truncate(self.model, 120),
            definition.get("name"),
            compact(definition["schema"]) if definition else 0,
            self.last_request_metrics["request_bytes"],
            self.last_request_metrics["message_count"],
        )
        if not self.enabled:
            self._fail(
                "AI 功能当前未启用。",
                error_type="llm_disabled",
                started=started,
                stage=stage,
            )
        if not self.api_key:
            self._fail(
                "AI 服务未配置 API Key。",
                error_type="configuration_error",
                started=started,
                stage=stage,
            )
        trace = current_execution.get()
        remaining = trace.remaining(stage or "provider") if trace else None
        if remaining is not None and stage in {"response_compose", "explanation"}:
            # Reserve a small completion window for deterministic feedback. Optional
            # wording must not consume the final time needed to return a saved result.
            if remaining <= 0.1:
                self._fail(
                    "本轮剩余时间不足以润色回复，将使用已验证的结果。",
                    error_type="response_budget_exhausted",
                    started=started,
                    stage=stage,
                )
            remaining -= 0.1
        limits = [
            value
            for value in (provider_stage_budget(stage), read_timeout_seconds, remaining)
            if value is not None
        ]
        wall_limit = min(limits) if limits else None
        self.last_request_metrics["budget_seconds"] = wall_limit
        # This is metadata only, scoped to the current application request. It is
        # available to test observers without recording prompts or model reasoning.
        if trace is not None:
            if not hasattr(trace, "provider_requests"):
                trace.provider_requests = []
            trace.provider_requests.append(self.last_request_metrics)
        # Copy per request: health probes must not change the shared client's limits.
        timeout_values = self.timeout.as_dict()
        if wall_limit is not None:
            timeout_values = {
                key: min(value, wall_limit) if value is not None else wall_limit
                for key, value in timeout_values.items()
            }
        timeout = httpx.Timeout(**timeout_values)

        try:
            if wall_limit is None:
                self.last_request_metrics["provider_request_count"] = 1
            response = self._bounded_post(payload, timeout, wall_limit)
        except httpx.TimeoutException as exc:
            if trace and remaining is not None and time.monotonic() - trace.started >= trace.budget:
                self.last_request_metrics.update(
                    status="failed",
                    error_type="agent_turn_timeout",
                    latency_ms=round((time.perf_counter() - started) * 1000),
                )
                raise ExecutionTimeout(
                    stage or "provider", round((time.monotonic() - trace.started) * 1000)
                ) from exc
            kind = (
                "connect_timeout"
                if isinstance(exc, httpx.ConnectTimeout)
                else "read_timeout"
                if isinstance(exc, httpx.ReadTimeout)
                else "write_timeout"
                if isinstance(exc, httpx.WriteTimeout)
                else "pool_timeout"
                if isinstance(exc, httpx.PoolTimeout)
                else "timeout"
            )
            message = (
                f"AI Provider 等待响应超过 {timeout.read:g} 秒。"
                if kind == "read_timeout"
                else "连接 AI Provider 超时。"
                if kind == "connect_timeout"
                else "AI Provider 请求超时。"
            )
            self._fail(
                message,
                error_type=kind,
                started=started,
                stage=stage,
                cause=exc,
            )
        except AIUnavailableError as exc:
            self._fail(
                exc.safe_message,
                error_type=exc.error_type,
                started=started,
                stage=stage,
                cause=exc,
            )
        except (httpx.RequestError, httpx.InvalidURL) as exc:
            self._fail(
                "无法连接 AI Provider，请检查网络、域名或 TLS 配置。",
                error_type="connection_error",
                started=started,
                stage=stage,
                cause=exc,
            )

        latency_ms = max(0, round((time.perf_counter() - started) * 1000))
        self._last_latency_ms = latency_ms
        if not 200 <= response.status_code < 300:
            provider_message = self._provider_error_message(response)
            error_type, message = self._classify_provider_error(
                response.status_code,
                provider_message,
            )
            self._fail(
                message,
                error_type=error_type,
                provider_status=response.status_code,
                provider_message=provider_message,
                started=started,
                stage=stage,
            )

        try:
            result = response.json()
        except ValueError as exc:
            self._fail(
                "AI Provider 返回了无法识别的响应。",
                error_type="invalid_provider_response",
                provider_status=response.status_code,
                started=started,
                cause=exc,
                stage=stage,
            )
        if not isinstance(result, dict):
            self._fail(
                "AI Provider 返回了无法识别的响应。",
                error_type="invalid_provider_response",
                provider_status=response.status_code,
                started=started,
                stage=stage,
            )
        if trace:
            trace.remaining(stage or "provider")
        self.last_request_metrics.update(
            status="completed",
            error_type=None,
            latency_ms=latency_ms,
            provider_status=response.status_code,
        )
        logger.info(
            "llm_complete model=%s base_url=%s stage=%s latency_ms=%s provider_status=%s "
            "conversation_id=%s client_message_id=%s status=completed error_type=none "
            "request_id=%s provider_request_count=1",
            self._redact_and_truncate(self.model, 120),
            self._safe_base_url(),
            stage,
            latency_ms,
            response.status_code,
            trace.conversation_id if trace else None,
            trace.client_message_id if trace else None,
            self.last_request_metrics["provider_request_id"],
        )
        return result, latency_ms, response.status_code

    def _content(
        self,
        response: dict[str, Any],
        latency_ms: int,
        provider_status: int,
        *,
        stage: str | None = None,
    ) -> str:
        started = time.perf_counter() - (latency_ms / 1000)
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            self._fail(
                "AI Provider 返回了无法识别的响应。",
                error_type="invalid_provider_response",
                provider_status=provider_status,
                started=started,
                cause=exc,
                stage=stage,
            )
        if not isinstance(content, str) or not content.strip():
            self._fail(
                "AI Provider 返回了无法识别的响应。",
                error_type="invalid_provider_response",
                provider_status=provider_status,
                started=started,
                stage=stage,
            )
        if re.search(r"(?i)<(?:think|thinking|reasoning)(?:>|\s)", content):
            self._fail(
                "AI Provider 返回了不适合展示的内容。",
                error_type="invalid_provider_response",
                started=started,
                stage=stage,
                provider_status=provider_status,
            )
        return content.strip()

    def health_check(self) -> dict[str, Any]:
        checks: dict[str, dict[str, Any]] = {}
        read_timeout = positive_seconds("LLM_HEALTH_READ_TIMEOUT_SECONDS", 30)
        try:
            response, latency_ms, provider_status = self._post(
                {
                    "model": self.model,
                    "messages": [
                        {"role": "user", "content": "你好，请只回复 OK"},
                    ],
                    "temperature": 0,
                },
                stage="basic_chat",
                read_timeout_seconds=read_timeout,
            )
            reply = self._content(response, latency_ms, provider_status, stage="basic_chat")
            checks["basic_chat"] = {"status": "ok", "latency_ms": latency_ms, "reply": reply}
        except AIUnavailableError as exc:
            checks["basic_chat"] = {
                "status": "error",
                **exc.public_details,
                "message": exc.safe_message,
            }
            return {
                "status": "error",
                "model": self.model,
                "enabled": self.enabled,
                "key_present": bool(self.api_key),
                "checks": checks,
            }

        try:
            structured = self.complete_json(
                system="Return exactly the JSON object required by the schema.",
                user={"probe": "structured_output"},
                schema_name="health_check",
                schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                },
                stage="structured_output_health",
                read_timeout_seconds=read_timeout,
            )
            if structured.get("ok") is not True:
                raise AIUnavailableError(
                    "AI Provider 返回了无法识别的结构化探针结果。",
                    error_type="invalid_provider_response",
                    latency_ms=self._last_latency_ms,
                    stage="structured_output_health",
                )
            checks["structured_output"] = {"status": "ok", "latency_ms": self._last_latency_ms}
        except AIUnavailableError as exc:
            checks["structured_output"] = {
                "status": "error",
                **exc.public_details,
                "message": exc.safe_message,
            }
            return {
                "status": "degraded",
                "model": self.model,
                "enabled": self.enabled,
                "key_present": bool(self.api_key),
                "checks": checks,
            }
        return {
            "status": "ok",
            "model": self.model,
            "enabled": self.enabled,
            "key_present": bool(self.api_key),
            "checks": checks,
        }

    def complete_json(
        self,
        *,
        system: str,
        user: dict[str, Any],
        schema_name: str,
        schema: dict[str, Any],
        stage: str = "structured_output",
        read_timeout_seconds: float | None = None,
        strict_output: bool = True,
    ) -> dict[str, Any]:
        validate_strict_json_schema(schema)
        if not strict_output:
            system += (
                " Return only a JSON object, with all fields and no extra fields, matching: "
                + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
            )
        response, latency_ms, provider_status = self._post(
            {
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": json.dumps(user, ensure_ascii=False, default=str),
                    },
                ],
                **(
                    {
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {
                                "name": schema_name,
                                "strict": True,
                                "schema": schema,
                            },
                        }
                    }
                    if strict_output
                    else {}
                ),
            },
            stage=stage,
            read_timeout_seconds=read_timeout_seconds,
        )
        started = time.perf_counter() - (latency_ms / 1000)
        try:
            parsed = json.loads(self._content(response, latency_ms, provider_status, stage=stage))
        except json.JSONDecodeError as exc:
            self._fail(
                "AI Provider 返回了无法识别的响应。",
                error_type="invalid_provider_response",
                provider_status=provider_status,
                started=started,
                cause=exc,
                stage=stage,
            )
        if not isinstance(parsed, dict):
            self._fail(
                "AI Provider 返回了无法识别的响应。",
                error_type="invalid_provider_response",
                provider_status=provider_status,
                started=started,
                stage=stage,
            )
        if not Draft202012Validator(schema).is_valid(parsed):
            self._fail(
                "AI 结构化结果不符合预期格式。",
                error_type="structured_output_error",
                started=started,
                stage=stage,
                provider_status=provider_status,
            )
        return parsed

    def complete_text(
        self,
        *,
        system: str,
        user: dict[str, Any],
        stage: str = "response_compose",
    ) -> str:
        response, latency_ms, provider_status = self._post(
            {
                "model": self.model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": json.dumps(user, ensure_ascii=False, default=str),
                    },
                ],
            },
            stage=stage,
        )
        return self._content(response, latency_ms, provider_status, stage=stage)
