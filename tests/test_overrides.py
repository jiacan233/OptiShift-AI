from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from backend.app.models import Assignment, Day, ForceRequest, OverrideAuthorization, OverrideScope, Schedule, SchedulingContext, Shift, SolverStatus
from backend.app.models.domain import RuleConfig
from backend.app.repository import InvalidScheduleStateError
from backend.app.services.agent_router import AgentRouter
from backend.app.services.explanation import normalize_validation
from backend.app.services.scheduling_service import SchedulingService, SolverOutputError
from backend.app.solver.primary_solver import PrimarySolver
from backend.app.validator import RuleValidator
from backend.app.validator.authorization import classify_validation, constraint_id


def request_r08():
    return ForceRequest(
        authorization_reason="我知道 E01 周一请假，仍授权让 E01 周一早班上班",
        requested_overrides=[OverrideScope(rule_id="R08", employee_id="E01", day="Mon", shift="morning")],
        forced_assignments=[Assignment(employee_id="E01", day="Mon", shift="morning")],
    )


def test_force_leave_persists_and_confirms_without_changing_master_data(demo_service, week_start):
    demo_service.employees.update("E01", {"leave_days": [Day.MON]})
    before = demo_service.employees.list_with_revision()
    request = request_r08()
    draft = demo_service.force_generate(week_start=week_start, force_request=request, client_message_id="once")
    assert draft["compliance_status"] == "authorized_violations"
    assert draft["validation"]["passed"] is False
    assert draft["validation"]["valid"] is False
    assert draft["confirmable"] is True
    assert demo_service.employees.list_with_revision() == before
    assert request.forced_assignments[0].model_dump(mode="json") in draft["schedule"]["assignments"]
    violation = draft["authorized_violations"][0]
    assert (violation["rule_id"], violation["day"], violation["shift"], violation["employee_id"]) == ("R08", "Mon", "morning", "E01")
    assert violation["actual"] == "scheduled"
    assert violation["authorization_id"]
    retry = demo_service.force_generate(week_start=week_start, force_request=request, client_message_id="once")
    assert retry["schedule_id"] == draft["schedule_id"]
    reloaded = SchedulingService(demo_service.employees, demo_service.schedules)
    assert reloaded.validate_stored(draft["schedule_id"])["confirmable"] is True
    confirmed = reloaded.confirm(draft["schedule_id"], draft["version"])
    assert confirmed["lifecycle_status"] == "confirmed"
    assert confirmed["compliance_status"] == "authorized_violations"
    assert confirmed["authorized_violations"] == draft["authorized_violations"]
    assert len(demo_service.schedules.versions(draft["schedule_id"])) == 1


def test_force_prefers_compliant_strict_solution(demo_service, week_start):
    draft = demo_service.force_generate(week_start=week_start, force_request=ForceRequest(authorization_reason="强制生成"))
    assert draft["compliance_status"] == "compliant"
    assert draft["validation"]["passed"] is True
    assert draft["authorized_violations"] == []


@pytest.mark.parametrize("field", ["employee", "rules", "snapshot"])
def test_changed_constraints_reject_confirmation(demo_service, week_start, field):
    demo_service.employees.update("E01", {"leave_days": [Day.MON]})
    draft = demo_service.force_generate(week_start=week_start, force_request=request_r08())
    if field == "employee":
        demo_service.employees.update("E02", {"preferred_shift": Shift.EVENING})
    elif field == "rules":
        demo_service.context_builder.rules.manager_per_shift += 1
    else:
        from backend.app.models.orm import ScheduleRecord
        with demo_service.schedules.database.transaction() as session:
            record = session.get(ScheduleRecord, draft["schedule_id"])
            record.metadata_json = {**record.metadata_json, "user_forced_assignments": []}
    with pytest.raises((InvalidScheduleStateError, SolverOutputError)):
        demo_service.confirm(draft["schedule_id"], draft["version"])


@pytest.mark.parametrize("rule", ["H01", "R05", "R06", "R07", "R09"])
def test_protected_rules_cannot_be_authorized(rule):
    with pytest.raises(ValidationError):
        OverrideScope(rule_id=rule, employee_id="E01", day="Mon", shift="morning")


@pytest.mark.parametrize("mutation", [
    {"day": "Tue"}, {"shift": "evening"}, {"employee_id": "E02"},
])
def test_r08_authorization_is_exact(week_start, mutation):
    scope = request_r08().requested_overrides[0]
    auth = authorization(scope, week_start)
    raw = {"passed": False, "violations": [{"rule_id": "R08", "employee_id": "E01", "day": "Mon", "shift": "morning", "message": "unavailable", **mutation}]}
    result = classify_validation(raw, week_start, [auth])
    assert result["compliance_status"] == "invalid"
    assert result["confirmable"] is False


