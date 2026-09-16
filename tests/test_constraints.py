from __future__ import annotations

from datetime import timedelta

from ortools.sat.python import cp_model

from backend.app.models import (
    ChangeType,
    Day,
    HistoricalAssignment,
    HistoryStatus,
    RuleConfig,
    ScheduleChange,
    SchedulingContext,
    Shift,
    Skill,
    SolverStatus,
    WEEK_DAYS,
    SHIFTS,
)
from backend.app.solver import ConstraintBuilder, PrimarySolver


def _status(context: SchedulingContext, week_start) -> int:
    built = ConstraintBuilder().build(context, week_start=week_start)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 3
    solver.parameters.num_search_workers = 1
    return solver.Solve(built.model)


def _zero_coverage_rules(**overrides) -> RuleConfig:
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


def _forced(employee_id: str, day: Day, shift: Shift) -> ScheduleChange:
    return ScheduleChange(
        employee_id=employee_id,
        type=ChangeType.ASSIGN,
        day=day,
        shift=shift,
    )


def test_H01_one_shift_per_day(employee_factory, week_start):
    employee = employee_factory("E01")
    context = SchedulingContext(
        employees=[employee],
        rules=_zero_coverage_rules(),
        requested_changes=[
            _forced("E01", Day.MON, Shift.MORNING),
            _forced("E01", Day.MON, Shift.EVENING),
        ],
    )

    assert _status(context, week_start) == cp_model.INFEASIBLE


def _solved_default(default_context, week_start):
    result = PrimarySolver().solve(default_context, week_start=week_start)
    assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert result.schedule is not None
    return result.schedule


def test_R01_manager_coverage(default_context, week_start):
    schedule = _solved_default(default_context, week_start)
    employees = {employee.id: employee for employee in default_context.employees}
    for day in WEEK_DAYS:
        for shift in SHIFTS:
            assigned = [a for a in schedule.assignments if a.day is day and a.shift is shift]
            assert sum(Skill.MANAGER in employees[a.employee_id].skills for a in assigned) >= 1


def test_R02_beverage_coverage(default_context, week_start):
    schedule = _solved_default(default_context, week_start)
    employees = {employee.id: employee for employee in default_context.employees}
    for day in WEEK_DAYS:
        for shift in SHIFTS:
            assigned = [a for a in schedule.assignments if a.day is day and a.shift is shift]
            assert sum(Skill.BEVERAGE in employees[a.employee_id].skills for a in assigned) >= 2


def test_R03_cashier_coverage(default_context, week_start):
    schedule = _solved_default(default_context, week_start)
    employees = {employee.id: employee for employee in default_context.employees}
    for day in WEEK_DAYS:
        for shift in SHIFTS:
            assigned = [a for a in schedule.assignments if a.day is day and a.shift is shift]
            assert sum(Skill.CASHIER in employees[a.employee_id].skills for a in assigned) >= 1


def test_R04_min_staffing(default_context, week_start):
    schedule = _solved_default(default_context, week_start)
    for day in WEEK_DAYS:
        for shift in SHIFTS:
            assigned = {a.employee_id for a in schedule.assignments if a.day is day and a.shift is shift}
            assert len(assigned) >= default_context.rules.minimum_staff(day)


def test_R05_weekly_limit(default_context, week_start):
    schedule = _solved_default(default_context, week_start)
    for employee in default_context.employees:
        count = sum(a.employee_id == employee.id for a in schedule.assignments)
        assert count <= default_context.rules.max_shifts_per_week


def test_R06_consecutive_days(employee_factory, week_start):
    employee = employee_factory("E01")
    context = SchedulingContext(
        employees=[employee],
        rules=_zero_coverage_rules(max_consecutive_days=5),
        requested_changes=[_forced("E01", day, Shift.MORNING) for day in WEEK_DAYS[:6]],
    )

    assert _status(context, week_start) == cp_model.INFEASIBLE


def test_R06_cross_week_boundary(employee_factory, week_start):
    employee = employee_factory("E01")
    context = SchedulingContext(
        employees=[employee],
        rules=_zero_coverage_rules(max_consecutive_days=5),
        previous_days=[
            HistoricalAssignment(
                employee_id="E01",
                day=Day.SUN,
                shift=Shift.MORNING,
                assignment_date=week_start - timedelta(days=1),
            )
        ],
        requested_changes=[_forced("E01", day, Shift.MORNING) for day in WEEK_DAYS[:5]],
        history_status=HistoryStatus.AVAILABLE,
    )

    assert _status(context, week_start) == cp_model.INFEASIBLE


def test_R07_evening_to_morning(employee_factory, week_start):
    employee = employee_factory("E01")
    context = SchedulingContext(
        employees=[employee],
        rules=_zero_coverage_rules(),
        requested_changes=[
            _forced("E01", Day.MON, Shift.EVENING),
            _forced("E01", Day.TUE, Shift.MORNING),
        ],
    )

    assert _status(context, week_start) == cp_model.INFEASIBLE


def test_R07_cross_week_boundary(employee_factory, week_start):
    employee = employee_factory("E01")
    context = SchedulingContext(
        employees=[employee],
        rules=_zero_coverage_rules(),
        previous_days=[
            HistoricalAssignment(
                employee_id="E01",
                day=Day.SUN,
                shift=Shift.EVENING,
                assignment_date=week_start - timedelta(days=1),
            )
        ],
        requested_changes=[_forced("E01", Day.MON, Shift.MORNING)],
        history_status=HistoryStatus.AVAILABLE,
    )

    assert _status(context, week_start) == cp_model.INFEASIBLE


def test_R08_leave_and_availability(employee_factory, week_start):
    employee = employee_factory(
        "E01", available_days=[Day.MON], leave_days=[Day.MON]
    )
    context = SchedulingContext(
        employees=[employee],
        rules=_zero_coverage_rules(),
        requested_changes=[_forced("E01", Day.MON, Shift.MORNING)],
    )

    assert _status(context, week_start) == cp_model.INFEASIBLE


def test_R09_skill_source(employee_factory, week_start):
    role_only_manager = employee_factory("E01", role="manager", skills=[])
    context = SchedulingContext(
        employees=[role_only_manager],
        rules=_zero_coverage_rules(manager_per_shift=1),
    )

    result = PrimarySolver().solve(context, week_start=week_start)
    assert result.status is SolverStatus.INFEASIBLE
    assert result.schedule is None

