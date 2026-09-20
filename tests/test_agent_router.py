"""Router contracts and safety at the real provider transport boundary."""
import json
import time

import httpx
import pytest
from pydantic import ValidationError

from backend.app.database import DEMO_EMPLOYEES
from backend.app.models import Employee
from backend.app.services.agent_router import (
    AgentDomain, AgentIntent, AgentRoute, AgentRouter, ForcePlan, MutationPlan, RouterDecision, SpeechAct, TrustedAgentAction,
    UnknownAgentEmployeeError, agent_route_json_schema, lite_router_json_schema,
)
from backend.app.services.llm_client import AgentLLMClient, AIUnavailableError, strict_json_schema, validate_strict_json_schema
from backend.app.services.router_stages import schema_bytes


@pytest.fixture
def employees():
    return [Employee(**row) for row in DEMO_EMPLOYEES]


def decision(**kwargs):
    return {"intent": "ask", "domain": "scheduling", "speech_act": "question", "mutation_requested": False, "employees": [],
            "force_or_override_intent": False, "clarification_required": False,
            "question_type": "general_question", **kwargs}


def operation(employee="E01", day="Mon", **kwargs):
    return {"operation": "add", "employee_id": employee, "type": "leave", "day": day, "shift": None, **kwargs}


@pytest.fixture
def router_factory(monkeypatch):
    clients = []
    def create(*responses):
        monkeypatch.setenv("LLM_ENABLED", "true")
        monkeypatch.setenv("LLM_API_KEY", "local-test-key")
        calls = []
        pending = iter(responses)
        def handle(request):
            calls.append((json.loads(request.content), request.extensions["timeout"]))
            response = next(pending)
            if isinstance(response, Exception):
                raise response
            if callable(response):
                response = response()
            if isinstance(response, httpx.Response):
                return response
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(response)}}]})
        transport = httpx.Client(transport=httpx.MockTransport(handle))
        clients.append(transport)
        return AgentRouter(AgentLLMClient(transport)), calls
    yield create
    for client in clients:
        client.close()


def route(router, employees, text="你好", **kwargs):
    return router.route(text, employees=employees, recent_messages=[], **kwargs)


def test_lite_and_specialized_schemas_are_small_strict_and_separate():
    old = schema_bytes(agent_route_json_schema())
    new = lite_router_json_schema()
    assert schema_bytes(new) < 2000 < old
    for model in (RouterDecision, MutationPlan, ForcePlan):
        schema = strict_json_schema(model.model_json_schema())
        validate_strict_json_schema(schema)
        assert schema_bytes(schema) < old / 2
    assert not ({"read_query", "operations", "changes", "requested_overrides"} & new["properties"].keys())
    with pytest.raises(ValidationError):
        RouterDecision.model_validate(decision(confirm=True))


def test_strict_success_preserves_public_contract(router_factory, employees):
    router, calls = router_factory(decision())
    assert isinstance(route(router, employees), AgentRoute)
    assert len(calls) == 1
    assert calls[0][0]["response_format"]["json_schema"]["name"] == "agent_route_lite"
    assert calls[0][1]["read"] <= 25
    assert router.llm.timeout.read == 120


@pytest.mark.parametrize("failure", [
    httpx.Response(400, json={"error": {"message": "response_format json_schema is not supported by this model"}}),
    httpx.Response(501, json={"error": {"message": "Structured outputs are not implemented"}}),
])
def test_compatible_failure_falls_back_once(router_factory, employees, failure):
    router, calls = router_factory(failure, decision())
    assert not route(router, employees).mutation_requested
    assert len(calls) == 2 and router.last_run.fallback_used
    assert "response_format" not in calls[1][0]
    assert calls[1][0]["temperature"] == 0
    assert calls[1][1]["read"] <= 10
    assert router.last_run.stages[1]["retry_reason"] == "schema_unsupported"
    assert router.last_run.stages[1]["attempt"] == 2


