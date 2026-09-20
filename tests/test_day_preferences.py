"""Verify dated soft preferences through objective coefficients and real solves."""

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
    SolverStatus,
)
from backend.app.solver import PrimarySolver
from backend.app.solver.constraint_builder import ConstraintBuilder
from backend.app.validator import RuleValidator


def _preference(day: Day, shift: Shift) -> ScheduleChange:
    return ScheduleChange(employee_id="E18", type=ChangeType.PREFERENCE, day=day, shift=shift)


def _context(employee_factory, changes, *, default=None, leave_days=None, maximum=2):
    # No staffing demand, workload reward, or schedule stability tradeoff:
    # the two requested slots must win strictly over every other assignment.
    return SchedulingContext(
        employees=[employee_factory("E18", preferred_shift=default, leave_days=leave_days)],
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


def _reward_coefficients(built):
    objective = built.model.Proto().objective
    coefficients = dict(zip(objective.vars, objective.coeffs, strict=True))
    return {
        key: coefficients.get(variable.Index(), 0) * objective.scaling_factor
        for key, variable in built.assignment_vars.items()
    }


@pytest.mark.parametrize("reverse", [False, True])
def test_date_preferences_have_exact_coefficients_and_solve_both_dates(
    employee_factory, week_start, reverse,
):
    changes = [
        _preference(Day.THU, Shift.MORNING),
        _preference(Day.SUN, Shift.EVENING),
    ]
    if reverse:
        changes.reverse()
    context = _context(employee_factory, changes)
    built = ConstraintBuilder().build(context, week_start=week_start)

    coefficients = _reward_coefficients(built)
    expected = {("E18", Day.THU, Shift.MORNING), ("E18", Day.SUN, Shift.EVENING)}
    assert {key for key, value in coefficients.items() if value} == expected
    assert coefficients[("E18", Day.THU, Shift.MORNING)] == 5
    assert coefficients[("E18", Day.SUN, Shift.EVENING)] == 5
    assert len(built.preference_terms) == 2

    result = PrimarySolver().solve(context, week_start=week_start)

    assert result.status is SolverStatus.OPTIMAL
    assert result.schedule is not None
    assert {
        (item.employee_id, item.day, item.shift) for item in result.schedule.assignments
    } == expected
    assert result.objective_value == 10
    assert result.metrics["preference_satisfied"] == 2
    assert result.metrics["preference_opportunities"] == 2
    assert result.metrics["preference_rate"] == 1
    assert result.metrics["day_preference_satisfied"] == 2
    assert RuleValidator().validate(result.schedule, context.employees, context=context).valid


def test_dated_preference_overrides_only_that_day_and_never_doubles_default_reward(
    employee_factory, week_start,
):
    context = _context(
        employee_factory,
        [
            _preference(Day.THU, Shift.MORNING),
            _preference(Day.SUN, Shift.EVENING),
            _preference(Day.SUN, Shift.EVENING),
        ],
        default=Shift.EVENING,
    )
    built = ConstraintBuilder().build(context, week_start=week_start)
    coefficients = _reward_coefficients(built)

    assert coefficients[("E18", Day.THU, Shift.MORNING)] == 5
    assert coefficients[("E18", Day.THU, Shift.EVENING)] == 0
    assert coefficients[("E18", Day.MON, Shift.MORNING)] == 0
    assert coefficients[("E18", Day.MON, Shift.EVENING)] == 5
    assert coefficients[("E18", Day.SUN, Shift.EVENING)] == 5
    assert len(built.preference_terms) == 7
    assert context.employees[0].preferred_shift is Shift.EVENING
    assert built.facts.policies["E18"].preferred_shift is Shift.EVENING


def test_unavailable_day_preference_is_unsatisfied_soft_goal_not_hard_assignment(
    employee_factory, week_start,
):
    context = _context(
        employee_factory,
        [_preference(Day.THU, Shift.MORNING)],
        leave_days=[Day.THU],
    )
    result = PrimarySolver().solve(context, week_start=week_start)

    assert result.status is SolverStatus.OPTIMAL
    assert result.schedule is not None
    assert not any(item.day is Day.THU for item in result.schedule.assignments)
    assert result.objective_value == 0
    assert result.metrics["preference_satisfied"] == 0
    assert result.metrics["preference_opportunities"] == 1
    assert result.metrics["preference_rate"] == 0
    assert result.metrics["day_preference_rate"] == 0
    assert RuleValidator().validate(result.schedule, context.employees, context=context).valid


def test_preference_metrics_use_the_dated_objective_scope(employee_factory):
    context = _context(
        employee_factory,
        [_preference(Day.THU, Shift.MORNING), _preference(Day.SUN, Shift.EVENING)],
    )
    metrics = SchedulingFacts(context).preference_metrics([
        Assignment(employee_id="E18", day=Day.THU, shift=Shift.MORNING),
        # A matching shift on another day must not satisfy the Sunday request.
        Assignment(employee_id="E18", day=Day.FRI, shift=Shift.EVENING),
    ])

    assert metrics["preference_satisfied"] == 1
    assert metrics["preference_opportunities"] == 2
    assert metrics["preference_rate"] == 0.5
    assert metrics["day_preference_satisfied"] == 1
    assert metrics["day_preference_opportunities"] == 2


def test_alternative_soft_preferences_do_not_bypass_h01(employee_factory, week_start):
    context = _context(employee_factory, [
        _preference(Day.THU, Shift.MORNING),
        _preference(Day.THU, Shift.EVENING),
    ])
    result = PrimarySolver().solve(context, week_start=week_start)

    assert result.status is SolverStatus.OPTIMAL
    assert result.schedule is not None
    assert sum(item.day is Day.THU for item in result.schedule.assignments) == 1
    assert result.objective_value == 5
    assert result.metrics["preference_opportunities"] == 1
    assert result.metrics["preference_satisfied"] == 1


def test_soft_preference_never_overrides_explicit_unassignment(employee_factory, week_start):
    context = _context(employee_factory, [
        _preference(Day.THU, Shift.MORNING),
        ScheduleChange(
            employee_id="E18", type=ChangeType.UNASSIGN, day=Day.THU, shift=Shift.MORNING,
        ),
    ])
    result = PrimarySolver().solve(context, week_start=week_start)

    assert result.status is SolverStatus.OPTIMAL
    assert result.schedule is not None
    assert not any(
        item.day is Day.THU and item.shift is Shift.MORNING
        for item in result.schedule.assignments
    )
    assert result.metrics["preference_rate"] == 0


def test_analysis_fallback_metrics_honor_stored_date_requests(
    database, repositories, employee_factory, week_start,
):
    from backend.app.repository import ScenarioRepository
    from backend.app.services.agent_tools import AgentTools
    from backend.app.services.scheduling_service import SchedulingService

    employees, schedules = repositories
    employees.create(employee_factory("E18"))
    schedules.previous_week_context(week_start, allow_bootstrap=True)
    changes = [_preference(Day.THU, Shift.MORNING), _preference(Day.SUN, Shift.EVENING)]
    context = _context(employee_factory, changes)
    schedule = Schedule(
        week_start=week_start,
        assignments=[Assignment(employee_id="E18", day=Day.THU, shift=Shift.MORNING)],
    )
    schedules.save_draft(
        schedule,
        lineage_id=schedule.schedule_id,
        base_schedule_id=None,
        base_version=None,
        validation={"passed": True},
        metadata={
            "requested_changes": [item.model_dump(mode="json") for item in changes],
            "rule_config": context.rules.model_dump(mode="json"),
        },
    )
    tool = AgentTools(
        employees, schedules, SchedulingService(employees, schedules), ScenarioRepository(database),
    )

    analysis = tool.analyze_schedule(target_week=week_start)

    assert analysis["metrics"]["preference_satisfied"] == 1
    assert analysis["metrics"]["preference_opportunities"] == 2
    assert analysis["metrics"]["preference_rate"] == 0.5
    assert analysis["metrics"]["day_preference_satisfied"] == 1
