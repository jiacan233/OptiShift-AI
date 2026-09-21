from __future__ import annotations

import json
import threading
import time

import httpx
import pytest

from backend.app.execution import ExecutionTrace, current_execution
from backend.app.services.agent_router import agent_route_json_schema
from backend.app.models.dialogue import TurnCommand
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
    monkeypatch.setenv("LLM_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.delenv("LLM_READ_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("LLM_HEALTH_READ_TIMEOUT_SECONDS", raising=False)
    return AgentLLMClient()


def test_agent_route_schema_is_strict_and_complete() -> None:
    schema = agent_route_json_schema()
    validate_strict_json_schema(schema)
    assert set(schema["properties"]) == set(schema["required"])
    assert "edits" in schema["required"] and "staffing_constraints" in schema["required"]
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
    assert payload["messages"][0]["content"] == "test"
    assert result == {"ok": True}


def _route_completion(client):
    return client.complete_json(
        system="Route the current request.", user={"message": "hello"},
        schema_name="agent_route", schema=agent_route_json_schema(),
    )


@pytest.mark.parametrize("detection", ["model", "host", "rejection"])
def test_json_object_provider_returns_existing_agent_route(monkeypatch, detection):
    client = _client(monkeypatch)
    if detection == "model":
        client.model = "deepseek-chat"
    elif detection == "host":
        client.base_url = "https://api.deepseek.com/v1"
    route = TurnCommand().model_dump(mode="json")
    requests = []

    def post(_self, _url, **kwargs):
        requests.append(kwargs["json"])
        if detection == "rejection" and len(requests) == 1:
            return _response("This response_format type is unavailable now", 400)
        return _response(json.dumps(route))

    monkeypatch.setattr(httpx.Client, "post", post)
    assert TurnCommand.model_validate(_route_completion(client)).execution == "none"
    assert len(requests) == (2 if detection == "rejection" else 1)
    assert requests[-1]["response_format"] == {"type": "json_object"}
    prompt = requests[-1]["messages"][0]["content"]
    assert "ONLY a JSON object" in prompt and "TurnCommand Schema" in prompt
    assert json.dumps(agent_route_json_schema(), ensure_ascii=False, separators=(",", ":")) in prompt


@pytest.mark.parametrize("model", ["gpt-4.1-mini", "deepseek-chat"])
@pytest.mark.parametrize("recover", [False, True])
@pytest.mark.parametrize("failure,reason", [
    ("not JSON", "Expecting value"),
    ('{"execution":"invalid"}', "literal_error"),
    (json.dumps(TurnCommand().model_dump(mode="json") | {"target_week": "2026-02-30"}), "target_week"),
    ("{}", "constraint required"),
    ("[]", "JSON root must be an object"),
    ('{"execution":"none"}', "constraint required"),
])
def test_structured_validation_retries_only_once(monkeypatch, caplog, model, recover, failure, reason):
    client = _client(monkeypatch)
    client.model = model
    valid = TurnCommand().model_dump(mode="json")
    requests = []

    def post(_self, _url, **kwargs):
        requests.append(kwargs["json"])
        return _response(json.dumps(valid) if recover and len(requests) == 2 else failure)

    monkeypatch.setattr(httpx.Client, "post", post)
    if recover:
        assert _route_completion(client) == valid
    else:
        with pytest.raises(AIUnavailableError) as error:
            _route_completion(client)
        assert error.value.error_type in {"invalid_json", "structured_output_error"}
        assert error.value.__cause__ is not None or failure == "[]"
    assert len(requests) == 2
    assert reason in caplog.text
    expected_format = "json_object" if model == "deepseek-chat" else "json_schema"
    assert all(r["response_format"]["type"] == expected_format for r in requests)


def test_deepseek_health_is_not_degraded(monkeypatch):
    client = _client(monkeypatch)
    client.model = "deepseek-chat"

    def post(_self, _url, **kwargs):
        if "response_format" in kwargs["json"]:
            assert kwargs["json"]["response_format"] == {"type": "json_object"}
            return _response('{"ok":true}')
        return _response("OK")

    monkeypatch.setattr(httpx.Client, "post", post)
    assert client.health_check()["status"] == "ok"


def test_format_negotiation_does_not_reset_validation_retry_limit(monkeypatch):
    client = _client(monkeypatch)
    requests = []

    def post(_self, _url, **kwargs):
        requests.append(kwargs["json"])
        if len(requests) == 1:
            return _response("This response_format type is unavailable now", 400)
        return _response("not JSON")

    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(AIUnavailableError, match="无法识别"):
        _route_completion(client)
    assert [r["response_format"]["type"] for r in requests] == [
        "json_schema", "json_object", "json_object",
    ]
    assert client.last_request_metrics["validation_retries"] == 1


def test_health_check_requires_basic_and_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    requests: list[dict[str, object]] = []
    timeouts: list[httpx.Timeout] = []

    def fake_post(_url: str, **kwargs: object) -> httpx.Response:
        payload = kwargs["json"]
        requests.append(payload)
        timeouts.append(kwargs["timeout"])
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
    assert timeouts[0].read == 30
    # Structured calls subtract elapsed time from the shared retry budget.
    assert 0 < timeouts[1].read <= 30
    assert client.timeout.read == 120


def test_health_timeout_override_uses_effective_timeout_in_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch)

    def fail_post(_self, *_args, **_kwargs):
        raise httpx.ReadTimeout("probe")

    monkeypatch.setattr(httpx.Client, "post", fail_post)
    result = client.health_check()
    assert result["checks"]["basic_chat"]["error_type"] == "read_timeout"
    assert "30" in result["checks"]["basic_chat"]["message"]
    assert "120" not in result["checks"]["basic_chat"]["message"]


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