def test_invalid_fallback_fails_closed(router_factory, employees):
    router, calls = router_factory(
        httpx.Response(400, json={"error": {"message": "strict response_format is unsupported"}}),
        {},
    )
    with pytest.raises(AIUnavailableError):
        route(router, employees, "生成本周排班")
    assert len(calls) == 2


@pytest.mark.parametrize("status", [401, 403, 404, 429, 503])
def test_non_compatibility_errors_do_not_retry(router_factory, employees, status):
    router, calls = router_factory(httpx.Response(status, json={"error": {"message": "unavailable"}}))
    with pytest.raises(AIUnavailableError):
        route(router, employees, "生成本周排班")
    assert len(calls) == 1


def test_total_budget_bounds_a_stuck_transport(router_factory, employees, monkeypatch):
    monkeypatch.setenv("LLM_ROUTER_BUDGET_SECONDS", "0.05")
    def stall():
        time.sleep(0.15)
        return decision()
    router, calls = router_factory(stall)
    started = time.monotonic()
    with pytest.raises(AIUnavailableError):
        route(router, employees, "生成本周排班")
    assert time.monotonic() - started < 0.12
    assert len(calls) == 1
    time.sleep(0.16)  # Let only the isolated provider worker finish before fixture cleanup.


@pytest.mark.parametrize("text", ["E17这周能不能排进去？", "不要强制生成，看看有没有别的办法", "我只是问能不能强制生成", "别违反规则", "周日为什么安排了7个人？"])
def test_aggressive_provider_cannot_turn_a_question_into_a_write(router_factory, employees, text):
    router, calls = router_factory(decision(intent="generate", mutation_requested=True, force_or_override_intent=True))
    result = route(router, employees, text)
    assert not result.mutation_requested and not result.force_generate
    assert result.operations == result.forced_assignments == result.requested_overrides == []
    assert len(calls) == 1


@pytest.mark.parametrize("identifier", ["E01", "e01", "Ｅ０１"])
def test_ids_and_multi_day_mutation(router_factory, employees, identifier):
    ops = [operation(day="Mon"), operation(day="Tue"), operation("E02", "Wed", type="preference", shift="evening")]
    router, calls = router_factory(decision(intent="replan", mutation_requested=True),
        {"operations": ops, "minimize_changes": False, "clarification": None})
    text = f"{identifier} 周一周二请假，E02 周三晚班优先，帮我重新排一下"
    result = route(router, employees, text)
    assert result.mutation_requested
    assert [o.model_dump(mode="json") for o in result.operations] == ops
    assert len(result.changes) == 3
    assert text in calls[1][0]["messages"][1]["content"]
    assert len(calls) == 2


@pytest.mark.parametrize("failure,expected", [
    (httpx.ReadTimeout("slow"), "read_timeout"),
    (httpx.ConnectTimeout("slow connect"), "connect_timeout"),
    (httpx.ConnectError("connection refused"), "connection_error"),
    ({"bogus": True}, "structured_output_error"),
    (httpx.Response(200, text="invalid json"), "invalid_provider_response"),
    (httpx.Response(400, json={"error": {"message": "Invalid response_format schema: missing properties"}}), "invalid_request"),
])
def test_transport_and_invalid_output_never_trigger_schema_retry(
    router_factory, employees, failure, expected
):
    router, calls = router_factory(failure, decision())
    with pytest.raises(AIUnavailableError) as error:
        route(router, employees, "生成本周排班")
    assert error.value.error_type == expected
    assert len(calls) == 1
    assert not router.last_run.fallback_used
    assert router.last_run.stages[0]["error_type"] == expected
    assert router.last_run.stages[0]["provider_request_count"] == 1


def test_provider_operation_order_is_canonicalized_to_current_message(router_factory, employees):
    expected = [operation(day="Mon"), operation(day="Tue"), operation("E02", "Wed", type="preference", shift="evening")]
    router, _ = router_factory(
        decision(intent="replan", mutation_requested=True),
        {"operations": [expected[2], expected[1], expected[0]], "minimize_changes": False, "clarification": None},
    )
    result = route(router, employees, "E01 周一周二请假，E02 周三晚班优先，帮我重新排一下")
    assert [(item.employee_id, item.type.value, item.day.value if item.day else None, item.shift.value if item.shift else None) for item in result.operations] == [
        ("E01", "leave", "Mon", None),
        ("E01", "leave", "Tue", None),
        ("E02", "preference", "Wed", "evening"),
    ]


