from __future__ import annotations

from backend.app.models import (
    ChangeType,
    Day,
    ScheduleChange,
    SchedulingContext,
    SolverStatus,
)
from backend.app.solver import PrimarySolver
from backend.app.validator import RuleValidator


def _keys(schedule):
    return {
        (assignment.employee_id, assignment.day, assignment.shift)
        for assignment in schedule.assignments
    }


def test_solver_generates_independently_valid_schedule(default_context, week_start):
    result = PrimarySolver().solve(
        default_context,
        week_start=week_start,
        schedule_id="solver-draft",
        version=3,
        parent_schedule_id="confirmed-v2",
    )

    assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert result.schedule is not None
    assert result.schedule.schedule_id == "solver-draft"
    assert result.schedule.version == 3
    assert result.schedule.parent_schedule_id == "confirmed-v2"
    validation = RuleValidator().validate(
        result.schedule,
        default_context.employees,
        context=default_context,
    )
    assert validation.valid
    assert validation.passed_count == validation.total_count == 10


def test_solver_is_deterministic_for_fixed_seed(default_context, week_start):
    first = PrimarySolver().solve(default_context, week_start=week_start)
    second = PrimarySolver().solve(default_context, week_start=week_start)

    assert first.schedule is not None and second.schedule is not None
    assert _keys(first.schedule) == _keys(second.schedule)
    assert first.objective_value == second.objective_value


def test_solver_respects_temporary_leave(default_context, week_start):
    employee_id = default_context.employees[0].id
    context = default_context.model_copy(
        update={
            "requested_changes": [
                ScheduleChange(
                    employee_id=employee_id,
                    type=ChangeType.LEAVE,
                    day=Day.FRI,
                )
            ]
        }
    )

    result = PrimarySolver().solve(context, week_start=week_start)

    assert result.schedule is not None
    assert not any(
        item.employee_id == employee_id and item.day is Day.FRI
        for item in result.schedule.assignments
    )
    assert RuleValidator().validate(
        result.schedule, context.employees, context=context
    ).valid


def test_solver_reports_objective_metrics(default_context, week_start):
    result = PrimarySolver().solve(default_context, week_start=week_start)

    assert result.schedule is not None
    assert result.metrics["assignment_count"] == len(result.schedule.assignments)
    assert 0 <= result.metrics["preference_rate"] <= 1
    assert result.metrics["preference_satisfied"] <= result.metrics["preference_opportunities"]
    assert result.metrics["workload_gap"] >= 0
    assert result.metrics["change_count"] == 0


def test_minimal_perturbation_keeps_unchanged_feasible_base(default_context, week_start):
    base_result = PrimarySolver().solve(default_context, week_start=week_start)
    assert base_result.schedule is not None
    replan_context = SchedulingContext(
        base_schedule=base_result.schedule,
        employees=default_context.employees,
        rules=default_context.rules,
        minimize_changes=True,
    )

    replanned = PrimarySolver().solve(replan_context, week_start=week_start)

    assert replanned.schedule is not None
    assert replanned.metrics["change_count"] == 0
    assert _keys(replanned.schedule) == _keys(base_result.schedule)

