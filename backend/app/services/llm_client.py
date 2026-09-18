from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from copy import deepcopy
from typing import Any, NoReturn
from urllib.parse import urlsplit, urlunsplit

import httpx


logger = logging.getLogger("optishift.llm")


def _redact_message(value: str | None, limit: int, secrets: tuple[str, ...] = ()) -> str | None:
    if not value:
        return None
    safe = value
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

    def __init__(self) -> None:
        self.enabled = os.getenv("LLM_ENABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        self.api_key = os.getenv("LLM_API_KEY", "").strip()
        self.model = os.getenv("LLM_MODEL", "gpt-4.1-mini").strip()
        self.base_url = os.getenv(
            "LLM_BASE_URL", "https://api.openai.com/v1"
        ).rstrip("/")
        self._last_latency_ms = 0
        self._configuration_error: str | None = None
        try:
            self.timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "5"))
            if not math.isfinite(self.timeout) or self.timeout <= 0:
                raise ValueError
        except (TypeError, ValueError):
            self.timeout = 5.0
            self._configuration_error = "LLM_TIMEOUT_SECONDS 配置无效。"

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
            safe_url = urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
        except ValueError:
            safe_url = self.base_url.split("?", 1)[0].split("#", 1)[0]
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
        safe_provider_message = self._redact_and_truncate(provider_message, 300)
        logger.warning(
            "LLM request failed model=%s base_url=%s provider_status=%s "
            "error_type=%s latency_ms=%s provider_message=%r",
            self._redact_and_truncate(self.model, 120) or "<empty>",
            self._safe_base_url(),
            provider_status,
            error_type,
            latency_ms,
            safe_provider_message,
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

    def _post(
        self,
        payload: dict[str, Any],
        *,
        stage: str | None = None,
    ) -> tuple[dict[str, Any], int, int]:
        started = time.perf_counter()
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
        if self._configuration_error:
            self._fail(
                self._configuration_error,
                error_type="configuration_error",
                started=started,
                stage=stage,
            )

        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            self._fail(
                "AI Provider 请求超时。",
                error_type="timeout",
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
        return content.strip()

    def health_check(self) -> dict[str, Any]:
        checks: dict[str, dict[str, Any]] = {}
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
                stage="structured_output",
            )
            if structured.get("ok") is not True:
                raise AIUnavailableError(
                    "AI Provider 返回了无法识别的结构化探针结果。",
                    error_type="invalid_provider_response",
                    latency_ms=self._last_latency_ms,
                    stage="structured_output",
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
    ) -> dict[str, Any]:
        validate_strict_json_schema(schema)
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
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "strict": True,
                        "schema": schema,
                    },
                },
            },
            stage=stage,
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
        return parsed

    def complete_text(
        self,
        *,
        system: str,
        user: dict[str, Any],
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
            }
        )
        return self._content(response, latency_ms, provider_status)
