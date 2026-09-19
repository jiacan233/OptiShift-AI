from __future__ import annotations

from datetime import date
import os
import pytest

from backend.app.database import Database, seed_demo_employees
from backend.app.models import Day, Shift
from backend.app.repository import (
    ConversationRepository,
    EmployeeRepository,
    ScenarioRepository,
    ScheduleRepository,
)
from backend.app.services.agent_router import AgentRouter
from backend.app.services.agent_service import AgentService
from backend.app.services.agent_tools import AgentTools
from backend.app.services.llm_client import AgentLLMClient
from backend.app.services.scheduling_service import SchedulingService


@pytest.fixture
def eval_service(tmp_path):
    db = Database(tmp_path / "force-eval.db")
    db.initialize()
    seed_demo_employees(db)
    emp_repo = EmployeeRepository(db)
    sched_repo = ScheduleRepository(db)
    scen_repo = ScenarioRepository(db)
    sched_svc = SchedulingService(emp_repo, sched_repo, scenarios=scen_repo)
    tools = AgentTools(emp_repo, sched_repo, sched_svc, scen_repo)
    conv_repo = ConversationRepository(db)
    router = AgentRouter()
    router.llm.enabled = False
    service = AgentService(conv_repo, emp_repo, sched_repo, tools, router=router)
    service.llm.enabled = False
    return service, emp_repo


def test_eval_case_a_explicit_force_leave_override(eval_service):
    service, emp_repo = eval_service
    employees = emp_repo.list()
    msg = "我知道 E01 周三请假，但就是让 E01 周三早班上班，强制生成。"
    route = AgentRouter._deterministic_route(msg, employees)
    assert route.force_generate is True
    assert route.employees == ["E01"]
    assert len(route.forced_assignments) == 1
    assert route.forced_assignments[0].employee_id == "E01"
    assert route.forced_assignments[0].day == Day.WED
    assert route.forced_assignments[0].shift == Shift.MORNING
    assert len(route.requested_overrides) == 1
    assert route.requested_overrides[0].rule_id == "R08"
    assert route.requested_overrides[0].employee_id == "E01"
    assert route.requested_overrides[0].day == Day.WED
    assert route.requested_overrides[0].shift == Shift.MORNING

    # Execute turn with AgentService
    conv = service.create_conversation("eval-workspace")
    turn = service.send_message(
        conversation_id=conv["conversation_id"],
        browser_workspace_id="eval-workspace",
        client_message_id="eval-case-a",
        content=msg,
        current_week_start=date(2026, 9, 21),
    )
    result = turn["schedule_result"]
    assert result["compliance_status"] == "authorized_violations"
    assert result["validation"]["passed"] is False
    assert result["confirmable"] is True
    assert len(result["authorized_violations"]) == 1
    v = result["authorized_violations"][0]
    assert v["rule_id"] == "R08"
    assert v["employee_id"] == "E01"
    assert v["day"] == "Wed"
    assert v["shift"] == "morning"

    reply = turn["assistant_message"]["content"]
    assert "强制生成" in reply
    assert "非标准合规" in reply or "规则冲突" in reply
    assert "R08" in reply
    assert "E01" in reply
    assert "周三" in reply
    assert "早班" in reply


def test_eval_case_b_conflict_request_no_force(eval_service):
    _, emp_repo = eval_service
    employees = emp_repo.list()
    msg = "E01 周三请假，尽量帮我排一下。"
    route = AgentRouter._deterministic_route(msg, employees)
    assert route.force_generate is False
    assert not route.requested_overrides


def test_eval_case_c_explicit_do_not_force(eval_service):
    _, emp_repo = eval_service
    employees = emp_repo.list()
    msg = "不要强制生成，看看有什么别的解决方案。"
    route = AgentRouter._deterministic_route(msg, employees)
    assert route.force_generate is False
    assert not route.requested_overrides


def test_eval_live_llm_force_evaluation(database, evaluation_output_dir):
    if (
        os.getenv("LIVE_AGENT_EVAL", "false").lower() != "true"
        or not os.getenv("LLM_API_KEY", "").strip()
    ):
        pytest.skip("LIVE_AGENT_EVAL is disabled or LLM_API_KEY is missing")

    from tests.evals.test_live_router_eval import evaluate_router
    evaluate_router({"name": "explicit_force_r08", "input": "我知道 E01 周三请假，但就是让 E01 周三早班上班，强制生成。", "kind": "force"},
                    database, evaluation_output_dir)