def authorization(scope, week):
    return OverrideAuthorization(
        **scope.model_dump(), constraint_id=constraint_id(week, scope.rule_id, scope.day.value, scope.shift.value, scope.employee_id),
        authorization_source="structured_user_action", source_conversation_id="api", source_message_id="msg", client_message_id="msg",
        target_week=week, base_schedule_id=None, base_version=None, scenario_revision=0, employee_revision=1,
        rules_fingerprint="rules", constraint_snapshot_hash="snapshot", reason="exact exception",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


@pytest.mark.parametrize("day,shift,actual,allowed", [("Mon", "morning", 1, True), ("Tue", "morning", 1, False), ("Mon", "evening", 1, False), ("Mon", "morning", 0, False)])
def test_coverage_matcher_bounds(week_start, day, shift, actual, allowed):
    auth = authorization(OverrideScope(rule_id="R01", day="Mon", shift="morning", allowed_shortage=1), week_start)
    raw = {"passed": False, "violations": [{"rule_id": "R01", "day": day, "shift": shift, "message": "shortage", "details": {"required": 2, "actual": actual}}]}
    result = classify_validation(raw, week_start, [auth])
    assert result["confirmable"] is allowed
    assert result["passed"] is False


def test_coverage_solver_only_relaxes_exact_slot(employee_factory, week_start):
    employees = [employee_factory("E01", available_days=[Day.MON])]
    rules = RuleConfig(manager_per_shift=1, beverage_per_shift=0, cashier_per_shift=0, weekday_min_staff=0, weekend_min_staff=0)
    scopes = [OverrideScope(rule_id="R01", day=day, shift=shift, allowed_shortage=1).model_dump(mode="json")
              for day in Day for shift in Shift if (day, shift) != (Day.MON, Shift.MORNING)]
    context = SchedulingContext(employees=employees, rules=rules, override_scopes=scopes)
    solved = PrimarySolver().solve(context, week_start=week_start)
    assert solved.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert Assignment(employee_id="E01", day="Mon", shift="morning") in solved.schedule.assignments
    raw = RuleValidator().validate(solved.schedule, employees, context=context)
    assert raw.valid is False
    assert len(raw.violations) == 13
    context.override_scopes = scopes[:-1]
    assert PrimarySolver().solve(context, week_start=week_start).status is SolverStatus.INFEASIBLE


@pytest.mark.parametrize("text", ["想办法排出来", "你看着排", "尽量排一下", "继续排", "生成吧", "不要强制生成", "不要强制安排 E01 周一早班上班", "do not force generate"])
def test_ambiguous_requests_never_authorize(text, balanced_employees):
    route = AgentRouter._deterministic_route(text, balanced_employees)
    assert not route.requested_overrides
    assert not route.force_generate


def test_exact_leave_route_preserves_assignment_and_never_repairs(balanced_employees):
    route = AgentRouter._deterministic_route("我知道 E01 周一请假，但就是让 E01 周一早班上班。", balanced_employees)
    assert route.force_generate
    assert route.forced_assignments == request_r08().forced_assignments
    assert route.requested_overrides == request_r08().requested_overrides
    assert route.changes == route.operations == []


def test_duplicate_assignments_remain_protected(balanced_employees, week_start):
    assignment = Assignment(employee_id="E01", day="Mon", shift="morning")
    schedule = Schedule(week_start=week_start, assignments=[assignment, assignment])
    result = classify_validation(normalize_validation(RuleValidator().validate(schedule, balanced_employees)), week_start)
    assert result["protected_violations"]
    assert result["confirmable"] is False


@pytest.mark.parametrize("text", ["E01 周一请假，但就是让他上班", "E01 周一请假，但就是让 E01 周一早班晚班都上班", "强制安排 E01 本周上班"])
def test_incomplete_forced_assignment_requires_clarification(text, balanced_employees):
    route = AgentRouter._deterministic_route(text, balanced_employees)
    assert route.intent.value == "clarification"
    assert not route.mutation_requested
    assert not route.force_generate


def test_stale_request_base_is_rejected(demo_service, week_start):
    from backend.app.repository import VersionConflictError
    base = demo_service.generate(week_start=week_start)
    demo_service.confirm(base["schedule_id"], base["version"])
    with pytest.raises(VersionConflictError):
        demo_service.force_generate(week_start=week_start, force_request=request_r08(), expected_base=(None, None))


def test_scenario_change_during_solve_rejects_save(demo_service, week_start):
    from backend.app.models import ScenarioPatch
    from backend.app.repository import ConversationRepository
    conversation = ConversationRepository(demo_service.schedules.database).create_conversation("force-test")
    conversation_id = conversation["conversation_id"]
    demo_service.employees.update("E01", {"leave_days": [Day.MON]})

    def change_scenario():
        demo_service.scenarios.upsert_patch(conversation_id, week_start, ScenarioPatch(employee_id="E02", days=[Day.TUE]))

    with pytest.raises(InvalidScheduleStateError):
        demo_service.force_generate(week_start=week_start, force_request=request_r08(),
                                    source_conversation_id=conversation_id, before_commit=change_scenario)
    assert demo_service.schedules.latest(status="draft", week_start=week_start) is None


def test_replay_cancelled_force_request_does_not_create_draft(demo_service, week_start):
    demo_service.employees.update("E01", {"leave_days": [Day.MON]})
    draft = demo_service.force_generate(week_start=week_start, force_request=request_r08(), client_message_id="cancelled-once")
    demo_service.cancel(draft["schedule_id"], draft["version"])
    retry = demo_service.force_generate(week_start=week_start, force_request=request_r08(), client_message_id="cancelled-once")
    assert retry["schedule_id"] == draft["schedule_id"]
    assert retry["lifecycle_status"] == "cancelled"
    assert demo_service.schedules.latest(status="draft", week_start=week_start) is None


def test_diagnostic_never_inherits_r08_override(demo_service, week_start):
    from backend.app.solver.diagnostic_solver import DiagnosticSolver
    demo_service.employees.update("E01", {"leave_days": [Day.MON]})
    request = request_r08()
    context = demo_service.context_builder.build(week_start, allow_history_bootstrap=True,
        user_forced_assignments=request.forced_assignments,
        override_scopes=[scope.model_dump(mode="json") for scope in request.requested_overrides])
    result = DiagnosticSolver().diagnose(context, week_start=week_start)
    assert result.preview_schedule is None
