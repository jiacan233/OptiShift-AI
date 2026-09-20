from __future__ import annotations

import json
import socket
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from backend.app.config import positive_seconds
from backend.app.execution import ExecutionTrace, current_execution, execution_stage
from backend.app.services.agent_router import AgentRoute, AgentRouter
from backend.app.services.llm_client import AgentLLMClient, AIUnavailableError


@pytest.mark.parametrize("value", ["0", "-1", "abc", "NaN", "inf"])
@pytest.mark.parametrize(
    "name,default",
    [
        ("LLM_CONNECT_TIMEOUT_SECONDS", 8),
        ("LLM_READ_TIMEOUT_SECONDS", 120),
        ("LLM_WRITE_TIMEOUT_SECONDS", 50),
        ("LLM_POOL_TIMEOUT_SECONDS", 8),
        ("AGENT_TURN_TIMEOUT_SECONDS", 300),
        ("AGENT_TURN_LEASE_SECONDS", 360),
        ("LLM_HEALTH_READ_TIMEOUT_SECONDS", 30),
        ("SOLVER_MAX_TIME_SECONDS", 10),
    ],
)
def test_invalid_timeout_falls_back(monkeypatch, name, default, value):
    monkeypatch.setenv(name, value)
    assert positive_seconds(name, default) == default


def test_split_timeouts_and_legacy_ignored(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "5")
    with AgentLLMClient() as client:
        assert client.timeout.as_dict() == {"connect": 8, "read": 120, "write": 50, "pool": 8}
    monkeypatch.setenv("LLM_READ_TIMEOUT_SECONDS", "61")
    with AgentLLMClient() as client:
        assert client.timeout.read == 61
        assert client.timeout.connect == 8


@pytest.mark.parametrize(
    "exception,kind",
    [(httpx.ConnectTimeout, "connect_timeout"), (httpx.ReadTimeout, "read_timeout")],
)
def test_transport_timeout_classification(monkeypatch, exception, kind):
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    def handler(request):
        assert request.extensions["timeout"]["connect"] == 8
        assert request.extensions["timeout"]["read"] == 120
        raise exception("private transport error")

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        with AgentLLMClient(transport) as client, pytest.raises(AIUnavailableError) as error:
            client.complete_text(system="test", user={}, stage="agent_route")
        assert error.value.error_type == kind
        assert error.value.stage == "agent_route"
        assert error.value.latency_ms >= 0
        assert "private" not in str(error.value.public_details)


def test_provider_client_reused_and_closed():
    with AgentLLMClient() as client:
        transport = client.client
        assert client.client is transport
    assert transport.is_closed


def test_router_stage_and_hidden_reasoning_ignored(monkeypatch, balanced_employees):
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    route = AgentRoute(
        intent="replan",
        mutation_requested=True,
        target_week=date(2026, 10, 5),
        employees=["E01"],
        changes=[{"employee_id": "E01", "day": "Mon", "type": "leave"}],
    )

    def handler(request):
        from tests.test_agent_router import decision, operation
        name = json.loads(request.content)["response_format"]["json_schema"]["name"]
        payload = decision(intent="replan", mutation_requested=True, employees=["E01"]) if name == "agent_route_lite" else {
            "operations": [operation()], "minimize_changes": False, "clarification": None,
        }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(payload),
                            "reasoning_content": "SECRET_HIDDEN_REASONING",
                        }
                    }
                ]
            },
        )

    events = []
    execution = ExecutionTrace("conversation", "request", events.append)
    token = current_execution.set(execution)
    try:
        with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
            client = AgentLLMClient(transport)
            result = AgentRouter(client).route(
                "我现在要重新排班，2026年第41周，E01周一请假了，要咋排？",
                employees=balanced_employees,
                recent_messages=[],
            )
        assert (result.target_iso_year, result.target_iso_week) == (2026, 41)
        assert result.changes[0].employee_id == "E01"
        assert [(e["stage"], e["status"]) for e in events] == [
            ("agent_route", "started"),
            ("agent_route_lite", "started"),
            ("agent_route_lite", "completed"),
            ("agent_mutation", "started"),
            ("agent_mutation", "completed"),
            ("agent_route", "completed"),
        ]
        assert "SECRET_HIDDEN_REASONING" not in json.dumps(events)
        assert events[-1]["details"]["changes"][0]["day"] == "Mon"
    finally:
        current_execution.reset(token)