def test_provider_cannot_replace_existing_preferences_without_set_authority(router_factory, employees):
    router, _ = router_factory(
        decision(intent="replan", mutation_requested=True),
        {"operations": [
            operation(day="Mon"),
            operation(day="Tue"),
            operation("E02", "Wed", type="preference", shift="evening", operation="set"),
        ], "minimize_changes": False, "clarification": None},
    )
    result = route(router, employees, "E01 周一周二请假，E02 周三晚班优先，帮我重新排一下")
    assert result.intent == AgentIntent.CLARIFICATION
    assert not result.mutation_requested


@pytest.mark.parametrize("returned", [
    [operation(day="Mon"), operation(day="Tue"), operation("E02", "Wed", type="preference", shift="morning")],
    [operation(day="Mon"), operation(day="Tue"), operation("E02", "Wed", type="preference", shift="evening"), operation(day="Fri")],
    [operation(day="Mon"), operation("E02", "Wed", type="preference", shift="evening")],
    [operation(day="Mon"), operation(day="Mon"), operation("E02", "Wed", type="preference", shift="evening")],
    [operation(day="Mon"), operation(day="Tue"), operation("E03", "Wed", type="preference", shift="evening")],
])
def test_grounding_rejects_missing_duplicate_or_unknown_operations(router_factory, employees, returned):
    router, _ = router_factory(
        decision(intent="replan", mutation_requested=True),
        {"operations": returned, "minimize_changes": False, "clarification": None},
    )
    result = route(router, employees, "E01 周一周二请假，E02 周三晚班优先，帮我重新排一下")
    assert result.intent == AgentIntent.CLARIFICATION
    assert not result.mutation_requested


@pytest.mark.parametrize("text,ops", [
    ("先清掉 E01 周一限制，再给 E01 周一请假", [operation(operation="clear"), operation()]),
    ("E01 周一取消请假，再给 E01 周二请假", [operation(operation="remove", type="available"), operation(day="Tue")]),
    ("E01 只请周一假，再给 E01 周二请假", [operation(operation="set"), operation(day="Tue")]),
    ("E01 周一请假，E02 周二取消请假", [operation(), operation("E02", "Tue", operation="remove", type="available")]),
])
def test_sequential_mutations_use_text_order_even_when_provider_reverses(router_factory, employees, text, ops):
    router, _ = router_factory(decision(mutation_requested=True),
        {"operations": list(reversed(ops)), "minimize_changes": False, "clarification": None})
    result = route(router, employees, text)
    assert result.mutation_requested
    assert [o.model_dump(mode="json") for o in result.operations] == ops


@pytest.mark.parametrize("text,ops", [
    ("E01、E02 周一都请假，重新排一下", [operation(), operation("E02")]),
    ("E01 和 E02 周一请假", [operation(), operation("E02")]),
    ("E01/E02 周一周二请假", [operation(), operation(day="Tue"), operation("E02"), operation("E02", "Tue")]),
    ("E01 周一、E02 周二都请假", [operation(), operation("E02", "Tue")]),
    ("E01 清掉周一限制，再加周二请假", [operation(operation="clear"), operation(day="Tue")]),
    ("E01 清掉周一限制，再加周二请假", [operation(operation="clear")]),
])
def test_unsupported_shared_clauses_fail_closed(router_factory, employees, text, ops):
    router, _ = router_factory(decision(mutation_requested=True),
        {"operations": ops, "minimize_changes": False, "clarification": None})
    result = route(router, employees, text + "，重新排一下")
    assert not result.mutation_requested
    assert result.intent == AgentIntent.CLARIFICATION


