from __future__ import annotations

import json

import httpx
import pytest

from backend.app.services.agent_router import agent_route_json_schema
from backend.app.services.llm_client import (
    AgentLLMClient,
    AIUnavailableError,
    validate_strict_json_schema,
)


@pytest.fixture(autouse=True)
def close_clients(monkeypatch):
    clients = []
    original = AgentLLMClient.__init__

    def initialize(self, *args, **kwargs):
        original(self, *args, **kwargs)
        clients.append(self)

    monkeypatch.setattr(AgentLLMClient, "__init__", initialize)
    yield
    for client in clients:
        client.close()


def _response(content: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={"choices": [{"message": {"content": content}}]}
        if status_code < 300
        else {"error": {"message": content}},
    )


def _client(monkeypatch: pytest.MonkeyPatch) -> AgentLLMClient:
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_API_KEY", "sk-test-secret")
    return AgentLLMClient()


def test_agent_route_schema_is_strict_and_complete() -> None:
    schema = agent_route_json_schema()
    validate_strict_json_schema(schema)
    assert set(schema["properties"]) == set(schema["required"])
    assert "operations" in schema["required"]
    assert "$ref" not in json.dumps(schema)


def test_complete_json_sends_strict_json_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured.update(kwargs)
        return _response('{"ok": true}')

    monkeypatch.setattr(
        httpx.Client, "post", lambda self, *args, **kwargs: fake_post(*args, **kwargs)
    )
    result = client.complete_json(
        system="test",
        user={"message": "hello"},
        schema_name="probe",
        schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        },
    )

    payload = captured["json"]
    assert isinstance(payload, dict)
    response_format = payload["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert result == {"ok": True}


def test_health_check_requires_basic_and_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    requests: list[dict[str, object]] = []

    def fake_post(_url: str, **kwargs: object) -> httpx.Response:
        payload = kwargs["json"]
        requests.append(payload)
        if "response_format" in payload:
            return _response('{"ok": true}')
        return _response("OK")

    monkeypatch.setattr(
        httpx.Client, "post", lambda self, *args, **kwargs: fake_post(*args, **kwargs)
    )
    result = client.health_check()

    assert result["status"] == "ok"
    assert result["checks"]["basic_chat"]["status"] == "ok"
    assert result["checks"]["structured_output"]["status"] == "ok"
    assert len(requests) == 2


def test_health_check_reports_degraded_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    calls = 0

    def fake_post(_url: str, **kwargs: object) -> httpx.Response:
        nonlocal calls
        calls += 1
        if "response_format" in kwargs["json"]:
            return _response(
                "Invalid schema for response_format 'agent_route': missing operations", 400
            )
        return _response("OK")

    monkeypatch.setattr(
        httpx.Client, "post", lambda self, *args, **kwargs: fake_post(*args, **kwargs)
    )
    result = client.health_check()

    assert result["status"] == "degraded"
    check = result["checks"]["structured_output"]
    assert check["error_type"] == "invalid_request"
    assert check["provider_status"] == 400
    assert "missing operations" in check["provider_message"]
    assert calls == 2


def test_health_check_stops_after_basic_auth_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)

    def fake_post(_url: str, **_kwargs: object) -> httpx.Response:
        return _response("invalid key", 401)

    monkeypatch.setattr(
        httpx.Client, "post", lambda self, *args, **kwargs: fake_post(*args, **kwargs)
    )
    result = client.health_check()

    assert result["status"] == "error"
    assert result["checks"]["basic_chat"]["error_type"] == "authentication_error"
    assert "structured_output" not in result["checks"]


def test_provider_message_is_redacted_before_public_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client(monkeypatch)
    error = AIUnavailableError(
        "provider failed",
        error_type="invalid_request",
        provider_status=400,
        provider_message=(
            "Authorization: Bearer sk-test-secret; "
            "https://user:password@example.test/path?api_key=secret"
        ),
        latency_ms=821,
        stage="structured_output",
    )

    details = error.public_details
    serialized = json.dumps(details)
    assert "sk-test-secret" not in serialized
    assert "password@example" not in serialized
    assert "Bearer sk-test-secret" not in serialized
    assert details["latency_ms"] == 821
    assert details["stage"] == "structured_output"
