"""Broad advice uses real Validator/CP-SAT results and the persisted card executor.

Only provider semantics/composition are scripted; no live provider is required.
"""
from datetime import timedelta
from uuid import uuid4

import pytest

from backend.app.models import Employee, Shift, WEEK_DAYS
from backend.app.models.orm import ScheduleRecord
from backend.app.repository.dialogue import DialogueRepository
from backend.app.services.agent_router import TrustedAgentAction
from backend.app.services.agent_service import AgentTurnError
from tests.read_fixtures import WEEK, database_snapshot, seed_read_fixture


QUESTION = "这周排班有什么可以优化的吗？"
WORKSPACE = "advice-regression"


@pytest.fixture
def advice_service(database, semantic_reply):
    service = seed_read_fixture(database)
    # An available employee with no shifts makes the valid baseline concretely
    # improvable without relying on a solver's choice of initial assignments.
    service.employees.create(Employee(id="E17", role="full_time",
        skills=["manager", "beverage", "cashier"], available_days=list(WEEK_DAYS)))
    service.tools.scheduling.context_builder.rules.max_time_seconds = 1
    semantic_reply(lambda _: {"execution": "advice", "read_query": {"question_type": "general_question"}}, service=service)
    return service


def send(service, cid, content=QUESTION, **kwargs):
    return service.send_message(conversation_id=cid, browser_workspace_id=WORKSPACE,
        client_message_id=uuid4().hex, content=content, current_week_start=WEEK, **kwargs)


def advice(service):
    cid = service.create_conversation(WORKSPACE)["conversation_id"]
    result = send(service, cid)
    return cid, result, result["assistant_message"]["metadata_json"]["suggestions"]


def apply(service, cid, suggestion, execution="record", **overrides):
    action = dict(intent="replan" if execution == "create_draft" else "advice",
        target_week=WEEK, suggestion_id=suggestion["suggestion_id"],
        suggestion_set_id=suggestion["suggestion_set_id"], execution=execution)
    action.update(overrides)
    return send(service, cid, "采纳这条建议", trusted_action=TrustedAgentAction(**action))


@pytest.mark.parametrize("entry", ["broad_read", "dialogue_advice", "trusted_advice"])
def test_broad_advice_produces_only_verified_unique_cards(advice_service, database, semantic_reply, entry):
    service = advice_service
    if entry == "dialogue_advice":
        semantic_reply(lambda _: {"execution": "advice"}, service=service)
    cid = service.create_conversation(WORKSPACE)["conversation_id"]
    before = database_snapshot(database, business_only=True)
    kwargs = {"trusted_action": TrustedAgentAction(intent="advice", target_week=WEEK)} if entry == "trusted_advice" else {}
    first = send(service, cid, **kwargs)
    metadata = first["assistant_message"]["metadata_json"]
    cards = metadata["suggestions"]
    assert first["assistant_message"]["content"]
    assert "旧建议缺少可验证的来源" not in first["assistant_message"]["content"]
    assert first["intent"] == "advice"
    assert first["schedule_result"] is None
    assert metadata["analysis"]["schedule_id"] == "sch_eval_v2"
    assert [c["tool_name"] for c in first["tool_calls"]] == ["analyze_schedule", "build_suggestions"]
    assert cards
    persisted = DialogueRepository(database).get(cid, WEEK).suggestion_sets[-1]
    assert persisted["suggestions"] == cards
    for card in cards:
        assert card["source_message_id"] == persisted["source_message_id"]
        assert card["suggestion_set_id"] == persisted["suggestion_set_id"]
        assert card["suggestion_id"].startswith("sug_")
        assert card["target_week"] == WEEK.isoformat()
        assert (card["based_on_schedule_id"], card["based_on_version"]) == ("sch_eval_v2", 2)
        assert card["based_on_scenario_revision"] == 0
        assert card["dependency_type"] == "schedule"
        assert card["dependencies"] == persisted["dependencies"]
        assert {"employee_revision", "employees_hash", "rules_hash", "configured_rules_hash",
            "history_id", "history_version", "history_hash", "history_status", "scenario_revision",
            "conditions_hash", "scenario_hash", "staffing_hash", "following_hash"} <= card["dependencies"].keys()
        assert {c["type"] for c in card["proposed_changes"]} == {"assign", "unassign"}
        assert all(c["employee_id"] and c["day"] and c["shift"] for c in card["proposed_changes"])
        assert card["executable"] is True and card["feasibility"] == "validated"
        assert card["validation"]["valid"] is True
        assert card["strict_preview"]["strict_feasible"] is True
        assert card["strict_preview"]["validation"]["valid"] is True
        assert card["improvement"]["after"] < card["improvement"]["before"]
    second = send(service, cid, **kwargs)["assistant_message"]["metadata_json"]["suggestions"]
    assert second
    assert {c["suggestion_id"] for c in cards}.isdisjoint(c["suggestion_id"] for c in second)
    assert cards[0]["suggestion_set_id"] != second[0]["suggestion_set_id"]
    assert database_snapshot(database, business_only=True) == before


