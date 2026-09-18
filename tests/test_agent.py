from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.app.models import HistoryStatus
from backend.app.services.agent_context import ResolvedWeek, WeekResolver
from backend.app.services.agent_router import AgentIntent, AgentRoute
from backend.app.services.agent_service import AgentService, StaleSuggestionError
from backend.app.services.llm_client import AIUnavailableError


WORKSPACE = "bw_agent_acceptance"
WEEK_40 = "2026-09-28"


@pytest.fixture
def agent_client(tmp_path, monkeypatch):
    import backend.app.database as database_module
    from backend.app.api import dependencies
    from backend.app.main import app

    database_module.database.path = tmp_path / "agent-api.db"
    monkeypatch.setattr(dependencies.agent_llm_client, "enabled", False)
    with TestClient(app) as value:
        yield value
    database_module.database.dispose()


def _conversation(client: TestClient, workspace: str = WORKSPACE) -> str:
    response = client.post(
        "/api/agent/conversations",
        json={"browser_workspace_id": workspace},
    )
    assert response.status_code == 200, response.text
    return response.json()["conversation_id"]


def _send(
    client: TestClient,
    conversation_id: str,
    content: str,
    *,
    client_message_id: str,
    workspace: str = WORKSPACE,
    current_week_start: str | None = WEEK_40,
    trusted_action: dict | None = None,
):
    payload = {
        "browser_workspace_id": workspace,
        "client_message_id": client_message_id,
        "content": content,
        "current_week_start": current_week_start,
    }
    if trusted_action is not None:
        payload["trusted_action"] = trusted_action
    return client.post(
        f"/api/agent/conversations/{conversation_id}/messages",
        json=payload,
    )


