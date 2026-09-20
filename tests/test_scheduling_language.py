"""Execute public Agent API against real SQLite, CP-SAT and Validator."""
import pytest

from backend.app.models.dialogue import DialogueState, PendingAction
from backend.app.services.draft_request import is_explicit_draft_request
from backend.app.services.intent_parser import IntentParser
from backend.app.services.dialogue_parser import deterministic_command
from tests.evals.scheduling_language import MULTITURN, NEGATIVE, POSITIVE
from tests.test_agent import WEEK_40, _conversation, _generate_and_confirm
from tests.test_dialogue_state import (
    _assert_execution_source, _assert_no_draft, _keys, _turn,
    agent_client,
)


@pytest.fixture
def solver_calls(agent_client, monkeypatch):
    from backend.app.api.dependencies import scheduling_service

    calls = []
    solve = scheduling_service.solver.solve

    def observed(context, **kwargs):
        calls.append(context.model_dump(mode="json"))
        return solve(context, **kwargs)

    # Observe the live instance: earlier timeout tests can restore a bound
    # method on this instance, which would bypass a class-level spy.
    monkeypatch.setattr(scheduling_service.solver, "solve", observed)
    return calls


@pytest.mark.parametrize("text", POSITIVE)
def test_deterministic_imperatives(text):
    command = deterministic_command(text, DialogueState(), [])
    assert command is not None
    assert command.execution == "create_draft"
    assert len(command.edits) == 1
    edit = command.edits[0]
    assert edit.employee_ids == ["E02"]
    assert edit.days == ["Mon"] and edit.shift == "morning" and edit.type == "assign"


def assert_draft(client, conversation, payload, shift="morning"):
    result = _assert_execution_source(payload, conversation, "execute", {("E02", "Mon", "assign", shift)})
    context = client.get("/api/schedules/week-context", params={"week_start": WEEK_40}).json()
    assert context["draft_schedule"]["schedule_id"] == result["schedule_id"]
    assert context["draft_schedule"]["status"] == "draft"
    assert any(t["tool_name"] in {"generate_schedule", "replan_schedule"} for t in payload["tool_calls"])
    return result


@pytest.mark.parametrize("text", POSITIVE)
def test_imperative_creates_persisted_draft(agent_client, solver_calls, text):
    conversation = _conversation(agent_client)
    payload, state = _turn(agent_client, conversation, text, "execute")
    assert_draft(agent_client, conversation, payload)
    assert len(solver_calls) == 1
    assert not state["pending"]


@pytest.mark.parametrize("text", NEGATIVE)
def test_read_only_never_creates_draft(agent_client, text):
    conversation = _conversation(agent_client)
    payload, _ = _turn(agent_client, conversation, text, "read")
    assert not (payload.get("schedule_result") or {}).get("schedule_id")
    assert not any(t["tool_name"] in {"generate_schedule", "replan_schedule"} for t in payload["tool_calls"])
    _assert_no_draft(agent_client)


@pytest.mark.parametrize("turns,shift", MULTITURN)
def test_slot_completion_executes_once(agent_client, solver_calls, turns, shift):
    conversation = _conversation(agent_client)
    for i, text in enumerate(turns[:-1]):
        payload, state = _turn(agent_client, conversation, text, str(i))
        assert not (payload.get("schedule_result") or {}).get("schedule_id")
        if state["pending"]:
            assert state["pending"][0]["execution_on_complete"] == "create_draft"
    payload, state = _turn(agent_client, conversation, turns[-1], "execute")
    assert not state["pending"]
    first = assert_draft(agent_client, conversation, payload, shift)
    replay, _ = _turn(agent_client, conversation, turns[-1], "execute")
    assert replay["schedule_result"]["schedule_id"] == first["schedule_id"]
    assert len(solver_calls) == 1