@pytest.mark.parametrize("clear_type", ["leave", "unavailable"])
def test_ordered_clear_then_add(router_factory, employees, clear_type):
    ops = [operation(day=None, operation="clear", type=clear_type), operation("E02", "Fri")]
    router, _ = router_factory(decision(intent="what_if", mutation_requested=True),
                              {"operations": ops, "minimize_changes": False, "clarification": None})
    result = route(router, employees, "先清掉 E01 的限制，再给 E02 周五请假")
    assert [o.model_dump(mode="json") for o in result.operations] == ops
    assert len(result.changes) == 1


@pytest.mark.parametrize("ops", [[], [operation("E17", "Mon", type="assign", shift="morning")]])
def test_unspecified_execution_fields_are_never_invented(router_factory, employees, ops):
    router, _ = router_factory(decision(intent="replan", mutation_requested=True, employees=["E17"]),
                              {"operations": ops, "minimize_changes": False, "clarification": None})
    result = route(router, employees, "把 E17 随便排到哪一天都行")
    assert result.intent == "clarification" and result.employees == ["E17"]
    assert not result.mutation_requested and not result.changes


def test_dropped_day_fails_closed(router_factory, employees):
    router, _ = router_factory(decision(intent="replan", mutation_requested=True),
        {"operations": [operation()], "minimize_changes": False, "clarification": None})
    assert route(router, employees, "E01 周一周二请假，重新排一下").intent == "clarification"


def test_unknown_employee_rejected_before_provider(router_factory, employees):
    router, calls = router_factory()
    with pytest.raises(UnknownAgentEmployeeError):
        route(router, employees, "E99 周一请假，重新排一下")
    assert not calls


def test_force_scope_cannot_be_invented(router_factory, employees):
    router, _ = router_factory(decision(intent="generate", mutation_requested=True, force_or_override_intent=True),
        {"requested_overrides": [{"rule_id": "R08", "employee_id": "E01", "day": "Mon", "shift": "morning", "allowed_shortage": None}],
         "forced_assignments": [], "clarification": None})
    result = route(router, employees, "就算违反规则也先给我排出来")
    assert result.intent == "clarification" and not result.force_generate


def test_fallback_budget_is_shared_across_stages(router_factory, employees):
    unsupported = httpx.Response(400, json={"error": {"message": "json_schema is not supported"}})
    router, calls = router_factory(unsupported, decision(intent="replan", mutation_requested=True), unsupported)
    with pytest.raises(AIUnavailableError):
        route(router, employees, "E01 周一请假，重新排一下")
    assert len(calls) == 3
    assert sum("response_format" not in c[0] for c in calls) == 1


def test_fast_paths_never_call_llm(router_factory, employees):
    router, calls = router_factory()
    assert not route(router, employees, "确认").mutation_requested
    assert route(router, employees, "生成", trusted_action=TrustedAgentAction(intent="generate")).mutation_requested
    router.llm.enabled = False
    assert route(router, employees, "生成本周排班").mutation_requested
    assert not calls


@pytest.mark.parametrize("text", ["你能重新排班吗？", "你会生成排班吗？", "你能强制生成吗？", "重新排班是怎么工作的？"])
def test_capability_questions_are_non_mutating(router_factory, employees, text):
    router, _ = router_factory(decision())
    result = route(router, employees, text)
    assert result.domain is AgentDomain.PRODUCT
    assert result.speech_act in {SpeechAct.CAPABILITY_QUESTION, SpeechAct.EXPLANATION_REQUEST}
    assert not result.mutation_requested
    assert not result.force_generate
    assert result.requested_overrides == []
    assert result.forced_assignments == []


@pytest.mark.parametrize("text", ["帮我生成本周排班", "请重新排一下", "E01 周一请假，帮我重新排一下", "能不能帮我重新排一下？"])
def test_action_requests_remain_actions(router_factory, employees, text):
    router, _ = router_factory(decision(), {"operations": [operation()] if "E01" in text else [], "minimize_changes": False, "clarification": None})
    result = route(router, employees, text)
    assert result.domain is AgentDomain.SCHEDULING
    assert result.mutation_requested


