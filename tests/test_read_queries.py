from datetime import date
import json
from pathlib import Path

import pytest

from backend.app.models import ScenarioPatch
from backend.app.models.orm import ScheduleRecord
from backend.app.services.agent_router import AgentRoute
from backend.app.services.llm_client import AIUnavailableError
from backend.app.services.read_analysis import analyze_snapshot, counterfactual_snapshot
from backend.app.services.read_query import normalize_plan
from backend.app.models.dialogue import TurnCommand
from backend.app.services.read_response import compose_read_answer, READ_ONLY_NOTICE
from tests.read_fixtures import WEEK, PREVIOUS_MESSAGES, database_snapshot, seed_read_fixture


@pytest.fixture
def read_service(database, semantic_reply):
    service = seed_read_fixture(database)
    def reply(user):
        text = user["message"]
        if text == "刚才第二条建议为什么？":
            return {"reference": "suggestion", "suggestion_ordinal": 2, "execution": "analyze"}
        if text == "按刚才第一条改":
            return {"reference": "suggestion", "suggestion_ordinal": 1, "execution": "create_draft"}
        return {"execution": "analyze", "read_query": READ_PLANS[text]}
    semantic_reply(reply, service=service)
    return service


READ_PLANS = {
    "周日为什么 7 个人，6 个人不是够了吗？": {"question_type": "staffing_explanation", "day": "Sun"},
    "周日谁上班？": {"question_type": "schedule_overview", "day": "Sun"},
    "周日晚班谁会做饮品？": {"question_type": "coverage_analysis", "day": "Sun", "shift": "evening"},
    "2026-10-11 早班人数": {"question_type": "staffing_explanation", "day": "Sun", "shift": "morning"},
    "如果去掉 E07 周日晚班可以吗？": {"question_type": "assignment_explanation", "day": "Sun", "shift": "evening", "employee_ids": ["E07"], "whether_counterfactual_needed": True},
    "周日早班少一个人行不行？": {"question_type": "staffing_explanation", "day": "Sun", "shift": "morning", "whether_counterfactual_needed": True},
    "E15 是不是必须上周日早班？": {"question_type": "assignment_explanation", "day": "Sun", "shift": "morning", "employee_ids": ["E15"], "whether_counterfactual_needed": True},
    "E03 能不能不排周日早班？": {"question_type": "assignment_explanation", "day": "Sun", "shift": "morning", "employee_ids": ["E03"], "whether_counterfactual_needed": True},
    "周日为什么 7 个人？": {"question_type": "staffing_explanation", "day": "Sun"},
}


def send(service, content, mid="read-1", conversation_id=None, **kwargs):
    cid = conversation_id or service.create_conversation("read-workspace")["conversation_id"]
    return service.send_message(conversation_id=cid, browser_workspace_id="read-workspace",
                                client_message_id=mid, content=content, current_week_start=WEEK, **kwargs)


def test_current_query_does_not_inherit_previous_suggestion(read_service, monkeypatch):
    cid = read_service.create_conversation("read-workspace")["conversation_id"]
    read_service.conversations.add_assistant_message(
        cid, "read-workspace", content=PREVIOUS_MESSAGES[0]["content"], target_week="2026-09-28",
        metadata=PREVIOUS_MESSAGES[0]["metadata"],
    )
    result = send(read_service, "周日为什么 7 个人，6 个人不是够了吗？", conversation_id=cid)
    metadata = result["assistant_message"]["metadata_json"]
    assert metadata["query_plan"]["reference_mode"] == "none"
    assert metadata["query_plan"]["target_week"] == WEEK.isoformat()
    assert metadata["query_plan"]["day"] == "Sun"
    assert metadata["query_plan"]["employee_ids"] == []
    assert [s["shift"] for s in metadata["read_analysis"]["slots"]] == ["morning", "evening"]
    assert "恢复 E01" not in result["assistant_message"]["content"]


@pytest.mark.parametrize("identifier", ["suggestion_1", "suggestion_2", "missing"])
def test_structured_reference_must_exist(read_service, identifier):
    from backend.app.services.agent_router import AgentRouter
    route = AgentRouter.from_command(TurnCommand(reference="suggestion", suggestion_id=identifier))
    result = read_service._resolve_suggestion(route, PREVIOUS_MESSAGES)
    assert (result is not None) == (identifier != "missing")


def test_explicit_suggestion_still_resolves(read_service):
    route = read_service.router.route("刚才第二条建议为什么？", employees=read_service.employees.list(), recent_messages=PREVIOUS_MESSAGES)
    assert read_service._resolve_suggestion(route, PREVIOUS_MESSAGES)["id"] == "suggestion_2"