@pytest.mark.parametrize("stage,budget_env,budget", [
    ("response_compose", "LLM_RESPONSE_BUDGET_SECONDS", 3),
    ("explanation", "LLM_RESPONSE_BUDGET_SECONDS", 3),
    ("intent_parse", "LLM_SEMANTIC_BUDGET_SECONDS", 7),
])
def test_stage_budget_caps_every_http_phase_and_records_safe_request(
    monkeypatch, stage, budget_env, budget
):
    client = _client(monkeypatch)
    monkeypatch.setenv(budget_env, str(budget))
    client.base_url = "https://user:password@example.test/private?token=secret"
    execution = ExecutionTrace("conversation", "turn")
    execution.budget = 2
    token = current_execution.set(execution)

    def fake_post(_self, _url, **kwargs):
        assert all(0 < value <= 2 for value in kwargs["timeout"].as_dict().values())
        return _response("OK")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    try:
        assert client.complete_text(system="PRIVATE_PROMPT", user={}, stage=stage) == "OK"
        assert len(execution.provider_requests) == 1
        metrics = execution.provider_requests[0]
        assert metrics["provider_request_count"] == 1
        assert metrics["status"] == "completed"
        assert metrics["stage"] == stage
        assert metrics["provider"] == "example.test"
        assert metrics["model"] == client.model
        assert metrics["provider_request_id"]
        assert metrics["latency_ms"] >= 0
        assert metrics["error_type"] is None
        assert not any(secret in json.dumps(metrics) for secret in (
            "sk-test-secret", "password", "token=secret", "PRIVATE_PROMPT",
        ))
    finally:
        current_execution.reset(token)


def test_response_wall_budget_stops_stalled_transport_without_late_result(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setenv("LLM_RESPONSE_BUDGET_SECONDS", "0.03")
    release = threading.Event()
    finished = threading.Event()
    calls = []

    def stalled_post(_self, _url, **_kwargs):
        calls.append(1)
        release.wait(timeout=1)
        finished.set()
        return _response("late result")

    monkeypatch.setattr(httpx.Client, "post", stalled_post)
    started = time.monotonic()
    try:
        with pytest.raises(AIUnavailableError) as error:
            client.complete_text(system="test", user={})
        assert time.monotonic() - started < 0.3
        assert error.value.error_type == "read_timeout"
        assert error.value.stage == "response_compose"
        metrics = dict(client.last_request_metrics)
        assert metrics["status"] == "failed"
        assert metrics["timeout_source"] == "wall_budget"
        assert len(calls) == metrics["provider_request_count"] == 1
    finally:
        release.set()
        assert finished.wait(timeout=1)
    assert client.last_request_metrics == metrics