def _generate_and_confirm(client: TestClient, week_start: str = WEEK_40) -> dict:
    generated = client.post(
        "/api/schedule/generate",
        json={"week_start": week_start, "prompt": "生成测试排班"},
    )
    assert generated.status_code == 200, generated.text
    draft = generated.json()
    confirmed = client.post(
        "/api/schedule/confirm",
        json={"schedule_id": draft["schedule_id"], "version": draft["version"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def test_01_browser_workspace_creates_conversation(agent_client):
    conversation_id = _conversation(agent_client)

    assert conversation_id.startswith("conv_")


def test_force_agent_records_structured_authorization_and_replays(agent_client):
    agent_client.patch("/api/employees/E01", json={"leave_days": ["Mon"]})
    conversation_id = _conversation(agent_client)
    text = "我知道 E01 周一请假，但就是让 E01 周一早班上班。"
    response = _send(agent_client, conversation_id, text, client_message_id="force-agent-once")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["schedule_result"]["compliance_status"] == "authorized_violations"
    calls = [call for call in result["tool_calls"] if call["tool_name"] == "force_generate_schedule"]
    assert calls[0]["input"]["force_request"]["requested_overrides"][0]["rule_id"] == "R08"
    retry = _send(agent_client, conversation_id, text, client_message_id="force-agent-once")
    assert retry.status_code == 200
    assert retry.json()["schedule_result"]["schedule_id"] == result["schedule_result"]["schedule_id"]


def test_02_workspace_a_cannot_see_workspace_b_conversation(agent_client):
    conversation_id = _conversation(agent_client, "bw_a")

    listing = agent_client.get(
        "/api/agent/conversations", params={"browser_workspace_id": "bw_b"}
    )

    assert listing.status_code == 200
    assert listing.json()["conversations"] == []
    assert conversation_id not in str(listing.json())


def test_03_conversation_list_returns_history(agent_client):
    first = _conversation(agent_client)
    _send(
        agent_client,
        first,
        "这个项目怎么排班？",
        client_message_id="cm_history_1",
    )
    second = _conversation(agent_client)

    response = agent_client.get(
        "/api/agent/conversations", params={"browser_workspace_id": WORKSPACE}
    )

    assert response.status_code == 200
    rows = response.json()["conversations"]
    assert {item["conversation_id"] for item in rows} == {first, second}
    populated = next(item for item in rows if item["conversation_id"] == first)
    assert populated["message_count"] == 2
    assert populated["last_message_preview"]


def test_04_conversation_messages_are_persisted_server_side(agent_client):
    conversation_id = _conversation(agent_client)
    sent = _send(
        agent_client,
        conversation_id,
        "你知道我们的项目怎么排班吗？",
        client_message_id="cm_persist",
    )

    restored = agent_client.get(
        f"/api/agent/conversations/{conversation_id}",
        params={"browser_workspace_id": WORKSPACE},
    )

    assert sent.status_code == 200
    assert [item["role"] for item in restored.json()["messages"]] == [
        "user",
        "assistant",
    ]
    assert restored.json()["messages"][0]["content"] == "你知道我们的项目怎么排班吗？"


def test_05_get_conversation_restores_complete_multiturn_history(agent_client):
    conversation_id = _conversation(agent_client)
    _send(agent_client, conversation_id, "项目怎么排班？", client_message_id="cm_multi_1")
    _send(agent_client, conversation_id, "第40周呢？", client_message_id="cm_multi_2")

    restored = agent_client.get(
        f"/api/agent/conversations/{conversation_id}",
        params={"browser_workspace_id": WORKSPACE},
    ).json()

    assert len(restored["messages"]) == 4
    assert [item["sequence_number"] for item in restored["messages"]] == [1, 2, 3, 4]


def test_06_old_conversation_remains_recoverable_after_new_conversation(agent_client):
    old_id = _conversation(agent_client)
    _send(agent_client, old_id, "项目怎么排班？", client_message_id="cm_old")
    new_id = _conversation(agent_client)

    restored = agent_client.get(
        f"/api/agent/conversations/{old_id}",
        params={"browser_workspace_id": WORKSPACE},
    )

    assert new_id != old_id
    assert restored.status_code == 200
    assert len(restored.json()["messages"]) == 2


@pytest.mark.parametrize(
    ("case", "message", "expected_intent"),
    [
        ("07", "这个项目怎么排班？", "ask"),
        ("08", "这周有什么优化建议？", "advice"),
        ("09", "为什么 E03 周三不上班？", "explain"),
        ("10", "帮我检查当前排班有没有违反规则", "validate"),
        ("11", "今天天气怎么样？", "out_of_scope"),
    ],
    ids=["ask", "advice", "explain", "validate", "out_of_scope"],
)
def test_07_to_11_read_only_intents_do_not_create_drafts(
    agent_client, case, message, expected_intent
):
    conversation_id = _conversation(agent_client)

    response = _send(
        agent_client,
        conversation_id,
        message,
        client_message_id=f"cm_read_{case}",
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["intent"] == expected_intent
    assert payload["mutation_requested"] is False
    assert payload["schedule_result"] is None
    context = agent_client.get(
        "/api/schedules/week-context", params={"week_start": WEEK_40}
    ).json()
    assert context["draft_schedule"] is None


def test_12_generate_creates_a_draft(agent_client):
    conversation_id = _conversation(agent_client)

    response = _send(
        agent_client,
        conversation_id,
        "第40周帮我生成一版。",
        client_message_id="cm_generate",
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["intent"] == "generate"
    assert payload["schedule_result"]["schedule_status"] == "draft"
    assert payload["schedule_result"]["schedule"]["week_start"] == WEEK_40


def test_13_replan_creates_a_draft(agent_client):
    confirmed = _generate_and_confirm(agent_client)
    conversation_id = _conversation(agent_client)

    response = _send(
        agent_client,
        conversation_id,
        "E02 周五请假，帮我重新排一下。",
        client_message_id="cm_replan",
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["intent"] == "replan"
    assert payload["schedule_result"]["schedule_status"] == "draft"
    assert payload["schedule_result"]["schedule"]["parent_schedule_id"] == confirmed["schedule_id"]


def test_14_chat_confirmation_cannot_confirm_schedule(agent_client):
    conversation_id = _conversation(agent_client)
    generated = _send(
        agent_client,
        conversation_id,
        "第40周帮我生成一版。",
        client_message_id="cm_confirm_generate",
    ).json()

    response = _send(
        agent_client,
        conversation_id,
        "确认。",
        client_message_id="cm_chat_confirm",
    )
    context = agent_client.get(
        "/api/schedules/week-context", params={"week_start": WEEK_40}
    ).json()

    assert response.status_code == 200
    assert response.json()["mutation_requested"] is False
    assert response.json()["schedule_result"] is None
    assert context["confirmed_schedule"] is None
    assert context["draft_schedule"]["schedule_id"] == generated["schedule_result"]["schedule_id"]


def test_15_version_guard_rejects_stale_concrete_suggestion(agent_client):
    from backend.app.api import dependencies

    target = ResolvedWeek(date(2026, 9, 28), 2026, 40, "test")
    suggestion = {
        "target_week": WEEK_40,
        "based_on_schedule_id": "schedule-v1",
        "based_on_version": 1,
        "proposed_changes": [
            {"employee_id": "E01", "type": "unassign", "day": "Mon", "shift": "morning"}
        ],
    }
    current = {
        "confirmed": {
            "schedule_id": "schedule-v2",
            "version": 2,
            "schedule": {
                "schedule_id": "schedule-v2",
                "version": 2,
                "status": "confirmed",
                "week_start": WEEK_40,
                "assignments": [],
            },
        }
    }

    with pytest.raises(StaleSuggestionError):
        dependencies.agent_service._validate_suggestion_for_replan(
            suggestion=suggestion,
            target=target,
            current=current,
        )


def test_16_conversation_can_move_between_weeks(agent_client):
    conversation_id = _conversation(agent_client)
    first = _send(
        agent_client,
        conversation_id,
        "这周排得怎么样？",
        client_message_id="cm_cross_1",
    ).json()
    second = _send(
        agent_client,
        conversation_id,
        "那下周呢？",
        client_message_id="cm_cross_2",
    ).json()

    assert first["context"]["target_week"] == WEEK_40
    assert second["context"]["target_week"] == "2026-10-05"
    assert first["user_message"]["conversation_id"] == second["user_message"]["conversation_id"]


def test_17_iso_week_resolution_uses_iso_cross_year_rules():
    resolved = WeekResolver().resolve(
        content="看看2026年第1周。",
        route=AgentRoute(intent=AgentIntent.ASK, target_iso_year=2026, target_iso_week=1),
        current_week_start=date(2026, 1, 5),
        recent_messages=[],
    )

    assert resolved.week_start == date(2025, 12, 29)
    assert (resolved.iso_year, resolved.iso_week) == (2026, 1)


def test_18_week_40_resolves_to_2026_09_28():
    resolved = WeekResolver().resolve(
        content="看看2026年第40周。",
        route=AgentRoute(intent=AgentIntent.ASK, target_iso_year=2026, target_iso_week=40),
        current_week_start=None,
        recent_messages=[],
    )

    assert resolved.week_start.isoformat() == WEEK_40


def test_19_relative_next_week_uses_conversation_context():
    resolved = WeekResolver().resolve(
        content="那下周呢？",
        route=AgentRoute(intent=AgentIntent.ASK),
        current_week_start=date(2026, 9, 14),
        recent_messages=[{"target_week": WEEK_40}],
    )

    assert resolved.week_start == date(2026, 10, 5)
    assert resolved.source == "relative_week"


def test_20_active_workbench_week_is_used_for_generate(agent_client):
    conversation_id = _conversation(agent_client)
    active_week = "2026-09-21"

    response = _send(
        agent_client,
        conversation_id,
        "帮我生成一版。",
        client_message_id="cm_active_week",
        current_week_start=active_week,
    )

    assert response.status_code == 200, response.text
    assert response.json()["schedule_result"]["schedule"]["week_start"] == active_week


def test_21_pending_draft_blocks_second_mutation(agent_client):
    conversation_id = _conversation(agent_client)
    first = _send(
        agent_client,
        conversation_id,
        "第40周帮我生成一版。",
        client_message_id="cm_pending_1",
    )
    second = _send(
        agent_client,
        conversation_id,
        "第40周再生成一版。",
        client_message_id="cm_pending_2",
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "draft_pending"


def test_22_duplicate_client_message_id_does_not_duplicate_draft(agent_client):
    conversation_id = _conversation(agent_client)
    first = _send(
        agent_client,
        conversation_id,
        "第40周帮我生成一版。",
        client_message_id="cm_idempotent",
    )
    replay = _send(
        agent_client,
        conversation_id,
        "这段不同正文不应覆盖第一次请求",
        client_message_id="cm_idempotent",
        current_week_start="2026-10-05",
    )
    restored = agent_client.get(
        f"/api/agent/conversations/{conversation_id}",
        params={"browser_workspace_id": WORKSPACE},
    ).json()

    assert first.status_code == replay.status_code == 200
    assert first.json()["schedule_result"]["schedule_id"] == replay.json()["schedule_result"]["schedule_id"]
    assert len(restored["messages"]) == 2


def test_23_refresh_week_context_restores_pending_draft(agent_client):
    conversation_id = _conversation(agent_client)
    generated = _send(
        agent_client,
        conversation_id,
        "第40周帮我生成一版。",
        client_message_id="cm_refresh",
    ).json()["schedule_result"]

    refreshed = agent_client.get(
        "/api/schedules/week-context", params={"week_start": WEEK_40}
    )

    assert refreshed.status_code == 200
    assert refreshed.json()["display_schedule"]["schedule_id"] == generated["schedule_id"]
    assert refreshed.json()["draft_schedule"]["status"] == "draft"


def test_24_history_unavailable_is_a_structured_409(agent_client):
    _generate_and_confirm(agent_client, WEEK_40)
    conversation_id = _conversation(agent_client)

    response = _send(
        agent_client,
        conversation_id,
        "2026年第42周帮我生成一版。",
        client_message_id="cm_history_unavailable",
        current_week_start="2026-10-12",
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "history_unavailable"
    assert response.json()["error"]["details"]["assistant_message"]["role"] == "assistant"


def test_25_unavailable_history_is_not_treated_as_known_empty(agent_client):
    from backend.app.api import dependencies

    _generate_and_confirm(agent_client, WEEK_40)

    previous, status = dependencies.schedule_repository.previous_week_context(
        date(2026, 10, 12)
    )

    assert previous is None
    assert status is HistoryStatus.UNAVAILABLE


def test_26_llm_failure_returns_ai_unavailable(agent_client, monkeypatch):
    from backend.app.api import dependencies

    conversation_id = _conversation(agent_client)
    monkeypatch.setattr(dependencies.agent_llm_client, "enabled", True)

    def fail(**_kwargs):
        raise AIUnavailableError("provider down")

    monkeypatch.setattr(dependencies.agent_llm_client, "complete_json", fail)

    response = _send(
        agent_client,
        conversation_id,
        "这个项目怎么排班？",
        client_message_id="cm_llm_failure",
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_unavailable"


def test_27_missing_conversation_returns_404(agent_client):
    response = agent_client.get(
        "/api/agent/conversations/conv_missing",
        params={"browser_workspace_id": WORKSPACE},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "conversation_not_found"


def test_28_cross_workspace_conversation_access_returns_safe_404(agent_client):
    conversation_id = _conversation(agent_client, "bw_owner")

    read = agent_client.get(
        f"/api/agent/conversations/{conversation_id}",
        params={"browser_workspace_id": "bw_intruder"},
    )
    write = _send(
        agent_client,
        conversation_id,
        "项目怎么排班？",
        client_message_id="cm_intruder",
        workspace="bw_intruder",
    )

    assert read.status_code == 404
    assert write.status_code == 404
    assert read.json()["error"]["code"] == "conversation_not_found"
    assert write.json()["error"]["code"] == "conversation_not_found"


def test_29_infeasible_agent_result_is_persisted_with_deterministic_summary(agent_client, monkeypatch):
    from backend.app.api import dependencies

    conversation_id = _conversation(agent_client)
    infeasible = {
        "status": "infeasible",
        "conflicts": [{
            "rule_id": "R01",
            "day": "Mon",
            "shift": "morning",
            "required": 1,
            "available": 0,
            "shortage": 1,
        }],
        "blocking_candidates": [],
        "diagnosis": None,
        "message": "No valid schedule exists.",
        "generated_valid_schedule": False,
    }

    def fake_run(tool_name, **_inputs):
        if tool_name == "get_current_schedule":
            return {"target_week": WEEK_40, "confirmed": None, "draft": None, "display": None}
        if tool_name == "generate_schedule":
            return infeasible
        raise AssertionError(tool_name)

    monkeypatch.setattr(dependencies.agent_service.tools, "run", fake_run)
    response = _send(
        agent_client,
        conversation_id,
        "第40周帮我生成一版。",
        client_message_id="cm_infeasible_persist",
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "**主要冲突**" in payload["assistant_message"]["content"]
    persisted = payload["assistant_message"]["metadata_json"]["infeasible_result"]
    assert persisted == infeasible
    restored = agent_client.get(
        f"/api/agent/conversations/{conversation_id}",
        params={"browser_workspace_id": WORKSPACE},
    ).json()
    assert restored["messages"][1]["metadata_json"]["infeasible_result"] == infeasible


def test_30_infeasible_public_history_is_compact():
    result = AgentService._public_messages([{
        "role": "assistant",
        "content": "无法排班",
        "intent": "generate",
        "target_week": WEEK_40,
        "metadata": {
            "infeasible_result": {
                "status": "infeasible",
                "message": "No valid schedule exists.",
                "conflicts": [{"rule_id": str(index)} for index in range(8)],
                "blocking_candidates": [{"employee_id": f"E{index:02d}"} for index in range(8)],
                "diagnosis": {"summary": "summary", "diagnostic_conflicts": list(range(100))},
                "generated_valid_schedule": False,
            }
        },
    }])

    metadata = result[0]["metadata"]["infeasible_result"]
    assert len(metadata["conflicts"]) == 5
    assert len(metadata["blocking_candidates"]) == 5
    assert metadata["diagnosis"] == {"summary": "summary"}