@pytest.mark.parametrize("text,shifts", [("周日谁上班？", ["morning", "evening"]), ("周日晚班谁会做饮品？", ["evening"]), ("2026-10-11 早班人数", ["morning"])])
def test_scope_and_validator_consistency(read_service, text, shifts):
    plan = normalize_plan(text, read_service.employees.list(), target_week=WEEK, proposal=READ_PLANS[text])
    snapshot = read_service.tools.get_current_schedule(target_week=WEEK)["display"]
    facts = read_service.tools.analyze_staffing(target_week=WEEK, plan=plan.model_dump(mode="json"), snapshot=snapshot)
    assert [s["shift"] for s in facts["slots"]] == shifts
    assert facts["validation"]["valid"] is True
    for slot in facts["slots"]:
        rows = {r["rule_id"]: r for r in slot["validation"]["coverage"]}
        assert rows["R04"]["actual"] == slot["actual_staff"]
        assert rows["R04"]["expected"] == slot["minimum_staff"]
        for rule, skill in [("R01", "manager"), ("R02", "beverage"), ("R03", "cashier")]:
            assert rows[rule]["actual"] == slot[skill]["actual"]
            assert rows[rule]["passed"] == slot[skill]["passed"]


@pytest.mark.parametrize("text", ["如果去掉 E07 周日晚班可以吗？", "周日早班少一个人行不行？", "E15 是不是必须上周日早班？", "E03 能不能不排周日早班？"])
def test_counterfactual_no_business_writes_and_timeline(read_service, database, text):
    cid = read_service.create_conversation("read-workspace")["conversation_id"]
    read_service.tools.scenarios.upsert_patch(cid, WEEK, ScenarioPatch(employee_id="E03", days=["Wed"]))
    before = database_snapshot(database, business_only=True)
    events = []
    result = send(read_service, text, conversation_id=cid, event_sink=events.append)
    assert database_snapshot(database, business_only=True) == before
    assert result["schedule_result"] is None
    assert result["mutation_requested"] is False
    assert [c["tool_name"] for c in result["tool_calls"]] == ["get_current_schedule", "analyze_counterfactual"]
    assert any(e["stage"] == "counterfactual" and e["status"] == "completed" for e in events)
    assert READ_ONLY_NOTICE in result["assistant_message"]["content"]


def test_direct_removal_and_alternatives_are_distinct(read_service):
    plan = normalize_plan("如果去掉 E07 周日晚班可以吗？", read_service.employees.list(), target_week=WEEK, proposal=READ_PLANS["如果去掉 E07 周日晚班可以吗？"])
    snapshot = read_service.tools.get_current_schedule(target_week=WEEK)["display"]
    schedule, context = read_service.tools._read_snapshot(target_week=WEEK, snapshot=snapshot)
    original = schedule.model_dump(mode="json")
    item = counterfactual_snapshot(schedule, context, plan)["counterfactuals"][0]
    assert item["direct_removal_slot_passed"] is False
    assert any(v["rule_id"] == "R04" for v in item["violations"])
    assert item["replacement_employee_ids"] == ["E13", "E14", "E16"]
    assert item["multiple_replacements"] and not item["unique_necessity_proven"]
    assert item["re_solve_feasible"] is None
    assert schedule.model_dump(mode="json") == original


def test_draft_display_and_explicit_version(read_service, database):
    with database.transaction() as session:
        session.get(ScheduleRecord, "sch_eval_v2").status = "draft"
    assert read_service.tools.get_current_schedule(target_week=WEEK)["display"]["status"] == "draft"
    assert read_service.tools.get_current_schedule(target_week=WEEK, version=1)["display"]["version"] == 1
    assert read_service.tools.get_current_schedule(target_week=WEEK, version=99)["display"] is None


@pytest.mark.parametrize("failure", ["provider", "malformed"])
def test_llm_failure_stops_read_execution(read_service, monkeypatch, failure):
    read_service.llm.enabled = True
    def reply(**kwargs):
        if failure == "provider":
            raise AIUnavailableError("unavailable")
        if failure == "malformed":
            return {"invalid": "plan"}
        return {"intent": "explain", "employees": ["E999"]}
    monkeypatch.setattr(read_service.llm, "complete_json", reply)
    from backend.app.services.agent_service import AgentTurnError
    with pytest.raises(AgentTurnError) as error:
        send(read_service, "周日晚班谁会做饮品？")
    assert error.value.code == "ai_unavailable"


def test_read_idempotency(read_service):
    cid = read_service.create_conversation("read-workspace")["conversation_id"]
    first = send(read_service, "周日谁上班？", conversation_id=cid)
    second = send(read_service, "周日谁上班？", conversation_id=cid)
    assert first["assistant_message"]["message_id"] == second["assistant_message"]["message_id"]
    assert first["tool_calls"] == second["tool_calls"]


