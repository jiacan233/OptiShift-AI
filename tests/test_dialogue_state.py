"""Multi-turn behavior through the public HTTP API and persisted state.

These are offline behavioral regressions, not evidence of a real Provider run.
Fault injection is restricted to fencing and interrupted-response boundaries.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.app.database import Database, utc_now
from backend.app.models.orm import ConversationRecord
from backend.app.repository.dialogue import DialogueRepository
from backend.app.solver import PrimarySolver
from tests.test_agent import WEEK_40, WORKSPACE, _conversation, _generate_and_confirm, _send
from tests.test_agent import agent_client as dialogue_api_client

agent_client = dialogue_api_client


def _state(client, conversation, week=WEEK_40):
    response = client.get(
        f"/api/agent/conversations/{conversation}/scenario",
        params={"browser_workspace_id": WORKSPACE, "week_start": week},
    )
    assert response.status_code == 200, response.text
    return response.json()["dialogue_state"]


def _turn(client, conversation, content, turn_id, *, week=WEEK_40):
    response = _send(
        client,
        conversation,
        content,
        client_message_id=turn_id,
        current_week_start=week,
    )
    assert response.status_code == 200, f"{turn_id}: {content}\n{response.text}"
    return response.json(), _state(client, conversation, week)


def _keys(state, field="conditions"):
    return {
        (change["employee_id"], change["day"], change["type"], change.get("shift"))
        for item in state[field]
        for change in item["changes"]
    }


def _assert_no_draft(client, week=WEEK_40):
    response = client.get("/api/schedules/week-context", params={"week_start": week})
    assert response.status_code == 200, response.text
    assert response.json()["draft_schedule"] is None


@pytest.fixture
def solver_calls(monkeypatch):
    calls = []
    solve = PrimarySolver.solve

    def observed(self, context, **kwargs):
        calls.append(context.model_dump(mode="json"))
        return solve(self, context, **kwargs)

    monkeypatch.setattr(PrimarySolver, "solve", observed)
    return calls


def _assert_execution_source(payload, conversation, client_id, expected):
    from backend.app.api.dependencies import schedule_repository

    result = payload["schedule_result"]
    assert result and result["status"] == "feasible", payload
    record = schedule_repository.get_record(result["schedule_id"])
    metadata = record["metadata"]
    assert metadata["agent_conversation_id"] == conversation
    assert metadata["agent_client_message_id"] == client_id
    assert metadata["agent_user_message_id"]
    assert metadata["condition_hash"]
    assert {
        (c["employee_id"], c["day"], c["type"], c.get("shift"))
        for c in metadata["requested_changes"]
    } == expected
    assert {
        (c["employee_id"], c["day"], c["type"], c.get("shift"))
        for item in metadata["condition_snapshot"]
        for c in item["changes"]
    } == expected
    return result


def test_case_b_slot_filling_recovers_from_database_and_records_without_solving(
    agent_client,
    solver_calls,
):
    from backend.app.api.dependencies import conversation_repository

    conversation = _conversation(agent_client)
    _, state = _turn(agent_client, conversation, "我想调一个人的排班。", "b1")
    assert len(state["pending"]) == 1
    pending_id = state["pending"][0]["id"]
    _, state = _turn(agent_client, conversation, "E18。", "b2")
    assert state["pending"][0]["id"] == pending_id
    assert state["pending"][0]["employee_id"] == "E18"
    _, state = _turn(agent_client, conversation, "想让他上班，先别生成。", "b3")
    assert state["pending"][0]["type"] == "assign"
    assert state["pending"][0]["days"] == []

    # New database and repository instances must recover slots independently of chat text.
    restarted_database = Database(conversation_repository.database.url)
    try:
        recovered = DialogueRepository(restarted_database).get(
            conversation, date.fromisoformat(WEEK_40)
        )
        assert recovered.pending[0].id == pending_id
        assert recovered.pending[0].employee_id == "E18"
        assert recovered.pending[0].type.value == "assign"
    finally:
        restarted_database.dispose()
    restored = agent_client.get(
        f"/api/agent/conversations/{conversation}",
        params={"browser_workspace_id": WORKSPACE},
    )
    assert restored.status_code == 200
    _, state = _turn(agent_client, conversation, "有哪些排班规则？", "b-interruption")
    assert state["pending"][0]["id"] == pending_id
    _, state = _turn(agent_client, conversation, "周四。", "b4")
    assert state["pending"][0]["days"] == ["Thu"]
    _, state = _turn(agent_client, conversation, "晚班。", "b5")
    assert state["pending"] == []
    assert _keys(state) == {("E18", "Thu", "assign", "evening")}
    _turn(agent_client, conversation, "不过先别生成，你告诉我现在理解我要干嘛。", "b6")
    _, state = _turn(agent_client, conversation, "再加一个条件，E06周五请假。", "b7")
    expected = {("E18", "Thu", "assign", "evening"), ("E06", "Fri", "leave", None)}
    assert _keys(state) == expected
    assert solver_calls == []
    _assert_no_draft(agent_client)
    payload, state = _turn(agent_client, conversation, "好，就按这两个要求重新排班。", "b8")
    _assert_execution_source(payload, conversation, "b8", expected)
    assert state["last_draft"]["scenario_revision"] == state["scenario_revision"]


def test_explicit_pending_cancel_does_not_revive_on_later_slot(agent_client, solver_calls):
    conversation = _conversation(agent_client)
    _turn(agent_client, conversation, "我想调一个人的排班。", "cancel1")
    _, state = _turn(agent_client, conversation, "E18。", "cancel2")
    pending_id = state["pending"][0]["id"]
    _, state = _turn(agent_client, conversation, "取消这个待补动作。", "cancel3")
    assert state["pending"] == []
    assert pending_id in state["tombstones"]
    _, state = _turn(agent_client, conversation, "晚班。", "cancel4")
    assert state["pending"] == []
    assert state["conditions"] == []
    assert solver_calls == []


def test_case_g_date_correction_preserves_identity_and_removes_only_old_day(
    agent_client,
    solver_calls,
):
    conversation = _conversation(agent_client)
    _, state = _turn(agent_client, conversation, "我想让E19周六晚班优先。", "g1")
    original_id = state["conditions"][0]["id"]
    _turn(agent_client, conversation, "你先告诉我你理解的具体条件是什么。", "g2")
    _, state = _turn(agent_client, conversation, "等等，我说错了，不是周六，是周日。", "g3")
    assert _keys(state) == {("E19", "Sun", "preference", "evening")}
    assert state["conditions"][0]["id"] == original_id
    _turn(agent_client, conversation, "班次还是晚班。", "g4")
    _turn(agent_client, conversation, "另外E15周六请假。", "g5")
    _turn(agent_client, conversation, "你现在把两个最终条件再说一遍。", "g6")
    _, state = _turn(
        agent_client, conversation, "确认一下，E19周六那个旧条件已经不存在了，对吧？", "g7"
    )
    expected = {("E19", "Sun", "preference", "evening"), ("E15", "Sat", "leave", None)}
    assert _keys(state) == expected
    assert solver_calls == []
    payload, _ = _turn(agent_client, conversation, "好，按最终条件重新排。", "g8")
    _assert_execution_source(payload, conversation, "g8", expected)


def test_exact_correction_keeps_same_employee_other_date_and_ambiguous_remove_is_atomic(
    agent_client,
):
    conversation = _conversation(agent_client)
    _, state = _turn(agent_client, conversation, "E19周四早班优先。", "precision1")
    thursday_id = state["conditions"][0]["id"]
    _turn(agent_client, conversation, "E19周六晚班优先。", "precision2")
    _, state = _turn(agent_client, conversation, "不是周六，是周日。", "precision3")
    expected = {("E19", "Thu", "preference", "morning"), ("E19", "Sun", "preference", "evening")}
    assert _keys(state) == expected
    assert (
        next(c for c in state["conditions"] if c["id"] == thursday_id)["changes"][0]["day"] == "Thu"
    )
    revision = state["scenario_revision"]
    _, state = _turn(agent_client, conversation, "取消E19的限制。", "precision4")
    assert _keys(state) == expected
    assert state["scenario_revision"] == revision
    _, state = _turn(agent_client, conversation, "取消E19周日限制。", "precision5")
    assert _keys(state) == {("E19", "Thu", "preference", "morning")}
    _, state = _turn(agent_client, conversation, "不是周日，是周六。", "precision6")
    assert _keys(state) == {("E19", "Thu", "preference", "morning")}


def test_case_e_pronoun_conflict_and_atomic_resolution(agent_client):
    conversation = _conversation(agent_client)
    _turn(agent_client, conversation, "我要调一下E18。", "e1")
    _turn(agent_client, conversation, "E18周二请假。", "e2")
    _, state = _turn(agent_client, conversation, "同时我又想让他周二晚班上。", "e3")
    assert _keys(state) == {("E18", "Tue", "leave", None), ("E18", "Tue", "assign", "evening")}
    assert any(item["code"] == "availability_conflict" for item in state["conflicts"])
    _turn(agent_client, conversation, "先别改，你告诉我哪里冲突。", "e4")
    _, state = _turn(agent_client, conversation, "那取消周二请假，保留E18周二晚班上班。", "e5")
    assert _keys(state) == {("E18", "Tue", "assign", "evening")}
    assert state["conflicts"] == []
    _turn(agent_client, conversation, "再加E11周四晚班优先。", "e6")
    _, state = _turn(
        agent_client,
        conversation,
        "你现在检查一下还有没有互相冲突的条件，并把最终条件复述一遍。",
        "e7",
    )
    expected = {("E18", "Tue", "assign", "evening"), ("E11", "Thu", "preference", "evening")}
    assert _keys(state) == expected
    assert state["conflicts"] == []
    payload, _ = _turn(agent_client, conversation, "没有问题的话就重新排班。", "e8")
    _assert_execution_source(payload, conversation, "e8", expected)


def test_case_j_hypothesis_explicit_adoption_restore_and_precise_withdrawal(agent_client):
    conversation = _conversation(agent_client)
    _turn(agent_client, conversation, "先帮我分析E03本周工作量。", "j1")
    _, state = _turn(agent_client, conversation, "如果E03周五请假会怎样？", "j2")
    assert _keys(state) == set()
    assert _keys(state, "proposals") == {("E03", "Fri", "leave", None)}
    assert state["scenario_revision"] == 0
    proposal_id = state["proposals"][0]["id"]
    _turn(agent_client, conversation, "再加一个条件，E18周五晚班优先。", "j3")
    _, state = _turn(agent_client, conversation, "先不要生成，你把这两个条件记住。", "j4")
    assert _keys(state) == {("E03", "Fri", "leave", None), ("E18", "Fri", "preference", "evening")}
    assert state["proposals"] == []
    assert proposal_id in {item["id"] for item in state["conditions"]}
    restored = agent_client.get(
        f"/api/agent/conversations/{conversation}",
        params={"browser_workspace_id": WORKSPACE},
    )
    assert restored.status_code == 200
    _, after_refresh = _turn(agent_client, conversation, "我刚才准备改哪两个条件？", "j6")
    assert _keys(after_refresh) == _keys(state)
    _turn(agent_client, conversation, "其中E03那个不要了。", "j7")
    _, state = _turn(
        agent_client, conversation, "改成E06周三早班优先。你现在最终理解的两个条件是什么？", "j8"
    )
    expected = {("E18", "Fri", "preference", "evening"), ("E06", "Wed", "preference", "morning")}
    assert _keys(state) == expected
    assert proposal_id in state["tombstones"]
    payload, _ = _turn(agent_client, conversation, "按现在这两个条件重新排。", "j9")
    _assert_execution_source(payload, conversation, "j9", expected)


def test_case_m_combines_proposal_pronoun_and_new_condition_at_execution(agent_client):
    _generate_and_confirm(agent_client)
    conversation = _conversation(agent_client)
    _turn(agent_client, conversation, "先查E02本周目前怎么排。", "m1")
    _, state = _turn(
        agent_client, conversation, "如果让E02周二晚班上，会有什么影响？先分析。", "m2"
    )
    assert _keys(state) == set()
    assert _keys(state, "proposals") == {("E02", "Tue", "assign", "evening")}
    _turn(agent_client, conversation, "我还希望他周五晚班优先。", "m3")
    for turn_id, text in (
        ("m4", "先别生成，检查这样一周工作量会不会太高。"),
        ("m5", "再检查连续工作天数。"),
        ("m6", "再检查晚班后第二天早班。"),
        ("m7", "你现在把E02相关的两个条件分别复述一次。"),
    ):
        _, state = _turn(agent_client, conversation, text, turn_id)
        assert _keys(state) | _keys(state, "proposals") == {
            ("E02", "Tue", "assign", "evening"),
            ("E02", "Fri", "preference", "evening"),
        }
    _assert_no_draft(agent_client)
    payload, state = _turn(
        agent_client, conversation, "另外加E20周三请假，然后按这三个条件重新排。", "m8"
    )
    expected = {
        ("E02", "Tue", "assign", "evening"),
        ("E02", "Fri", "preference", "evening"),
        ("E20", "Wed", "leave", None),
    }
    assert _keys(state) == expected
    assert state["proposals"] == []
    _assert_execution_source(payload, conversation, "m8", expected)


def test_duplicate_message_records_and_executes_only_once(agent_client, solver_calls):
    conversation = _conversation(agent_client)
    first, state = _turn(agent_client, conversation, "E18周四晚班优先，先别生成。", "once-record")
    repeated, replay_state = _turn(
        agent_client, conversation, "E18周四晚班优先，先别生成。", "once-record"
    )
    assert replay_state == state
    assert repeated["assistant_message"]["message_id"] == first["assistant_message"]["message_id"]
    assert solver_calls == []
    first, state = _turn(agent_client, conversation, "按当前条件重新排班。", "once-execute")
    count = len(solver_calls)
    repeated, replay_state = _turn(
        agent_client, conversation, "按当前条件重新排班。", "once-execute"
    )
    assert repeated["schedule_result"]["schedule_id"] == first["schedule_result"]["schedule_id"]
    assert replay_state == state
    assert len(solver_calls) == count == 1


def test_old_draft_blocks_execution_but_keeps_new_conditions_for_retry(agent_client):
    draft_response = agent_client.post(
        "/api/schedule/generate",
        json={"week_start": WEEK_40, "prompt": "生成测试排班"},
    )
    assert draft_response.status_code == 200, draft_response.text
    old = draft_response.json()
    conversation = _conversation(agent_client)
    _, recorded = _turn(agent_client, conversation, "E18周四晚班优先，先别生成。", "old1")
    blocked_response = _send(
        agent_client, conversation, "按这个条件重新排班。", client_message_id="old2"
    )
    assert blocked_response.status_code == 409, blocked_response.text
    payload = blocked_response.json()
    blocked = _state(agent_client, conversation)
    assert payload["error"]["code"] == "draft_pending"
    assert payload["error"]["details"]["schedule_result"]["existing_draft_id"] == old["schedule_id"]
    assert _keys(blocked) == _keys(recorded) == {("E18", "Thu", "preference", "evening")}
    cancelled = agent_client.post(
        "/api/schedule/cancel",
        json={"schedule_id": old["schedule_id"], "version": old["version"]},
    )
    assert cancelled.status_code == 200, cancelled.text
    payload, _ = _turn(agent_client, conversation, "按当前条件重新排班。", "old3")
    result = _assert_execution_source(payload, conversation, "old3", _keys(recorded))
    assert result["schedule_id"] != old["schedule_id"]


@pytest.mark.parametrize(
    "fault,expected_error",
    [
        ("revision", "suggestion_stale"),
        ("lease", "message_processing"),
    ],
)
def test_stale_state_commit_is_rejected_without_partial_condition_write(
    agent_client,
    monkeypatch,
    fault,
    expected_error,
):
    conversation = _conversation(agent_client)
    _, before = _turn(agent_client, conversation, "E18周四晚班优先。", "fence1")
    commit = DialogueRepository.commit

    def stale_commit(self, *args, **kwargs):
        if fault == "revision":
            kwargs["expected_revision"] += 1
        else:
            kwargs["owner_token"] = "obsolete-worker-token"
        return commit(self, *args, **kwargs)

    monkeypatch.setattr(DialogueRepository, "commit", stale_commit)
    response = _send(agent_client, conversation, "E06周五请假。", client_message_id="fence2")
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == expected_error
    after = _state(agent_client, conversation)
    assert after == before


def test_result_writeback_rejects_lost_lease_and_retains_proposal(agent_client, monkeypatch):
    conversation = _conversation(agent_client)
    commit = DialogueRepository.commit

    def lose_lease_after_computation(self, *args, **kwargs):
        if kwargs.get("result") is not None:
            with self.database.transaction(immediate=True) as session:
                record = session.get(ConversationRecord, conversation)
                record.active_turn_owner_token = "replacement-worker"
        return commit(self, *args, **kwargs)

    monkeypatch.setattr(DialogueRepository, "commit", lose_lease_after_computation)
    response = _send(
        agent_client,
        conversation,
        "如果E03周五请假会怎样？",
        client_message_id="preview-lease",
    )
    assert response.status_code == 409, response.text
    state = _state(agent_client, conversation)
    assert _keys(state) == set()
    assert _keys(state, "proposals") == {("E03", "Fri", "leave", None)}
    assert state["last_preview"] is None


def test_record_commit_recovers_after_response_interruption_without_duplicate_condition(
    agent_client,
    monkeypatch,
):
    from backend.app.api.dependencies import conversation_repository
    from backend.app.services.dialogue_agent import DialogueAgent

    conversation = _conversation(agent_client)
    finish = DialogueAgent.finish

    def interrupted(self, **kwargs):
        raise RuntimeError("fault injection: response transport interrupted")

    monkeypatch.setattr(DialogueAgent, "finish", interrupted)
    response = _send(
        agent_client, conversation, "E18周四晚班优先。", client_message_id="interrupted"
    )
    assert response.status_code == 500, response.text
    committed = _state(agent_client, conversation)
    assert _keys(committed) == {("E18", "Thu", "preference", "evening")}
    with conversation_repository.database.transaction(immediate=True) as session:
        row = session.get(ConversationRecord, conversation)
        row.active_turn_started_at = utc_now() - timedelta(hours=1)
    monkeypatch.setattr(DialogueAgent, "finish", finish)
    recovered, state = _turn(agent_client, conversation, "E18周四晚班优先。", "interrupted")
    assert state == committed
    assert recovered["assistant_message"]["metadata"]["conditions"] == [
        {"employee_id": "E18", "type": "preference", "day": "Thu", "shift": "evening"},
    ]
    _assert_no_draft(agent_client)