@pytest.mark.parametrize("suppress", ["不过先别生成", "先分析", "先看看", "暂时别排", "只记下来", "先不排了"])
def test_suppress_clears_pending_continuation(agent_client, suppress):
    conversation = _conversation(agent_client)
    _turn(agent_client, conversation, "帮我把E02排进去", "1")
    _, state = _turn(agent_client, conversation, "周一，" + suppress, "2")
    assert state["pending"][0]["days"] == ["Mon"]
    assert state["pending"][0]["execution_on_complete"] == "none"
    payload, state = _turn(agent_client, conversation, "早班", "3")
    assert not (payload.get("schedule_result") or {}).get("schedule_id")
    assert _keys(state) == {("E02", "Mon", "assign", "morning")}
    _assert_no_draft(agent_client)
    payload, _ = _turn(agent_client, conversation, "现在按这个排", "execute")
    assert_draft(agent_client, conversation, payload)


def test_hypothetical_pending_stays_proposal(agent_client):
    conversation = _conversation(agent_client)
    for i, text in enumerate(["如果让E02这周上班会怎样", "周一", "早班"]):
        payload, state = _turn(agent_client, conversation, text, str(i))
        assert not (payload.get("schedule_result") or {}).get("schedule_id")
        assert not state["conditions"]
    assert _keys(state, "proposals") == {("E02", "Mon", "assign", "morning")}
    _assert_no_draft(agent_client)


def test_cancel_pending_cannot_resume(agent_client):
    conversation = _conversation(agent_client)
    for i, text in enumerate(["帮我把E02排进去", "周一", "取消刚才那个", "早班"]):
        payload, state = _turn(agent_client, conversation, text, str(i))
        assert not (payload.get("schedule_result") or {}).get("schedule_id")
    assert not state["pending"] and not state["conditions"]
    _assert_no_draft(agent_client)


def test_multiple_pending_requires_explicit_employee(agent_client):
    conversation = _conversation(agent_client)
    _turn(agent_client, conversation, "给E02排个班，给E03排个班", "1")
    payload, state = _turn(agent_client, conversation, "周一", "2")
    assert len(state["pending"]) == 2
    assert all(not p["days"] for p in state["pending"])
    assert "多个待补" in payload["assistant_message"]["content"]
    _assert_no_draft(agent_client)


def test_replan_preserves_confirmed_version(agent_client):
    confirmed = _generate_and_confirm(agent_client)
    conversation = _conversation(agent_client)
    payload, _ = _turn(agent_client, conversation, "E02周一早班安排上班", "execute")
    result = assert_draft(agent_client, conversation, payload)
    context = agent_client.get("/api/schedules/week-context", params={"week_start": WEEK_40}).json()
    assert context["confirmed_schedule"]["schedule_id"] == confirmed["schedule_id"]
    assert context["confirmed_schedule"]["version"] == confirmed["version"]
    assert agent_client.post("/api/schedule/cancel", json={"schedule_id": result["schedule_id"], "version": result["version"]}).status_code == 200


@pytest.mark.parametrize("text", [
    "如果帮我生成E02周一早班会怎么样", "能不能让E02周一上早班",
    "不要让E02周一早班上班", "我只是问一下E02周一早班可不可以",
    "帮我看看是否把E02放到周一早班", "先别生成，把E02周一早班安排上",
    "E02周一早班上班", "安排一下会议", "把图片放到文件夹",
])
def test_execution_veto_and_domain(text):
    assert not is_explicit_draft_request(text)


@pytest.mark.parametrize("day,expected", list(zip("一二三四五六日天", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Sun"])))
def test_colloquial_weekdays(day, expected):
    assert IntentParser.extract_days("礼拜" + day) == [expected]


def test_legacy_pending_defaults_to_no_authority():
    assert PendingAction(source_message_id="old").execution_on_complete == "none"


def test_ambiguous_suppression_is_persisted(agent_client):
    conversation = _conversation(agent_client)
    _turn(agent_client, conversation, "给E02排个班，给E03排个班", "1")
    _, state = _turn(agent_client, conversation, "周一，但先别生成", "2")
    assert len(state["pending"]) == 2
    assert all(p["execution_on_complete"] == "none" and not p["days"] for p in state["pending"])


def test_cancel_continuation_without_slot(agent_client):
    conversation = _conversation(agent_client)
    for i, text in enumerate(["我想让E02上班", "周一", "先不排了", "早班"]):
        payload, state = _turn(agent_client, conversation, text, str(i))
        assert not (payload.get("schedule_result") or {}).get("schedule_id")
    assert not state["pending"]
    _assert_no_draft(agent_client)