def test_invalid_model_answer_cannot_invent_facts(read_service, monkeypatch):
    read_service.llm.enabled = True
    monkeypatch.setattr(read_service.llm, "complete_json", lambda **kw: {"sentence_ids": ["actual_999"]})
    plan = normalize_plan("周日为什么 7 个人？", read_service.employees.list(), target_week=WEEK, proposal=READ_PLANS["周日为什么 7 个人？"])
    snapshot = read_service.tools.get_current_schedule(target_week=WEEK)["display"]
    schedule, context = read_service.tools._read_snapshot(target_week=WEEK, snapshot=snapshot)
    answer, audit = compose_read_answer(read_service.llm, question="人数", plan=plan, facts=analyze_snapshot(schedule, context, plan))
    assert "999" not in answer and "实际 7 人" in answer and "实际 6 人" in answer
    assert audit["fallback_reason"] == "invalid_sentence_selection"


def test_normalized_week_does_not_create_reference(read_service):
    from backend.app.services.agent_router import AgentRouter
    route = AgentRouter.from_command(TurnCommand(target_week=WEEK, execution="create_draft", explicit_empty=True))
    assert route.reference.type == "none" and route.target_week == WEEK


@pytest.mark.parametrize("stale", [None, "version", "scenario"])
def test_explicit_scenario_suggestion_guard(read_service, database, monkeypatch, stale):
    from backend.app.services.agent_service import AgentTurnError
    cid = read_service.create_conversation("read-workspace")["conversation_id"]
    state = read_service.tools.scenarios.upsert_patch(cid, WEEK, ScenarioPatch(employee_id="E03", days=["Wed"]))
    suggestion = {
        "id": "repair_1_wed", "title": "恢复可用", "target_week": WEEK.isoformat(),
        "based_on_schedule_id": "sch_eval_v2", "based_on_version": 1 if stale == "version" else 2,
        "based_on_scenario_revision": 0 if stale == "scenario" else state.revision,
        "scenario_patch": {"employee_id": "E03", "operation": "remove", "days": ["Wed"], "change_type": "leave"},
    }
    read_service.conversations.add_assistant_message(cid, "read-workspace", content="建议", target_week=WEEK,
                                                    metadata={"suggestions": [suggestion]})
    before = database_snapshot(database, business_only=True)
    monkeypatch.setattr(read_service.tools.scheduling, "preview_scenario", lambda **kw: {"status": "scenario_preview", "strict_feasible": True})
    if stale:
        with pytest.raises(AgentTurnError) as error:
            send(read_service, "按刚才第一条改", conversation_id=cid)
        assert error.value.code == "suggestion_stale"
        assert database_snapshot(database, business_only=True) == before
    else:
        result = send(read_service, "按刚才第一条改", conversation_id=cid)
        assert result["schedule_result"]["status"] == "scenario_preview"
        assert read_service.tools.scenarios.get(cid, WEEK).patches == []
        assert result["tool_calls"][-1]["input"]["expected_revision"] == state.revision


@pytest.mark.parametrize("case", json.loads(
    (Path(__file__).parent / "evals/agent_cases.json").read_text(encoding="utf-8")
), ids=lambda c: c["name"])
def test_evaluation_pipeline_offline_contract(read_service, database, monkeypatch, case):
    from backend.app.services.agent_router import AgentRouter
    from backend.app.services.read_turn import preview_read_turn
    from tests.evals.test_live_agent_eval import check_case
    from sqlalchemy import event
    read_service.llm.enabled = True
    def structured_reply(**kwargs):
        if kwargs["stage"] == "agent_semantic":
            expected = case["expected"]
            plan = {key: value for key, value in expected.items() if key not in {"shifts", "tools"}}
            plan["requested_facts"] = ["staffing", "coverage", "assignments", "workload", "rules", "validation", "difference"]
            plan["whether_counterfactual_needed"] = "analyze_counterfactual" in expected["tools"]
            if expected["question_type"] == "schedule_difference":
                plan["comparison"] = "previous_version"
            return TurnCommand(execution="analyze", target_week=expected["target_week"], read_query=plan,
                reference="suggestion" if expected["reference_mode"] == "suggestion" else "none",
                suggestion_ordinal=2 if expected["reference_mode"] == "suggestion" else None).model_dump(mode="json")
        return {"sentence_ids": list(kwargs["user"]["sentences"])}
    monkeypatch.setattr(read_service.llm, "complete_json", structured_reply)
    before = database_snapshot(database)
    def readonly(connection, record, proxy):
        connection.execute("PRAGMA query_only=ON")
    event.listen(database.engine, "checkout", readonly)
    try:
        result = preview_read_turn(read_service, content=case["messages"][-1], current_week_start=WEEK,
                                   recent_messages=case["previous_conversation_state"])
        assert check_case(case, result) == []
        assert database_snapshot(database) == before
    finally:
        event.remove(database.engine, "checkout", readonly)
