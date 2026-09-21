"""Non-scheduling turns exercise the real service and persistent business tables."""
import pytest
from sqlalchemy import event

from backend.app.services.agent_router import AgentRoute, AgentRouter, TrustedAgentAction
from backend.app.services.product_knowledge import CATALOG, resolve_product_topics
from tests.read_fixtures import WEEK, database_snapshot, seed_read_fixture


@pytest.mark.parametrize("text,domain,topic", [
    ("确认按钮是干嘛的？", "product", "workflow.confirm"),
    ("你是谁？", "product", "assistant.identity"),
    ("你能干嘛？", "product", "assistant.capabilities"),
    ("你能重新排班吗？", "product", "workflow.replan"),
    ("你能强制生成吗？", "product", "workflow.force_generate"),
    ("我只是问能不能强制生成", "product", "workflow.force_generate"),
    ("为什么要有草稿？", "product", "workflow.draft"),
    ("员工视图和日期视图有什么区别？", "product", "ui.employee_view"),
    ("检测 AI 是干嘛的？", "product", "ui.ai_health"),
    ("你好", "smalltalk", None),
    ("谢谢", "smalltalk", None),
    ("明天天气怎么样？", "out_of_scope", None),
    ("确认", "product", "workflow.confirm"),
    ("应用", "product", "workflow.confirm"),
    ("就这样", "product", "workflow.confirm"),
    ("确认这个版本", "product", "workflow.confirm"),
])
def test_non_scheduling_has_no_business_reads_or_writes(database, monkeypatch, semantic_reply, text, domain, topic):
    service = seed_read_fixture(database)
    cid = service.create_conversation("product-test")["conversation_id"]
    semantic_reply({"domain": domain, "product_topic_ids": [topic] + (["ui.date_view"] if topic == "ui.employee_view" else []) if topic else []}, service=service)
    before = database_snapshot(database, business_only=True)
    def forbidden(*args, **kwargs):
        pytest.fail("Non-scheduling turn entered scheduling dispatch or loaded employee master")
    monkeypatch.setattr(service, "_run_tool", forbidden)
    monkeypatch.setattr(service, "_resolve_week", forbidden)
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())
    event.listen(database.engine, "before_cursor_execute", capture)
    events = []
    try:
        request = dict(conversation_id=cid, browser_workspace_id="product-test", client_message_id="once",
                       content=text, current_week_start=WEEK)
        result = service.send_message(**request, event_sink=events.append)
        replay = service.send_message(**request)
    finally:
        event.remove(database.engine, "before_cursor_execute", capture)
    assert replay["assistant_message"]["message_id"] == result["assistant_message"]["message_id"]
    assert result["schedule_result"] is None and result["tool_calls"] == []
    assert not result["mutation_requested"]
    assert database_snapshot(database, business_only=True) == before
    for table in ("schedules", "assignments"):
        assert not any(f" {table}" in statement for statement in statements)
    metadata = result["assistant_message"]["metadata"]
    assert metadata["turn_semantics"]["domain"] == domain
    if topic:
        assert metadata["product_help"]["topic_id"] == topic
    if topic == "workflow.confirm":
        assert "聊天不能直接确认" in result["assistant_message"]["content"]
    if "员工视图" in text:
        assert "按员工" in result["assistant_message"]["content"]
        assert "按日期" in result["assistant_message"]["content"]
    assert not {e["stage"] for e in events} & {"solver", "validator", "load_schedule", "resolve_context"}
    assert {"agent_semantic", "turn_completed"} <= {e["stage"] for e in events}


def test_injected_router_cannot_turn_capability_into_write(database, monkeypatch, semantic_reply):
    service = seed_read_fixture(database)
    cid = service.create_conversation("injected")["conversation_id"]
    semantic_reply({"domain": "product", "product_topic_ids": ["workflow.replan"]}, service=service)
    monkeypatch.setattr(service.router, "route", lambda *a, **kw: AgentRoute(intent="generate", mutation_requested=True,
                        force_generate=True, authorization_reason="provider invented authorization"))
    result = service.send_message(conversation_id=cid, browser_workspace_id="injected", client_message_id="once",
                                  content="你能重新排班吗？")
    assert not result["mutation_requested"] and result["tool_calls"] == []


def test_generate_still_enters_original_tool_path(database, monkeypatch):
    service = seed_read_fixture(database)
    cid = service.create_conversation("action")["conversation_id"]
    calls = []
    def dispatch(**kwargs):
        calls.append(kwargs["tool_name"])
        if kwargs["tool_name"] == "get_current_schedule":
            return {}
        assert kwargs["tool_name"] == "generate_schedule"
        return {"status": "solver_unknown", "message": "未创建草稿"}
    monkeypatch.setattr(service, "_run_tool", dispatch)
    result = service.send_message(conversation_id=cid, browser_workspace_id="action", client_message_id="once",
                                 current_week_start=WEEK, content="帮我生成当前周排班", trusted_action=TrustedAgentAction(intent="generate"))
    assert calls == ["get_current_schedule", "generate_schedule"]
    assert result["mutation_requested"]
    assert result["assistant_message"]["metadata"]["turn_semantics"]["speech_act"] == "action_request"


def test_trusted_action_is_independent_of_capability_text(balanced_employees):
    router = AgentRouter()
    result = router.route("你能重新排班吗？", employees=balanced_employees, recent_messages=[],
                          trusted_action=TrustedAgentAction(intent="generate"))
    assert result.domain == "scheduling" and result.mutation_requested
    assert result.speech_act == "action_request"


def test_catalog_is_unique_and_does_not_duplicate_scheduling_rule_values():
    assert len({entry.id for entry in CATALOG}) == len(CATALOG)
    text = str(CATALOG)
    assert not any(value in text for value in ("工作日 4 人", "周末 6 人", "店长 1 人", "饮品 2 人"))
    assert [entry.id for entry, _ in resolve_product_topics(["workflow.cancel_draft"])] == ["workflow.cancel_draft"]