@pytest.fixture
def execution_client(tmp_path, monkeypatch):
    import backend.app.database as db
    from backend.app.api import dependencies
    from backend.app.main import app

    db.database.path = tmp_path / "execution.db"
    monkeypatch.setattr(dependencies.agent_llm_client, "enabled", False)
    monkeypatch.setenv("LLM_ENABLED", "false")
    with TestClient(app) as client:
        yield client
    db.database.dispose()


def conversation(client):
    return client.post("/api/agent/conversations", json={"browser_workspace_id": "events"}).json()[
        "conversation_id"
    ]


def body(key="once"):
    return {
        "browser_workspace_id": "events",
        "client_message_id": key,
        "content": "2026年第41周生成排班",
        "current_week_start": "2026-10-05",
        "trusted_action": {"intent": "generate", "target_week": "2026-10-05"},
    }


def frames(response):
    return [
        (frame.splitlines()[0][7:], json.loads(frame.splitlines()[1][6:]))
        for frame in response.text.strip().split("\n\n")
    ]


@pytest.mark.parametrize("drop_terminal", [False, True])
def test_sse_and_post_share_idempotent_draft_and_persist_events(execution_client, monkeypatch, drop_terminal):
    from backend.app.api import dependencies
    from backend.app.api import agent as agent_api

    if drop_terminal:
        response_class = agent_api.StreamingResponse

        def losing_response(content, **kwargs):
            async def filter_terminal():
                async for frame in content:
                    if not frame.startswith("event: result"):
                        yield frame
            return response_class(filter_terminal(), **kwargs)

        monkeypatch.setattr(agent_api, "StreamingResponse", losing_response)

    client = execution_client
    cid = conversation(client)
    original = dependencies.scheduling_service.solver.solve
    solves = []

    def solve(*args, **kwargs):
        solves.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(dependencies.scheduling_service.solver, "solve", solve)
    original_save = dependencies.scheduling_service.schedules.save_draft
    saves = []

    def save(*args, **kwargs):
        saved = original_save(*args, **kwargs)
        saves.append(saved.schedule_id)
        return saved

    monkeypatch.setattr(dependencies.scheduling_service.schedules, "save_draft", save)
    path = f"/api/agent/conversations/{cid}/messages"
    response = client.post(path + "/stream", json=body())
    assert response.headers["content-type"].startswith("text/event-stream")
    stream = frames(response)
    assert stream[-1][0] == ("execution" if drop_terminal else "result"), stream[-1]
    result = client.post(path, json=body()).json() if drop_terminal else stream[-1][1]
    assert result["schedule_result"]["status"] == "feasible"
    stages = [(e[1]["stage"], e[1]["status"]) for e in stream if e[0] == "execution"]
    assert stages[0] == ("turn_started", "completed")
    assert stages[-1] == ("turn_completed", "completed")
    for stage in [
        "agent_route",
        "resolve_context",
        "load_schedule",
        "solver",
        "validator",
        "save_draft",
    ]:
        assert (stage, "started") in stages and (stage, "completed") in stages
    replay = client.post(path, json=body()).json()
    assert replay == result
    assert len(solves) == 1
    assert saves == [result["schedule_result"]["schedule_id"]]
    detail = client.get(
        f"/api/agent/conversations/{cid}", params={"browser_workspace_id": "events"}
    ).json()
    assert len(detail["messages"]) == 2
    assert detail["messages"][-1]["metadata_json"]["execution_events"] == result["execution_events"]


