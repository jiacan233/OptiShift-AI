"""Scenario lifecycle, exact repair scope and public error regression tests."""

import json
from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.app.models import ScenarioPatch, ScheduleChange
from backend.app.models.orm import ConversationScenarioRecord
from backend.app.models.scenario_changes import (
    apply_scenario_patch,
    apply_scenario_patches,
    route_scenario_patches,
    scenario_patches_to_schedule_changes,
)
from tests.test_agent import WEEK_40, WORKSPACE, _conversation, _generate_and_confirm, _send
from tests.test_agent import agent_client as scenario_api_client

agent_client = scenario_api_client


def semantic_edits(atoms, execution="preview"):
    return {"execution": execution, "edits": [
        {"employee_ids": [employee], "days": [day], "type": kind, "shift": shift}
        for employee, day, kind, shift in sorted(atoms)]}



def patch(employee="E02", days=("Tue",), kind="preference", shift="morning", operation="add"):
    return ScenarioPatch(
        employee_id=employee, days=days, change_type=kind, shift=shift, operation=operation
    )


def keys(patches):
    return {
        (c.employee_id, c.day.value, c.type.value, c.shift.value if c.shift else None)
        for c in scenario_patches_to_schedule_changes(patches)
    }


def test_reducer_operation_scopes():
    a, b = patch(), patch(days=["Wed"], shift="evening")
    other = patch(employee="E01", days=["Mon", "Tue"], kind="leave", shift=None)
    state = apply_scenario_patches([], [a, b, other])
    assert len(keys(state)) == 4
    removed = apply_scenario_patch(state, a.model_copy(update={"operation": "remove"}))
    assert keys(removed) == keys([b, other])
    replaced = apply_scenario_patch(state, b.model_copy(update={"operation": "set"}))
    assert keys(replaced) == keys([b, other])
    cleared = apply_scenario_patch(
        state, patch(days=["Tue"], kind="leave", shift=None, operation="clear")
    )
    assert keys(cleared) == keys([b, other])
    cleared = apply_scenario_patch(
        state, patch(days=[], kind="leave", shift=None, operation="clear")
    )
    assert keys(cleared) == keys([other])
    both = [a.model_copy(update={"operation": "set"}), b.model_copy(update={"operation": "set"})]
    assert keys(apply_scenario_patches(state, both)) == keys(state)


@pytest.mark.parametrize("kind", ["preference", "assign", "unassign"])
def test_shift_required(kind):
    with pytest.raises(ValidationError):
        ScenarioPatch(employee_id="E02", days=["Wed"], change_type=kind)


def test_inconsistent_operations_rejected():
    change = ScheduleChange(employee_id="E02", day="Wed", type="preference", shift="evening")
    with pytest.raises((ValueError, ValidationError)):
        route_scenario_patches(
            [change],
            [{"employee_id": "E02", "day": "Wed", "type": "preference", "shift": "morning"}],
        )


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "E02 周二早班优先 + 周三晚班优先，帮我试排一下",
            {("E02", "Tue", "preference", "morning"), ("E02", "Wed", "preference", "evening")},
        ),
        ("E02 周三晚班优先，帮我试排一下", {("E02", "Wed", "preference", "evening")}),
        (
            "E01 周一周二请假，E02 周三晚班优先，帮我试排一下",
            {
                ("E01", "Mon", "leave", None),
                ("E01", "Tue", "leave", None),
                ("E02", "Wed", "preference", "evening"),
            },
        ),
    ],
)
def test_complete_conditions_reach_preview_and_progress(agent_client, semantic_reply, text, expected):
    from backend.app.api.dependencies import agent_service

    semantic_reply(semantic_edits(expected))
    cid = _conversation(agent_client)
    response = _send(agent_client, cid, text, client_message_id="conditions")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["schedule_result"]["status"] == "scenario_preview"
    state = agent_service.tools.scenarios.get(cid, date.fromisoformat(WEEK_40))
    assert keys(state.patches) == expected
    conditions = result["assistant_message"]["metadata_json"]["conditions"]
    assert {(c["employee_id"], c["day"], c["type"], c["shift"]) for c in conditions} == expected
    progress = [
        e
        for e in result["execution_events"]
        if e["stage"] == "agent_route" and e["status"] == "completed"
    ]
    assert len(progress[-1]["details"]["changes"]) == len(conditions)
    assert "晚班优先" in result["assistant_message"]["content"]