@pytest.mark.parametrize("text", ["确认生效是干嘛的？", "为什么要有草稿？", "员工视图和日期视图有什么区别？", "检测 AI 是做什么的？", "你好", "谢谢"])
def test_product_and_smalltalk_domains(router_factory, employees, text):
    router, _ = router_factory(decision())
    result = route(router, employees, text)
    assert result.domain in {AgentDomain.PRODUCT, AgentDomain.SMALLTALK}
    assert not result.mutation_requested


def test_current_read_never_inherits_suggestion(router_factory, employees):
    router, _ = router_factory(decision(intent="explain", question_type="general_question"))
    result = router.route("周日为什么安排了7个人？", employees=employees,
        recent_messages=[{"role": "assistant", "content": "恢复 E01 Mon 可用", "suggestions": [{"id": "suggestion_1"}]}])
    assert result.reference.type == "none"
    assert result.read_query.question_type == "staffing_explanation"
    assert result.read_query.day == "Sun"
    assert not result.mutation_requested


def test_bare_iso_week_is_resolved_deterministically():
    from datetime import date
    from backend.app.services.agent_context import WeekResolver, WeekResolutionError
    resolved = WeekResolver().resolve(content="41周", route=AgentRoute(intent="ask"),
        current_week_start=date(2026, 9, 28), recent_messages=[])
    assert resolved.week_start == date(2026, 10, 5)
    with pytest.raises(WeekResolutionError):
        WeekResolver().resolve(content="2026年第99周", route=AgentRoute(intent="ask"),
            current_week_start=date(2026, 9, 28), recent_messages=[])


def test_probe_uses_real_router_contract_without_an_execution_service(router_factory, employees):
    router, calls = router_factory(decision(intent="replan", mutation_requested=True, employees=["E17"]),
        {"operations": [], "minimize_changes": False, "clarification": "请指定日期和班次。"})
    probe = router.probe(employees=employees)
    assert probe["status"] == "ok" and probe["intent"] == "clarification"
    assert probe["mutation_requested"] is False
    assert probe["schema_bytes"] == schema_bytes(lite_router_json_schema())
    assert not probe["fallback_used"] and len(calls) == 2


def test_probe_cannot_report_deterministic_fallback_as_provider_success(router_factory, employees):
    router, _ = router_factory(httpx.Response(401, json={"error": {"message": "invalid key"}}))
    probe = router.probe(employees=employees)
    assert probe["status"] == "error" and probe["error_type"] == "authentication_error"


def test_read_advice_preserves_hypothetical_changes(router_factory, employees):
    router, _ = router_factory(decision(intent="advice"))
    result = route(router, employees, "E01 周一请假会有什么影响，给我建议。")
    assert result.intent == "advice" and not result.mutation_requested
    assert [(c.employee_id, c.day.value, c.type.value) for c in result.changes] == [("E01", "Mon", "leave")]
    assert not result.operations


def test_combined_ai_health_is_degraded_when_only_router_fails(monkeypatch):
    from fastapi import Response
    from backend.app import main
    monkeypatch.setattr(main.agent_llm_client, "health_check", lambda: {
        "status": "ok", "checks": {"basic_chat": {"status": "ok"}, "structured_output": {"status": "ok"}}})
    monkeypatch.setattr(main.employee_repository, "list", lambda: [])
    monkeypatch.setattr(main.AgentRouter, "probe", lambda self, **kw: {"status": "error", "error_type": "read_timeout"})
    response = Response()
    result = main.llm_health(response)
    assert response.status_code == 503 and result["status"] == "degraded"
    assert result["checks"]["agent_router"]["error_type"] == "read_timeout"


def test_basic_health_never_calls_router(monkeypatch):
    from fastapi import Response
    from backend.app import main
    monkeypatch.setattr(main.database, "is_healthy", lambda: True)
    def unexpected(*args, **kwargs):
        raise AssertionError("liveness must not call Provider")
    monkeypatch.setattr(main.AgentRouter, "probe", unexpected)
    assert main.health(Response())["status"] == "ok"
