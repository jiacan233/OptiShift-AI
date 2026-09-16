"""Production CP-SAT schedule generation."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from ortools.sat.python import cp_model

from ..models import (
    Assignment,
    Schedule,
    ScheduleStatus,
    SchedulingContext,
    SolverResult,
    SolverStatus,
)
from .constraint_builder import BuiltSchedulingModel, ConstraintBuilder


class PrimarySolver:
    def __init__(self, constraint_builder: ConstraintBuilder | None = None) -> None:
        self.constraint_builder = constraint_builder or ConstraintBuilder()

    def solve(
        self,
        context: SchedulingContext,
        *,
        week_start: date,
        schedule_id: str | None = None,
        version: int = 1,
        parent_schedule_id: str | None = None,
    ) -> SolverResult:
        built = self.constraint_builder.build(context, week_start=week_start)
        solver = self._configured_solver(context)
        cp_status = solver.Solve(built.model)
        status = _solver_status(cp_status)

        if status is SolverStatus.INFEASIBLE:
            from .diagnostic_solver import diagnose_infeasibility

            diagnosis = diagnose_infeasibility(context, week_start=week_start)
            return SolverResult(
                status=status,
                diagnosis=diagnosis,
                metrics={"solve_duration_seconds": solver.WallTime()},
                message="No valid schedule exists for the supplied context.",
            )

        if status not in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
            return SolverResult(
                status=status,
                metrics={"solve_duration_seconds": solver.WallTime()},
                message="The solver did not return a usable schedule.",
            )

        assignments = self._extract_assignments(built, solver)
        resolved_schedule_id = schedule_id or f"sch_{uuid4().hex[:12]}"
        schedule = Schedule(
            schedule_id=resolved_schedule_id,
            version=version,
            parent_schedule_id=parent_schedule_id,
            status=ScheduleStatus.DRAFT,
            week_start=week_start,
            assignments=assignments,
        )
        metrics = self._metrics(context, built, solver, assignments)
        return SolverResult(
            status=status,
            schedule=schedule,
            objective_value=solver.ObjectiveValue(),
            metrics=metrics,
        )

    @staticmethod
    def _configured_solver(context: SchedulingContext) -> cp_model.CpSolver:
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = context.rules.max_time_seconds
        solver.parameters.random_seed = context.rules.random_seed
        solver.parameters.num_search_workers = context.rules.num_search_workers
        return solver

    @staticmethod
    def _extract_assignments(
        built: BuiltSchedulingModel, solver: cp_model.CpSolver
    ) -> list[Assignment]:
        return [
            Assignment(employee_id=employee_id, day=day, shift=shift)
            for (employee_id, day, shift), variable in built.assignment_vars.items()
            if solver.Value(variable)
        ]

    @staticmethod
    def _metrics(
        context: SchedulingContext,
        built: BuiltSchedulingModel,
        solver: cp_model.CpSolver,
        assignments: list[Assignment],
    ) -> dict[str, int | float | str]:
        preferred = sum(solver.Value(term) for term in built.preference_terms)
        employees_with_preference = {
            employee.id
            for employee in context.employees
            if built.facts.policies[employee.id].preferred_shift is not None
        }
        preferred_opportunities = sum(
            1 for assignment in assignments if assignment.employee_id in employees_with_preference
        )
        change_count = sum(solver.Value(term) for term in built.change_terms)
        workload_gap = solver.Value(built.workload_gap) if built.workload_gap is not None else 0
        return {
            "assignment_count": len(assignments),
            "preference_satisfied": preferred,
            "preference_opportunities": preferred_opportunities,
            "preference_rate": (
                preferred / preferred_opportunities if preferred_opportunities else 1.0
            ),
            "workload_gap": workload_gap,
            "change_count": change_count,
            "solve_duration_seconds": solver.WallTime(),
            "history_status": context.history_status.value,
        }


def _solver_status(cp_status: int) -> SolverStatus:
    return {
        cp_model.OPTIMAL: SolverStatus.OPTIMAL,
        cp_model.FEASIBLE: SolverStatus.FEASIBLE,
        cp_model.INFEASIBLE: SolverStatus.INFEASIBLE,
        cp_model.MODEL_INVALID: SolverStatus.MODEL_INVALID,
        cp_model.UNKNOWN: SolverStatus.UNKNOWN,
    }.get(cp_status, SolverStatus.UNKNOWN)


def solve_schedule(
    context: SchedulingContext,
    *,
    week_start: date,
    schedule_id: str | None = None,
    version: int = 1,
    parent_schedule_id: str | None = None,
) -> SolverResult:
    return PrimarySolver().solve(
        context,
        week_start=week_start,
        schedule_id=schedule_id,
        version=version,
        parent_schedule_id=parent_schedule_id,
    )
