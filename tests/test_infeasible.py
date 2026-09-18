from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from backend.app.models import (
    Assignment,
    ChangeType,
    Day,
    DiagnosticConflict,
    HistoricalAssignment,
    HistoryStatus,
    RuleConfig,
    ScheduleChange,
    SchedulingContext,
    Shift,
    Skill,
    SolverStatus,
    WEEK_DAYS,
)
from backend.app.solver import (
    DiagnosticSolver,
    PrimarySolver,
    candidate_blocking_analysis,
    capacity_precheck,
)
from backend.app.services.scheduling_service import SchedulingService


def _rules(**overrides):
    values = {
        "manager_per_shift": 0,
        "beverage_per_shift": 0,
        "cashier_per_shift": 0,
        "weekday_min_staff": 0,
        "weekend_min_staff": 0,
        "max_shifts_per_week": 7,
        "max_consecutive_days": 7,
        "max_time_seconds": 3,
        "num_search_workers": 1,
    }
    values.update(overrides)
    return RuleConfig(**values)


def _assign(employee_id, day, shift=Shift.MORNING):
    return ScheduleChange(
        employee_id=employee_id, type=ChangeType.ASSIGN, day=day, shift=shift
    )


def test_no_manager_available_returns_structured_diagnosis(employee_factory, week_start):
    context = SchedulingContext(
        employees=[employee_factory("E01", skills=[Skill.BEVERAGE, Skill.CASHIER])],
        rules=_rules(manager_per_shift=1),
    )

    result = PrimarySolver().solve(context, week_start=week_start)

    assert result.status is SolverStatus.INFEASIBLE
    assert result.schedule is None
    assert result.diagnosis is not None
    assert len(result.diagnosis.capacity_conflicts) == 14
    assert all(item.rule_id == "R01" and item.available == 0 for item in result.diagnosis.capacity_conflicts)
    assert result.diagnosis.generated_valid_schedule is False


def test_beverage_shortage_is_reported(employee_factory):
    context = SchedulingContext(
        employees=[employee_factory("E01", skills=[Skill.BEVERAGE])],
        rules=_rules(beverage_per_shift=2),
    )

    conflicts = capacity_precheck(context)

    assert len(conflicts) == 14
    assert all(item.rule_id == "R02" and item.shortage == 1 for item in conflicts)


def test_weekend_total_staffing_shortage_is_reported(employee_factory):
    context = SchedulingContext(
        employees=[employee_factory(f"E{index:02d}") for index in range(1, 6)],
        rules=_rules(weekend_min_staff=6),
    )

    conflicts = capacity_precheck(context)

    assert {(item.day, item.shift) for item in conflicts} == {
        (day, shift)
        for day in (Day.SAT, Day.SUN)
        for shift in (Shift.MORNING, Shift.EVENING)
    }
    assert all(item.rule_id == "R04" and item.shortage == 1 for item in conflicts)


def test_R06_and_R07_jointly_block_otherwise_qualified_candidate(
    employee_factory, week_start
):
    employee = employee_factory("E01", skills=[Skill.MANAGER])
    context = SchedulingContext(
        employees=[employee],
        rules=_rules(max_consecutive_days=4),
    )
    candidate_schedule = [
        Assignment(
            employee_id="E01",
            day=day,
            shift=Shift.EVENING if day is Day.SAT else Shift.MORNING,
        )
        for day in (Day.WED, Day.THU, Day.FRI, Day.SAT)
    ]
    conflict = DiagnosticConflict(
        rule_id="R01",
        day=Day.SUN,
        shift=Shift.MORNING,
        required=1,
        actual=0,
        shortage=1,
    )

    blocking = candidate_blocking_analysis(
        context, [conflict], candidate_schedule, week_start=week_start
    )

    assert len(blocking) == 1
    assert {reason.rule_id for reason in blocking[0].reasons} >= {"R06", "R07"}


@pytest.mark.parametrize(
    "changes,rules,employee_kwargs,history",
    [
        (
            [_assign("E01", Day.MON, Shift.MORNING), _assign("E01", Day.MON, Shift.EVENING)],
            _rules(),
            {},
            [],
        ),
        (
            [_assign("E01", day) for day in WEEK_DAYS[:6]],
            _rules(max_shifts_per_week=5),
            {},
            [],
        ),
        (
            [_assign("E01", day) for day in WEEK_DAYS[:6]],
            _rules(max_consecutive_days=5),
            {},
            [],
        ),
        (
            [_assign("E01", Day.MON, Shift.EVENING), _assign("E01", Day.TUE, Shift.MORNING)],
            _rules(),
            {},
            [],
        ),
        (
            [_assign("E01", Day.MON)],
            _rules(),
            {"leave_days": [Day.MON]},
            [],
        ),
    ],
    ids=["H01", "R05", "R06", "R07", "R08"],
)
def test_diagnostic_solver_never_relaxes_retained_hard_rules(
    employee_factory, week_start, changes, rules, employee_kwargs, history
):
    context = SchedulingContext(
        employees=[employee_factory("E01", **employee_kwargs)],
        rules=rules,
        requested_changes=changes,
        previous_days=history,
        history_status=HistoryStatus.AVAILABLE if history else HistoryStatus.KNOWN_EMPTY,
    )

    diagnosis = DiagnosticSolver().diagnose(context, week_start=week_start)

    assert diagnosis.diagnostic_status is SolverStatus.INFEASIBLE
    assert diagnosis.generated_valid_schedule is False


def test_diagnostic_solver_does_not_invent_skills_or_employees(employee_factory, week_start):
    employee = employee_factory("E01", role="manager", skills=[])
    context = SchedulingContext(
        employees=[employee], rules=_rules(manager_per_shift=1)
    )

    diagnosis = DiagnosticSolver().diagnose(context, week_start=week_start)

    assert diagnosis.diagnostic_status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert diagnosis.diagnostic_conflicts
    assert all(item.rule_id == "R01" and item.actual == 0 for item in diagnosis.diagnostic_conflicts)
    assert diagnosis.blocking_candidates == []


def test_infeasible_service_response_is_never_persisted(demo_service, week_start):
    managers = [
        employee.id
        for employee in demo_service.employees.list()
        if Skill.MANAGER in employee.skills
    ]
    changes = [
        ScheduleChange(employee_id=employee_id, type=ChangeType.LEAVE, day=Day.SUN)
        for employee_id in managers
    ]

    result = demo_service.generate(week_start=week_start, changes=changes)

    assert result["status"] == "infeasible"
    assert result["generated_valid_schedule"] is False
    assert {"status", "conflicts", "blocking_candidates", "diagnosis", "message", "generated_valid_schedule"} <= result.keys()
    assert any(item["rule_id"] == "R01" and item["day"] == "Sun" for item in result["conflicts"])
    assert demo_service.schedules.latest(status="draft") is None


def test_infeasible_response_contract_is_complete_without_diagnosis():
    result = SchedulingService._infeasible_response(
        SimpleNamespace(diagnosis=None, message="No valid schedule exists.")
    )

    assert result == {
        "status": "infeasible",
        "conflicts": [],
        "blocking_candidates": [],
        "diagnosis": None,
        "message": "No valid schedule exists.",
        "generated_valid_schedule": False,
    }