def test_router_failure_has_timeline_before_any_tool(execution_client, monkeypatch):
    from backend.app.api import dependencies

    def fail(*args, **kwargs):
        with execution_stage("agent_route"):
            raise AIUnavailableError(
                "AI Provider 等待响应超过 120 秒。",
                error_type="read_timeout",
                stage="agent_route",
                latency_ms=120021,
            )

    monkeypatch.setattr(dependencies.agent_service.router, "route", fail)
    cid = conversation(execution_client)
    stream = frames(
        execution_client.post(f"/api/agent/conversations/{cid}/messages/stream", json=body())
    )
    assert stream[-1][0] == "error"
    details = stream[-1][1]["details"]
    assert details["stage"] == "agent_route"
    assert details["latency_ms"] == 120021
    assert details["error_type"] == "read_timeout"
    assert details["tool_calls"] == []
    assert [(e["stage"], e["status"]) for e in details["execution_events"]][-3:] == [
        ("agent_route", "started"),
        ("agent_route", "failed"),
        ("turn_failed", "failed"),
    ]


def test_disconnected_sink_does_not_abort_or_duplicate(execution_client):
    from backend.app.api import dependencies

    cid = conversation(execution_client)
    payload = body()
    from backend.app.services.agent_router import TrustedAgentAction

    payload["trusted_action"] = TrustedAgentAction.model_validate(payload["trusted_action"])
    payload["current_week_start"] = date(2026, 10, 5)

    def disconnected(_event):
        raise BrokenPipeError("observer disconnected")

    result = dependencies.agent_service.send_message(
        conversation_id=cid, event_sink=disconnected, **payload
    )
    replay = execution_client.post(f"/api/agent/conversations/{cid}/messages", json=body()).json()
    assert replay["schedule_result"]["schedule_id"] == result["schedule_result"]["schedule_id"]


def test_budget_after_committed_draft_recovers_same_result(execution_client, monkeypatch):
    from backend.app.api import dependencies

    original = dependencies.agent_tools.run

    def after_commit(name, **kwargs):
        result = original(name, **kwargs)
        if name == "generate_schedule":
            trace = current_execution.get()
            trace.started -= trace.budget + 1
            trace.remaining("response_compose")
        return result

    monkeypatch.setattr(dependencies.agent_tools, "run", after_commit)
    cid = conversation(execution_client)
    path = f"/api/agent/conversations/{cid}/messages"
    response = execution_client.post(path, json=body())
    assert response.status_code == 200, response.text
    first = response.json()
    second = execution_client.post(path, json=body()).json()
    assert first["schedule_result"]["schedule_id"] == second["schedule_result"]["schedule_id"]


def test_live_sse_heartbeat_disconnect_and_concurrent_replay(execution_client, monkeypatch):
    from backend.app.api import dependencies
    from backend.app.main import app

    release = threading.Event()
    completed = threading.Event()
    original_route = dependencies.agent_service.router.route
    original_send = dependencies.agent_service.send_message
    original_solve = dependencies.scheduling_service.solver.solve
    solves = []

    def paused_route(*args, **kwargs):
        assert release.wait(20)
        return original_route(*args, **kwargs)

    def observed_send(**kwargs):
        try:
            return original_send(**kwargs)
        finally:
            if kwargs.get("event_sink"):
                completed.set()

    def solve(*args, **kwargs):
        solves.append(1)
        return original_solve(*args, **kwargs)

    monkeypatch.setattr(dependencies.agent_service.router, "route", paused_route)
    monkeypatch.setattr(dependencies.agent_service, "send_message", observed_send)
    monkeypatch.setattr(dependencies.scheduling_service.solver, "solve", solve)
    cid = conversation(execution_client)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    path = f"/api/agent/conversations/{cid}/messages"
    try:
        # Starting the thread does not mean Uvicorn is already listening.
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "SSE test server did not become ready"
        with httpx.Client(
            base_url=f"http://127.0.0.1:{sock.getsockname()[1]}", timeout=15
        ) as client:
            with client.stream("POST", path + "/stream", json=body()) as response:
                lines = response.iter_lines()
                assert next(lines) == "event: execution"
                assert json.loads(next(lines)[6:])["stage"] == "turn_started"
                assert not completed.is_set()
                duplicate = client.post(path, json=body())
                assert duplicate.status_code == 409
                assert any(line == "event: heartbeat" for line in lines)
                assert not completed.is_set()
            # The real HTTP observer disconnects before the Router is released.
            release.set()
            assert completed.wait(10)
            result = client.post(path, json=body()).json()
            replay = client.post(path, json=body()).json()
            assert result == replay
            assert result["schedule_result"]["status"] == "feasible"
            assert len(solves) == 1
            assert all(e["stage"] != "heartbeat" for e in result["execution_events"])
    finally:
        release.set()
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()