@pytest.mark.parametrize("execution", ["record", "preview", "create_draft"])
def test_verified_card_action_contracts(advice_service, database, execution):
    service = advice_service
    cid, _, cards = advice(service)
    result = apply(service, cid, cards[0], execution)
    state = DialogueRepository(database).get(cid, WEEK)
    assert [c.model_dump(mode="json") for c in state.conditions[0].changes] == cards[0]["proposed_changes"]
    assert state.conditions[0].suggestion_id == cards[0]["suggestion_id"]
    current = service.tools.get_current_schedule(target_week=WEEK)
    assert current["confirmed"]["schedule_id"] == "sch_eval_v2"
    if execution == "record":
        assert result["schedule_result"] is None
        assert result["tool_calls"] == []
        assert current["draft"] is None
    else:
        schedule = result["schedule_result"]
        assert schedule["validation"]["valid"] is True
        assignments = {(a["employee_id"], a["day"], a["shift"]) for a in schedule["schedule"]["assignments"]}
        for change in cards[0]["proposed_changes"]:
            key = (change["employee_id"], change["day"], change["shift"])
            assert (key in assignments) == (change["type"] == "assign")
        if execution == "preview":
            assert schedule["strict_feasible"] is True
            assert current["draft"] is None
        else:
            assert schedule["status"] == "feasible"
            assert current["draft"]["schedule_id"] == schedule["schedule_id"]


@pytest.mark.parametrize("changed", ["version", "employee", "rules", "history", "scenario", "scenario_reverted", "following"])
def test_card_rejects_changed_dependencies(advice_service, database, semantic_reply, changed):
    service = advice_service
    cid, _, cards = advice(service)
    if changed == "employee":
        service.employees.update("E17", {"preferred_shift": Shift.EVENING})
    elif changed == "rules":
        service.tools.scheduling.context_builder.rules.max_shifts_per_week += 1
    elif changed in {"scenario", "scenario_reverted"}:
        semantic_reply({"edits": [{"employee_ids": ["E17"], "days": ["Tue"], "type": "preference", "shift": "morning"}]}, service=service)
        send(service, cid, "E17周二早班优先")
        if changed == "scenario_reverted":
            semantic_reply({"edits": [{"operation": "remove", "employee_ids": ["E17"], "days": ["Tue"]}]}, service=service)
            send(service, cid, "取消刚才条件")
    else:
        # Isolate the dependency change without introducing unrelated solver results.
        with database.transaction() as session:
            if changed == "version":
                session.get(ScheduleRecord, "sch_eval_v2").version = 3
            else:
                from backend.app.database import utc_now
                session.add(ScheduleRecord(schedule_id=f"sch_{changed}", lineage_id=changed, version=1,
                    status="confirmed", week_start=WEEK + timedelta(days=-7 if changed == "history" else 7),
                    validation_json={}, metadata_json={}, created_at=utc_now(), confirmed_at=utc_now()))
    before = database_snapshot(database, business_only=True)
    before_state = DialogueRepository(database).get(cid, WEEK)
    with pytest.raises(AgentTurnError) as error:
        apply(service, cid, cards[0], "create_draft")
    assert error.value.code == "suggestion_stale"
    assert DialogueRepository(database).get(cid, WEEK) == before_state
    assert database_snapshot(database, business_only=True) == before


@pytest.mark.parametrize("bad_reference", ["wrong_set", "wrong_week", "legacy"])
def test_unverified_source_cannot_be_adopted(advice_service, database, bad_reference):
    service = advice_service
    cid, _, cards = advice(service)
    overrides = {}
    if bad_reference == "wrong_set":
        overrides["suggestion_set_id"] = "set_not_the_source"
    elif bad_reference == "wrong_week":
        overrides["target_week"] = WEEK + timedelta(days=7)
    else:
        legacy = {"id": "suggestion_1", "suggestion_id": "suggestion_1", "action": "replan",
            "target_week": WEEK.isoformat(), "based_on_schedule_id": "sch_eval_v2", "based_on_version": 2,
            "proposed_changes": cards[0]["proposed_changes"]}
        service.conversations.add_assistant_message(cid, WORKSPACE, content="旧建议", target_week=WEEK,
            metadata={"suggestions": [legacy]})
        overrides.update(suggestion_id="suggestion_1", suggestion_set_id=None)
    before = database_snapshot(database, business_only=True)
    with pytest.raises(AgentTurnError) as error:
        apply(service, cid, cards[0], "create_draft", **overrides)
    assert error.value.code == "suggestion_stale"
    assert database_snapshot(database, business_only=True) == before


@pytest.mark.parametrize("failure", ["no_schedule", "validator", "strict_preview"])
def test_analysis_survives_without_verified_candidates(advice_service, database, monkeypatch, failure):
    service = advice_service
    if failure == "no_schedule":
        with database.transaction() as session:
            for sid in ("sch_eval_v1", "sch_eval_v2"):
                session.get(ScheduleRecord, sid).status = "cancelled"
    elif failure == "validator":
        from backend.app.models import ValidationResult
        monkeypatch.setattr(service.tools.scheduling.validator, "validate",
            lambda *a, **kw: ValidationResult(valid=False, hard_constraints={}, passed_count=0))
    else:
        monkeypatch.setattr(service.tools.scheduling, "preview_scenario",
            lambda **kw: {"strict_feasible": False})
    _, result, cards = advice(service)
    assert result["assistant_message"]["content"]
    assert cards == []
    assert result["schedule_result"] is None
    assert service.tools.get_current_schedule(target_week=WEEK)["draft"] is None


def test_dependency_change_during_verification_does_not_publish_cards(advice_service, database, monkeypatch):
    service = advice_service
    original = service.tools.scheduling.preview_scenario
    def changing_preview(**kwargs):
        result = original(**kwargs)
        service.employees.update("E17", {"preferred_shift": Shift.EVENING})
        return result
    monkeypatch.setattr(service.tools.scheduling, "preview_scenario", changing_preview)
    cid = service.create_conversation(WORKSPACE)["conversation_id"]
    with pytest.raises(AgentTurnError) as error:
        send(service, cid)
    assert error.value.code == "suggestion_stale"
    assert DialogueRepository(database).get(cid, WEEK).suggestion_sets == []
