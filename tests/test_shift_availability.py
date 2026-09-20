"""Exact availability exceptions must agree across facts, solve, and validation."""

from __future__ import annotations

import pytest

from backend.app.core import SchedulingFacts
from backend.app.models import (
    Assignment,
    ChangeType,
    Day,
    ObjectiveWeights,
    RuleConfig,
    Schedule,
    ScheduleChange,
    SchedulingContext,
    Shift,
    Skill,
    SolverStatus,
)
from backend.app.solver import PrimarySolver
from backend.app.solver.diagnostic_solver import capacity_precheck
from backend.app.validator import RuleValidator


def _change(kind, *, shift=None):
    return ScheduleChange(employee_id="E02", type=kind, day=Day.SUN, shift=shift)


def _context(employee_factory, changes, *, maximum=5):
    return SchedulingContext(
        employees=[employee_factory("E02")],
        requested_changes=changes,
        rules=RuleConfig(
            manager_per_shift=0,
            beverage_per_shift=0,
            cashier_per_shift=0,
            weekday_min_staff=0,
            weekend_min_staff=0,
            max_shifts_per_week=maximum,
            max_time_seconds=2,
            objective=ObjectiveWeights(
                preference_reward=5, workload_gap_penalty=0, schedule_change_penalty=0,
            ),
        ),
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_evening_availability_only_restores_evening_after_whole_day_unavailable(
    employee_factory, week_start, reverse,
):
    changes = [
        _change(ChangeType.UNAVAILABLE),
        _change(ChangeType.AVAILABLE, shift=Shift.EVENING),
        _change(ChangeType.PREFERENCE, shift=Shift.EVENING),
    ]
    if reverse:
        changes.reverse()
    context = _context(employee_factory, changes)
    facts = SchedulingFacts(context)
    assert not facts.employee_can_work("E02", Day.SUN, Shift.MORNING)
    assert facts.employee_can_work("E02", Day.SUN, Shift.EVENING)
    assert facts.employee_can_work("E02", Day.MON, Shift.MORNING)
    result = PrimarySolver().solve(context, week_start=week_start)

    assert result.status is SolverStatus.OPTIMAL
    assert result.schedule is not None
    sunday = [item for item in result.schedule.assignments if item.day is Day.SUN]
    assert [item.shift for item in sunday] == [Shift.EVENING]
    assert RuleValidator().validate(result.schedule, context.employees, context=context).valid

    illegal = Schedule(week_start=week_start, assignments=[
        Assignment(employee_id="E02", day=Day.SUN, shift=Shift.MORNING),
    ])
    validation = RuleValidator().validate(illegal, context.employees, context=context)
    assert not validation.valid
    assert [item.rule_id for item in validation.violations] == ["R08"]


def test_shift_availability_is_permission_not_a_required_assignment(employee_factory, week_start):
    context = _context(employee_factory, [
        _change(ChangeType.UNAVAILABLE),
        _change(ChangeType.AVAILABLE, shift=Shift.EVENING),
    ], maximum=0)
    result = PrimarySolver().solve(context, week_start=week_start)

    assert result.status is SolverStatus.OPTIMAL
    assert result.schedule is not None
    assert result.schedule.assignments == []


def test_shift_unavailability_does_not_remove_the_other_shift(employee_factory, week_start):
    context = _context(employee_factory, [
        _change(ChangeType.UNAVAILABLE, shift=Shift.EVENING),
        _change(ChangeType.ASSIGN, shift=Shift.MORNING),
    ])
    facts = SchedulingFacts(context)
    assert facts.employee_can_work("E02", Day.SUN, Shift.MORNING)
    assert not facts.employee_can_work("E02", Day.SUN, Shift.EVENING)
    result = PrimarySolver().solve(context, week_start=week_start)
    assert result.status is SolverStatus.OPTIMAL
    assert result.schedule is not None
    assert RuleValidator().validate(result.schedule, context.employees, context=context).valid


def test_evening_restoration_cannot_satisfy_sunday_morning_manager_requirement(
    employee_factory, week_start,
):
    employees = [employee_factory(f"E0{index}", skills=[Skill.MANAGER]) for index in range(1, 4)]
    context = SchedulingContext(
        employees=employees,
        requested_changes=[
            ScheduleChange(employee_id=item.id, type=ChangeType.UNAVAILABLE, day=Day.SUN)
            for item in employees
        ] + [_change(ChangeType.AVAILABLE, shift=Shift.EVENING)],
        rules=RuleConfig(
            manager_per_shift=1,
            beverage_per_shift=0,
            cashier_per_shift=0,
            weekday_min_staff=0,
            weekend_min_staff=0,
            max_shifts_per_week=7,
            max_consecutive_days=7,
            max_time_seconds=2,
        ),
    )
    shortages = capacity_precheck(context)
    assert [(item.rule_id, item.day, item.shift, item.available) for item in shortages] == [
        ("R01", Day.SUN, Shift.MORNING, 0),
    ]

    result = PrimarySolver().solve(context, week_start=week_start)

    assert result.status is SolverStatus.INFEASIBLE
    assert result.schedule is None
    assert result.diagnosis is not None
    assert any(
        item.rule_id == "R01" and item.day is Day.SUN and item.shift is Shift.MORNING
        for item in result.diagnosis.diagnostic_conflicts
    )


def test_h01_remains_hard_with_shift_availability_and_override_scope(
    employee_factory, week_start,
):
    context = _context(employee_factory, [
        _change(ChangeType.UNAVAILABLE),
        _change(ChangeType.AVAILABLE, shift=Shift.EVENING),
        _change(ChangeType.ASSIGN, shift=Shift.MORNING),
        _change(ChangeType.ASSIGN, shift=Shift.EVENING),
    ])
    context = context.model_copy(update={"override_scopes": [{
        "rule_id": "R08", "employee_id": "E02", "day": "Sun", "shift": "morning",
    }]})

    result = PrimarySolver().solve(context, week_start=week_start)
    assert result.status is SolverStatus.INFEASIBLE
    assert result.schedule is None
