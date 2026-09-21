"""Production CP-SAT schedule generation."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from ortools.sat.python import cp_model

from ..execution import current_execution, traced
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

    @traced("solver")
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

        if context.override_scopes and built.authorized_violation_terms:
            if status is not SolverStatus.OPTIMAL:
                return SolverResult(
                    status=SolverStatus.UNKNOWN,
                    message=(
                        "Exception count optimum was not proven; "
                        "retry with a larger solver time limit."
                    ),
                )
            # Force solving has three explicit phases: exception count,
            # exception magnitude, then ordinary business objectives.
            exception_count = sum(
                solver.Value(variable) for variable in built.authorized_violation_terms
            )
            built.model.Add(sum(built.authorized_violation_terms) == exception_count)
            built.model.ClearObjective()
            if built.authorized_magnitude_terms:
                built.model.Minimize(sum(built.authorized_magnitude_terms))
            magnitude_solver = self._configured_solver(context)
            magnitude_status = _solver_status(magnitude_solver.Solve(built.model))
            if magnitude_status is not SolverStatus.OPTIMAL:
                return SolverResult(
                    status=SolverStatus.UNKNOWN,
                    metrics={"solve_duration_seconds": magnitude_solver.WallTime()},
                    message="The Force solver could not preserve its authorized exception minimum.",
                )
            minimum_magnitude = sum(
                magnitude_solver.Value(variable) for variable in built.authorized_magnitude_terms
            )
            solver = magnitude_solver
            # The exception objectives are optimal; the business objective
            # still needs phase three before overall optimality can be claimed.
            status = SolverStatus.FEASIBLE
            if built.authorized_magnitude_terms:
                built.model.Add(sum(built.authorized_magnitude_terms) == minimum_magnitude)
            built.model.ClearObjective()
            weights = context.rules.objective
            objective = weights.preference_reward * sum(built.preference_terms)
            if built.workload_gap is not None:
                objective -= weights.workload_gap_penalty * built.workload_gap
            if built.change_terms:
                objective -= weights.schedule_change_penalty * sum(built.change_terms)
            objective -= (weights.preference_reward + weights.workload_gap_penalty + 1) * (
                sum(built.staffing_target_penalties) + sum(built.excess_staffing)
            )
            built.model.Maximize(objective)
            phase_three = self._configured_solver(context)
            phase_three_status = _solver_status(phase_three.Solve(built.model))
            if phase_three_status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
                solver = phase_three
                status = phase_three_status

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
        trace = current_execution.get()
        remaining = trace.remaining("solver") if trace else context.rules.max_time_seconds
        solver.parameters.max_time_in_seconds = min(context.rules.max_time_seconds, remaining)
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
        change_count = sum(solver.Value(term) for term in built.change_terms)
        workload_gap = solver.Value(built.workload_gap) if built.workload_gap is not None else 0
        return {
            "assignment_count": len(assignments),
            **built.facts.preference_metrics(assignments),
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
