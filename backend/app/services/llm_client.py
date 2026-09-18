from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from typing import Any, NoReturn
from urllib.parse import urlsplit, urlunsplit

import httpx


logger = logging.getLogger("optishift.llm")


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
    ) -> None:
        self.safe_message = message
        self.error_type = error_type
        self.provider_status = provider_status
        self.provider_message = provider_message
        self.latency_ms = latency_ms
        super().__init__(message)

    @property
    def public_details(self) -> dict[str, str | int | None]:
        return {
            "error_type": self.error_type,
            "provider_status": self.provider_status,
        }


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
        self._configuration_error: str | None = None
        try:
            self.timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "5"))
            if not math.isfinite(self.timeout) or self.timeout <= 0:
                raise ValueError
        except (TypeError, ValueError):
            self.timeout = 5.0
            self._configuration_error = "LLM_TIMEOUT_SECONDS 配置无效。"

    def _redact_and_truncate(self, value: str | None, limit: int) -> str | None:
        if not value:
            return None
        safe = re.sub(r"\s+", " ", value).strip()
        if self.api_key:
            safe = safe.replace(self.api_key, "[REDACTED]")
        safe = re.sub(
            r"(?i)\bBearer\s+[^\s,;]+",
            "Bearer [REDACTED]",
            safe,
        )
        safe = re.sub(
            r"(?i)(api[_ -]?key\s*[:=]\s*)[^\s,;]+",
            r"\1[REDACTED]",
            safe,
        )
        safe = re.sub(r"\bsk-[A-Za-z0-9._-]{6,}\b", "[REDACTED_API_KEY]", safe)
        if not safe:
            return None
        return safe[:limit]

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
        )
        if cause is not None:
            raise error from cause
        raise error

    def _post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
        started = time.perf_counter()
        if not self.enabled:
            self._fail(
                "AI 功能当前未启用。",
                error_type="llm_disabled",
                started=started,
            )
        if not self.api_key:
            self._fail(
                "AI 服务未配置 API Key。",
                error_type="configuration_error",
                started=started,
            )
        if self._configuration_error:
            self._fail(
                self._configuration_error,
                error_type="configuration_error",
                started=started,
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
                cause=exc,
            )
        except (httpx.RequestError, httpx.InvalidURL) as exc:
            self._fail(
                "无法连接 AI Provider，请检查网络、域名或 TLS 配置。",
                error_type="connection_error",
                started=started,
                cause=exc,
            )

        latency_ms = max(0, round((time.perf_counter() - started) * 1000))
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
            )
        if not isinstance(result, dict):
            self._fail(
                "AI Provider 返回了无法识别的响应。",
                error_type="invalid_provider_response",
                provider_status=response.status_code,
                started=started,
            )
        return result, latency_ms, response.status_code

    def _content(
        self,
        response: dict[str, Any],
        latency_ms: int,
        provider_status: int,
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
            )
        if not isinstance(content, str) or not content.strip():
            self._fail(
                "AI Provider 返回了无法识别的响应。",
                error_type="invalid_provider_response",
                provider_status=provider_status,
                started=started,
            )
        return content.strip()

    def health_check(self) -> tuple[str, int]:
        response, latency_ms, provider_status = self._post(
            {
                "model": self.model,
                "messages": [
                    {"role": "user", "content": "你好，请只回复 OK"},
                ],
                "temperature": 0,
            }
        )
        return self._content(response, latency_ms, provider_status), latency_ms

    def complete_json(
        self,
        *,
        system: str,
        user: dict[str, Any],
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
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
            }
        )
        started = time.perf_counter() - (latency_ms / 1000)
        try:
            parsed = json.loads(self._content(response, latency_ms, provider_status))
        except json.JSONDecodeError as exc:
            self._fail(
                "AI Provider 返回了无法识别的响应。",
                error_type="invalid_provider_response",
                provider_status=provider_status,
                started=started,
                cause=exc,
            )
        if not isinstance(parsed, dict):
            self._fail(
                "AI Provider 返回了无法识别的响应。",
                error_type="invalid_provider_response",
                provider_status=provider_status,
                started=started,
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