def test_preview_and_infeasible_draft_have_identical_patches(agent_client, semantic_reply):
    from backend.app.api.dependencies import agent_service

    _generate_and_confirm(agent_client)
    states = []
    for index, ending in enumerate(["帮我试排一下", "帮我重新排一下，只生成待确认方案"]):
        semantic_reply(semantic_edits({("E01", "Mon", "leave", None), ("E01", "Tue", "leave", None),
            ("E02", "Mon", "leave", None), ("E02", "Wed", "preference", "evening")},
            execution="create_draft" if index else "preview"))
        cid = _conversation(agent_client)
        response = _send(
            agent_client,
            cid,
            "E01 周一周二请假，E02 周一请假，E02 周三晚班优先，" + ending,
            client_message_id=f"path-{index}",
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["schedule_result"]["status"] == ("infeasible" if index else "scenario_preview")
        calls = [c["tool_name"] for c in result["tool_calls"]]
        if not index:
            assert "preview_scenario" in calls
        if index:
            assert "replan_schedule" in calls
        states.append(agent_service.tools.scenarios.get(cid, date.fromisoformat(WEEK_40)).patches)
    assert states[0] == states[1]


def test_repair_verified_conditions_equal_actual_application(agent_client, semantic_reply):
    from backend.app.api.dependencies import agent_service

    semantic_reply(semantic_edits({("E01", "Mon", "leave", None), ("E02", "Mon", "leave", None)}))
    cid = _conversation(agent_client)
    response = _send(
        agent_client,
        cid,
        "E01 周一请假，E02 周一请假，帮我试排一下，只生成待确认方案。",
        client_message_id="repair",
    )
    assert response.status_code == 200, response.text
    preview = response.json()["schedule_result"]
    suggestions = preview["suggestions"]
    repair = next(s for s in suggestions if s["scenario_patch"]["employee_id"] == "E01")
    assert {("E02", "Mon", "leave", None)} == {
        (c["employee_id"], c["day"], c["type"], c["shift"]) for c in repair["candidate_changes"]
    }
    semantic_reply({"reference": "suggestion", "suggestion_id": repair["suggestion_id"], "adopt": True, "execution": "preview"})
    response = _send(
        agent_client,
        cid,
        f"按 {repair['suggestion_id']} 调整试排。",
        client_message_id="apply",
    )
    assert response.status_code == 200, response.text
    state = agent_service.tools.scenarios.get(cid, date.fromisoformat(WEEK_40))
    assert [
        c.model_dump(mode="json") for c in scenario_patches_to_schedule_changes(state.patches)
    ] == repair["candidate_changes"]
    assert response.json()["schedule_result"]["strict_feasible"]


def test_clear_revision_ownership_idempotency_and_legacy(agent_client):
    from backend.app.api.dependencies import agent_service

    repo = agent_service.tools.scenarios
    cid = _conversation(agent_client)
    week = date.fromisoformat(WEEK_40)
    confirmed = _generate_and_confirm(agent_client)
    repo.upsert_patch(cid, week, patch())
    with repo.database.transaction(immediate=True) as session:
        record = session.scalar(
            select(ConversationScenarioRecord).where(
                ConversationScenarioRecord.conversation_id == cid
            )
        )
        record.temporary_constraints = [
            {"employee_id": "E02", "days": ["Wed"], "change_type": "preference"}
        ]
    detail = agent_client.get(
        f"/api/agent/conversations/{cid}", params={"browser_workspace_id": WORKSPACE}
    )
    assert detail.status_code == 200
    assert detail.json()["scenario_notices"][0]["invalidated"]
    invalid = agent_client.get(
        f"/api/agent/conversations/{cid}/scenario",
        params={"browser_workspace_id": WORKSPACE, "week_start": WEEK_40},
    )
    assert invalid.status_code == 200
    assert invalid.json()["invalidated"] and not invalid.json()["patches"]
    rev = invalid.json()["scenario_revision"]

    def clear(workspace=WORKSPACE, revision=rev):
        return agent_client.request(
            "DELETE",
            f"/api/agent/conversations/{cid}/scenario",
            json={
                "browser_workspace_id": workspace,
                "week_start": WEEK_40,
                "expected_revision": revision,
            },
        )

    assert clear("foreign").status_code == 404
    assert clear(revision=rev - 1).status_code == 409
    assert clear().status_code == clear().status_code == 200
    assert not repo.get(cid, week).patches
    current = agent_client.get(f"/api/schedules/{confirmed['schedule_id']}").json()
    assert current == confirmed["schedule"]
    assert (
        agent_client.get(
            f"/api/agent/conversations/{cid}", params={"browser_workspace_id": WORKSPACE}
        ).status_code
        == 200
    )


def test_clear_does_not_touch_draft_or_newer_scenario(agent_client):
    from backend.app.api.dependencies import agent_service

    cid = _conversation(agent_client)
    repo = agent_service.tools.scenarios
    week = date.fromisoformat(WEEK_40)
    generated = agent_client.post(
        "/api/schedule/generate", json={"week_start": WEEK_40, "prompt": ""}
    ).json()
    stored_draft = agent_client.get(f"/api/schedules/{generated['schedule_id']}").json()
    repo.upsert_patch(cid, week, patch())
    repo.upsert_patch(cid, week, patch(days=["Wed"], shift="evening"))
    response = agent_client.request(
        "DELETE",
        f"/api/agent/conversations/{cid}/scenario",
        json={"browser_workspace_id": WORKSPACE, "week_start": WEEK_40, "expected_revision": 1},
    )
    assert response.status_code == 409
    assert len(keys(repo.get(cid, week).patches)) == 2
    response = agent_client.request(
        "DELETE",
        f"/api/agent/conversations/{cid}/scenario",
        json={"browser_workspace_id": WORKSPACE, "week_start": WEEK_40, "expected_revision": 2},
    )
    assert response.status_code == 200
    assert agent_client.get(f"/api/schedules/{generated['schedule_id']}").json() == stored_draft


def test_preference_survives_save_analyze_and_force_boundaries(agent_client, monkeypatch):
    from backend.app.api.dependencies import agent_service
    from backend.app.models import ForceRequest

    tools = agent_service.tools
    cid = _conversation(agent_client)
    week = date.fromisoformat(WEEK_40)
    changes = scenario_patches_to_schedule_changes([patch(), patch(days=["Wed"], shift="evening")])
    preview = tools.preview_scenario(conversation_id=cid, target_week=week, changes=changes)
    assert preview["strict_feasible"]
    saved = tools.save_scenario(
        conversation_id=cid,
        target_week=week,
        source_conversation_id=cid,
        source_client_message_id="save-pref",
        source_user_message_id="user-pref",
    )
    assert saved["validation"]["passed"]
    record = tools.schedules.get_record(saved["schedule_id"])
    assert record["metadata"]["requested_changes"] == [c.model_dump(mode="json") for c in changes]
    # Observe the real analyze solver's context without replacing the solver.
    from backend.app.solver.primary_solver import PrimarySolver

    solve = PrimarySolver.solve
    observed = []

    def capture(self, context, **kwargs):
        observed.extend(context.requested_changes)
        return solve(self, context, **kwargs)

    monkeypatch.setattr(PrimarySolver, "solve", capture)
    tools.analyze_staffing(
        target_week=week,
        plan={"question_type": "feasibility_explanation"},
        snapshot=tools.get_current_schedule(target_week=week)["display"],
        conversation_id=cid,
    )
    assert observed == changes
    captured = {}
    monkeypatch.setattr(
        tools.scheduling, "force_generate", lambda **kwargs: captured.update(kwargs) or {}
    )
    tools.force_generate_schedule(
        target_week=week,
        force_request=ForceRequest(authorization_reason="test boundary"),
        changes=[],
        source_conversation_id=cid,
        source_client_message_id="force-boundary",
        source_user_message_id="user-pref",
    )
    assert captured["changes"] == changes


@pytest.mark.parametrize("stream", [False, True])
def test_internal_validation_is_sanitized_and_persisted_safely(agent_client, semantic_reply, monkeypatch, stream):
    from backend.app.api.dependencies import agent_service

    def broken(**kwargs):
        return ScheduleChange(employee_id="E02", type="preference", day="Wed")

    semantic_reply(semantic_edits({("E02", "Wed", "preference", "evening")}))
    monkeypatch.setattr(agent_service.tools.scheduling, "preview_scenario", broken)
    cid = _conversation(agent_client)
    body = {
        "browser_workspace_id": WORKSPACE,
        "current_week_start": WEEK_40,
        "client_message_id": "internal",
        "content": "E02 周三晚班优先，帮我试排一下",
    }
    response = agent_client.post(
        f"/api/agent/conversations/{cid}/messages" + ("/stream" if stream else ""), json=body
    )
    if stream:
        frames = [f for f in response.text.split("\n\n") if f.startswith("event: error")]
        assert len(frames) == 1
        error = json.loads(frames[0].split("data: ")[1])
        assert error["status"] == 500
    else:
        assert response.status_code == 500
        error = response.json()["error"]
    assert error["code"] == "agent_internal_error"
    detail = agent_client.get(
        f"/api/agent/conversations/{cid}", params={"browser_workspace_id": WORKSPACE}
    )
    for forbidden in ["pydantic.dev", "validation error for", "Traceback", "shift is required"]:
        assert forbidden not in response.text
        assert forbidden not in detail.text


def test_missing_preference_shift_clarifies(agent_client, semantic_reply):
    semantic_reply(semantic_edits({("E02", "Wed", "preference", None)}, execution="create_draft"))
    cid = _conversation(agent_client)
    response = _send(agent_client, cid, "E02 周三优先，帮我重新排一下", client_message_id="clarify")
    assert response.status_code == 200
    assert response.json()["intent"] == "clarification"
    assert response.json()["schedule_result"] is None


def test_followup_set_preserves_other_employee_preference(agent_client, semantic_reply):
    from backend.app.api.dependencies import agent_service

    cid = _conversation(agent_client)
    semantic_reply(
        semantic_edits({("E01", "Mon", "leave", None), ("E01", "Tue", "leave", None), ("E02", "Wed", "preference", "evening")}),
        {"execution": "preview", "reference": "current", "edits": [{"operation": "remove", "employee_ids": ["E01"], "days": ["Tue"], "type": "leave"}]},
        {"execution": "preview", "reference": "current"},
    )
    for index, text in enumerate([
        "E01 周一周二请假，E02 周三晚班优先，帮我试排一下。",
        "把 E01 改成只周一请假，E02 周三晚班优先保持不变，再试排。",
        "那如果只让 E01 周一请假呢？",
    ]):
        response = _send(agent_client, cid, text, client_message_id=f"set-{index}")
        assert response.status_code == 200, response.text
        assert response.json()["schedule_result"]["status"] == "scenario_preview"
    state = agent_service.tools.scenarios.get(cid, date.fromisoformat(WEEK_40))
    assert keys(state.patches) == {
        ("E01", "Mon", "leave", None), ("E02", "Wed", "preference", "evening")
    }


def test_staffing_only_clear_is_revision_fenced(agent_client, semantic_reply):
    from backend.app.api.dependencies import agent_service
    cid = _conversation(agent_client)
    semantic_reply({"staffing_constraints": [{"scope": "SHIFT", "days": ["Wed"], "shifts": ["morning"], "min_count": 4, "max_count": 4}]})
    response = _send(agent_client, cid, "记录人数条件", client_message_id="staffing")
    assert response.status_code == 200
    revision = response.json()["dialogue_state"]["scenario_revision"]
    def clear(expected):
        return agent_client.request("DELETE", f"/api/agent/conversations/{cid}/scenario", json={
            "browser_workspace_id": WORKSPACE, "week_start": WEEK_40, "expected_revision": expected})
    assert clear(revision - 1).status_code == 409
    assert clear(revision).status_code == 200
    assert agent_service.tools.scenarios.get(cid, date.fromisoformat(WEEK_40)).revision == revision + 1
    from backend.app.repository.dialogue import DialogueRepository
    assert not DialogueRepository(agent_service.conversations.database).get(cid, date.fromisoformat(WEEK_40)).staffing_constraints


def test_every_repair_candidate_retains_staffing_constraints(agent_client, semantic_reply, monkeypatch):
    from backend.app.api.dependencies import agent_service
    observed = []
    solve = agent_service.tools.scheduling.solver.solve
    def capture(context, **kwargs):
        observed.append(context.staffing_constraints)
        return solve(context, **kwargs)
    monkeypatch.setattr(agent_service.tools.scheduling.solver, "solve", capture)
    plan = semantic_edits({("E01", "Mon", "leave", None), ("E02", "Mon", "leave", None)})
    plan["staffing_constraints"] = [{"scope": "SHIFT", "days": ["Wed"], "shifts": ["morning"], "min_count": 4, "max_count": 4}]
    semantic_reply(plan)
    cid = _conversation(agent_client)
    response = _send(agent_client, cid, "按全部条件试排", client_message_id="candidates")
    assert response.status_code == 200, response.text
    assert response.json()["schedule_result"]["suggestions"]
    assert len(observed) > 1
    assert all(constraints == observed[0] and constraints for constraints in observed)


def test_hypothetical_staffing_clear_can_be_adopted():
    from backend.app.models.dialogue import DialogueState, TurnCommand
    from backend.app.services.dialogue_reducer import reduce_command
    state = DialogueState(staffing_constraints=[{"scope": "DAY", "days": ["Wed"], "min_count": 8, "max_count": 8}])
    state, question = reduce_command(state, TurnCommand(execution="preview", staffing_operation="clear"), message_id="preview", employees=[], employee_revision=1)
    assert question is None and state.proposed_staffing == [] and state.staffing_constraints
    state, question = reduce_command(state, TurnCommand(execution="create_draft", reference="current"), message_id="adopt", employees=[], employee_revision=1)
    assert question is None and not state.staffing_constraints and state.proposed_staffing is None
