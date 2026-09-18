from __future__ import annotations

import json
import os
from typing import Any

import httpx


class AIUnavailableError(RuntimeError):
    """Raised when a configured LLM cannot produce a trustworthy response."""


class AgentLLMClient:
    """Small OpenAI-compatible client shared by routing and response composition."""

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
        self.timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "5"))

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            raise AIUnavailableError("The AI assistant is disabled")
        if not self.api_key:
            raise AIUnavailableError("The AI provider is not configured")
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise TypeError("Provider response is not an object")
            return result
        except AIUnavailableError:
            raise
        except Exception as exc:
            raise AIUnavailableError(
                f"The AI provider request failed ({type(exc).__name__})"
            ) from exc

    @staticmethod
    def _content(response: dict[str, Any]) -> str:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIUnavailableError("The AI provider returned an invalid response") from exc
        if not isinstance(content, str) or not content.strip():
            raise AIUnavailableError("The AI provider returned an empty response")
        return content

    def complete_json(
        self,
        *,
        system: str,
        user: dict[str, Any],
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        response = self._post(
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
        try:
            parsed = json.loads(self._content(response))
        except (json.JSONDecodeError, TypeError) as exc:
            raise AIUnavailableError("The AI provider returned invalid structured output") from exc
        if not isinstance(parsed, dict):
            raise AIUnavailableError("The AI provider returned invalid structured output")
        return parsed

    def complete_text(
        self,
        *,
        system: str,
        user: dict[str, Any],
    ) -> str:
        response = self._post(
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
        return self._content(response)