def test_week41_replan_with_provider_schema_and_no_reasoning(execution_client, monkeypatch):
    from backend.app.api import dependencies

    client = execution_client
    for week in ["2026-09-28", "2026-10-05"]:
        draft = client.post("/api/schedule/generate", json={"week_start": week}).json()
        confirmed = client.post(
            "/api/schedule/confirm",
            json={
                "schedule_id": draft["schedule_id"],
                "version": draft["version"],
            },
        )
        assert confirmed.status_code == 200
    def staged_response(request):
        from tests.test_agent_router import decision, operation
        data = json.loads(request.content)
        name = data.get("response_format", {}).get("json_schema", {}).get("name")
        payload = decision(intent="replan", mutation_requested=True, employees=["E01"]) if name == "agent_route_lite" else {
            "operations": [operation()], "minimize_changes": False, "clarification": None,
        }
        return httpx.Response(200, json={"choices": [{"message": {
            "content": json.dumps(payload), "reasoning_content": "DO_NOT_EXPOSE_REASONING",
        }}]})
    transport = httpx.Client(transport=httpx.MockTransport(staged_response))
    monkeypatch.setattr(dependencies.agent_llm_client, "_client", transport)
    monkeypatch.setattr(dependencies.agent_llm_client, "enabled", True)
    monkeypatch.setattr(dependencies.agent_llm_client, "api_key", "private-test-key")
    cid = conversation(client)
    payload = body("week41-replan")
    payload.pop("trusted_action")
    payload["content"] = "我现在要重新排班，2026年第41周，E01周一请假了，要咋排？"
    try:
        response = client.post(f"/api/agent/conversations/{cid}/messages/stream", json=payload)
        kind, result = frames(response)[-1]
        assert kind == "result", result
        assert result["intent"] == "replan"
        assert result["context"]["target_week"] == "2026-10-05"
        assert result["schedule_result"]["status"] in {"feasible", "infeasible"}
        events = result["execution_events"]
        for stage in ["agent_route", "resolve_context", "load_schedule", "solver", "validator"]:
            assert any(e["stage"] == stage and e["status"] == "completed" for e in events)
        if result["schedule_result"]["status"] == "feasible":
            assert all(
                a["employee_id"] != "E01" or a["day"] != "Mon"
                for a in result["schedule_result"]["schedule"]["assignments"]
            )
        history = client.get(
            f"/api/agent/conversations/{cid}", params={"browser_workspace_id": "events"}
        )
        assert "DO_NOT_EXPOSE_REASONING" not in response.text + history.text
        assert "private-test-key" not in response.text + history.text
    finally:
        transport.close()


@pytest.mark.parametrize("delay,read_timeout,success", [(1, 2, True), (3, 2, False)])
def test_real_http_read_timeout(monkeypatch, delay, read_timeout, success):
    """Real socket exercises HTTPX timers; no billable Provider requests."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            time.sleep(delay)
            content = json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_API_KEY", "local-test-key")
    monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("LLM_READ_TIMEOUT_SECONDS", str(read_timeout))
    try:
        with AgentLLMClient() as client:
            if success:
                assert client.complete_text(system="test", user={}, stage="agent_route") == "OK"
            else:
                with pytest.raises(AIUnavailableError) as error:
                    client.complete_text(system="test", user={}, stage="agent_route")
                assert error.value.error_type == "read_timeout"
                assert 1000 <= error.value.latency_ms <= 5000
                assert error.value.stage == "agent_route"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
