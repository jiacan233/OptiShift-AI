"""Three-level, explanation-only diagnosis for infeasible schedules."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from ortools.sat.python import cp_model

from ..core import SchedulingFacts
from ..models import (
    Assignment,
    BlockingReason,
    CandidateBlocking,
    CapacityConflict,
    Day,
    DiagnosisResult,
    DiagnosticConflict,
    SchedulingContext,
    Shift,
    Skill,
    SolverStatus,
    WEEK_DAYS,
    SHIFTS,
)
from .constraint_builder import ConstraintBuilder
from .primary_solver import _solver_status


_COVERAGE_SKILL: dict[str, Skill | None] = {
    "R01": Skill.MANAGER,
    "R02": Skill.BEVERAGE,
    "R03": Skill.CASHIER,
    "R04": None,
}


def capacity_precheck(context: SchedulingContext) -> list[CapacityConflict]:
    """Find obvious local capacity shortages; passing does not prove feasibility."""

    facts = SchedulingFacts(context)
    rules = context.rules
    requirements = (
        ("R01", Skill.MANAGER, rules.manager_per_shift, "manager"),
        ("R02", Skill.BEVERAGE, rules.beverage_per_shift, "beverage"),
        ("R03", Skill.CASHIER, rules.cashier_per_shift, "cashier"),
    )
    conflicts: list[CapacityConflict] = []
    for day in WEEK_DAYS:
        available = [
            employee
            for employee in context.employees
            if facts.employee_can_work(employee.id, day)
        ]
        for shift in SHIFTS:
            for rule_id, skill, required, label in requirements:
                actual = sum(skill in employee.skills for employee in available)
                if actual < required:
                    conflicts.append(
                        CapacityConflict(
                            rule_id=rule_id,
                            day=day,
                            shift=shift,
                            required=required,
                            available=actual,
                            shortage=required - actual,
                            message=f"Only {actual} available {label} qualified staff for a requirement of {required}.",
                        )
                    )
            required_staff = rules.minimum_staff(day)
            if len(available) < required_staff:
                conflicts.append(
                    CapacityConflict(
                        rule_id="R04",
                        day=day,
                        shift=shift,
                        required=required_staff,
                        available=len(available),
                        shortage=required_staff - len(available),
                        message=f"Only {len(available)} employees are available for a requirement of {required_staff}.",
                    )
                )
    return conflicts


class DiagnosticSolver:
    """Relax only R01-R04 while retaining H01 and R05-R09 as hard rules."""

    def __init__(self, constraint_builder: ConstraintBuilder | None = None) -> None:
        self.constraint_builder = constraint_builder or ConstraintBuilder()

    def diagnose(
        self,
        context: SchedulingContext,
        *,
        week_start: date,
        primary_status: SolverStatus = SolverStatus.INFEASIBLE,
    ) -> DiagnosisResult:
        capacity_conflicts = capacity_precheck(context)
        built = self.constraint_builder.build(
            context, week_start=week_start, diagnostic=True
        )
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = context.rules.max_time_seconds
        solver.parameters.random_seed = context.rules.random_seed
        solver.parameters.num_search_workers = context.rules.num_search_workers
        cp_status = solver.Solve(built.model)
        diagnostic_status = _solver_status(cp_status)

        diagnostic_conflicts: list[DiagnosticConflict] = []
        blocking_candidates: list[CandidateBlocking] = []
        if diagnostic_status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
            assignments = [
                Assignment(employee_id=employee_id, day=day, shift=shift)
                for (employee_id, day, shift), variable in built.assignment_vars.items()
                if solver.Value(variable)
            ]
            for (rule_id, day, shift), slack in built.staffing_slacks.items():
                shortage = solver.Value(slack)
                if shortage <= 0:
                    continue
                required = _required_count(context, rule_id, day)
                actual = _actual_coverage(context, assignments, rule_id, day, shift)
                diagnostic_conflicts.append(
                    DiagnosticConflict(
                        rule_id=rule_id,  # type: ignore[arg-type]
                        day=day,
                        shift=shift,
                        required=required,
                        actual=actual,
                        shortage=max(shortage, required - actual),
                    )
                )
            blocking_candidates = candidate_blocking_analysis(
                context,
                diagnostic_conflicts,
                candidate_schedule=assignments,
                week_start=week_start,
            )

        summary = _diagnostic_summary(
            capacity_conflicts, diagnostic_status, diagnostic_conflicts
        )
        return DiagnosisResult(
            primary_status=primary_status,
            capacity_conflicts=capacity_conflicts,
            diagnostic_status=diagnostic_status,
            diagnostic_conflicts=diagnostic_conflicts,
            blocking_candidates=blocking_candidates,
            summary=summary,
        )


def candidate_blocking_analysis(
    context: SchedulingContext,
    conflicts: list[DiagnosticConflict],
    candidate_schedule: list[Assignment] | None = None,
    *,
    week_start: date | None = None,
) -> list[CandidateBlocking]:
    """Explain why master-data candidates cannot fill a diagnosed shortage."""

    assignments = candidate_schedule or []
    facts = SchedulingFacts(context, week_start)
    assignment_keys = {
        (assignment.employee_id, assignment.day, assignment.shift)
        for assignment in assignments
    }
    workdays = {
        (assignment.employee_id, assignment.day) for assignment in assignments
    }
    weekly_counts: dict[str, int] = defaultdict(int)
    for employee_id, _day, _shift in assignment_keys:
        weekly_counts[employee_id] += 1

    results: list[CandidateBlocking] = []
    for conflict in conflicts:
        required_skill = _COVERAGE_SKILL[conflict.rule_id]
        candidates = [
            employee
            for employee in context.employees
            if required_skill is None or required_skill in employee.skills
        ]
        for employee in candidates:
            target = (employee.id, conflict.day, conflict.shift)
            if target in assignment_keys:
                continue
            reasons: list[BlockingReason] = []
            policy = facts.policies[employee.id]
            if not policy.can_work(conflict.day):
                reasons.append(
                    BlockingReason(
                        rule_id="R08",
                        message="Employee is on leave or unavailable on this day.",
                        details={"day": conflict.day.value},
                    )
                )
            other_shifts = [
                shift
                for shift in SHIFTS
                if shift is not conflict.shift
                and (employee.id, conflict.day, shift) in assignment_keys
            ]
            if other_shifts:
                reasons.append(
                    BlockingReason(
                        rule_id="H01",
                        message="Employee already works the other shift on this day.",
                        details={"assigned_shift": other_shifts[0].value},
                    )
                )
            if weekly_counts[employee.id] >= context.rules.max_shifts_per_week:
                reasons.append(
                    BlockingReason(
                        rule_id="R05",
                        message="Employee already reached the weekly shift limit.",
                        details={
                            "assigned": weekly_counts[employee.id],
                            "maximum": context.rules.max_shifts_per_week,
                        },
                    )
                )
            if _would_break_r06(
                employee.id, conflict.day, workdays, facts, context.rules.max_consecutive_days
            ):
                reasons.append(
                    BlockingReason(
                        rule_id="R06",
                        message="Adding this shift would exceed the consecutive-day limit.",
                        details={"maximum": context.rules.max_consecutive_days},
                    )
                )
            r07_reason = _r07_block(
                employee.id, conflict.day, conflict.shift, assignment_keys, facts
            )
            if r07_reason is not None:
                reasons.append(r07_reason)
            if (conflict.day, conflict.shift) in policy.forced_unassignments:
                reasons.append(
                    BlockingReason(
                        rule_id="REQUEST",
                        message="The request explicitly removes this assignment.",
                    )
                )
            if not reasons:
                reasons.append(
                    BlockingReason(
                        rule_id="GLOBAL_CONSTRAINT_INTERACTION",
                        message="Adding this employee requires other assignment changes that violate a retained hard rule.",
                    )
                )
            results.append(
                CandidateBlocking(
                    employee_id=employee.id,
                    day=conflict.day,
                    shift=conflict.shift,
                    coverage_rule_id=conflict.rule_id,
                    reasons=reasons,
                )
            )
    return results


def _required_count(context: SchedulingContext, rule_id: str, day: Day) -> int:
    return {
        "R01": context.rules.manager_per_shift,
        "R02": context.rules.beverage_per_shift,
        "R03": context.rules.cashier_per_shift,
        "R04": context.rules.minimum_staff(day),
    }[rule_id]


def _actual_coverage(
    context: SchedulingContext,
    assignments: list[Assignment],
    rule_id: str,
    day: Day,
    shift: Shift,
) -> int:
    assigned_ids = {
        assignment.employee_id
        for assignment in assignments
        if assignment.day is day and assignment.shift is shift
    }
    required_skill = _COVERAGE_SKILL[rule_id]
    if required_skill is None:
        return len(assigned_ids)
    employee_by_id = {employee.id: employee for employee in context.employees}
    return sum(required_skill in employee_by_id[employee_id].skills for employee_id in assigned_ids)


def _would_break_r06(
    employee_id: str,
    target_day: Day,
    workdays: set[tuple[str, Day]],
    facts: SchedulingFacts,
    maximum: int,
) -> bool:
    previous = facts.previous_work_vector(employee_id)
    current = [
        int(day is target_day or (employee_id, day) in workdays) for day in WEEK_DAYS
    ]
    timeline = previous + current
    window_length = maximum + 1
    target_index = len(previous) + WEEK_DAYS.index(target_day)
    for start in range(max(0, target_index - maximum), min(target_index, len(timeline) - window_length) + 1):
        if sum(timeline[start : start + window_length]) > maximum:
            return True
    return False


def _r07_block(
    employee_id: str,
    day: Day,
    shift: Shift,
    assignment_keys: set[tuple[str, Day, Shift]],
    facts: SchedulingFacts,
) -> BlockingReason | None:
    day_index = WEEK_DAYS.index(day)
    if shift is Shift.MORNING:
        if day is Day.MON and facts.previous_sunday_evening(employee_id):
            return BlockingReason(
                rule_id="R07",
                message="The previous confirmed Sunday evening blocks Monday morning.",
            )
        if day_index > 0:
            previous_day = WEEK_DAYS[day_index - 1]
            if (employee_id, previous_day, Shift.EVENING) in assignment_keys:
                return BlockingReason(
                    rule_id="R07",
                    message="Employee works the preceding evening shift.",
                    details={"previous_day": previous_day.value},
                )
    if shift is Shift.EVENING and day_index < len(WEEK_DAYS) - 1:
        next_day = WEEK_DAYS[day_index + 1]
        if (employee_id, next_day, Shift.MORNING) in assignment_keys:
            return BlockingReason(
                rule_id="R07",
                message="Employee works the following morning shift.",
                details={"next_day": next_day.value},
            )
    return None


def _diagnostic_summary(
    capacity_conflicts: list[CapacityConflict],
    status: SolverStatus,
    diagnostic_conflicts: list[DiagnosticConflict],
) -> str:
    if status not in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
        return (
            "Even the diagnostic model is infeasible while H01 and R05-R09 remain hard; "
            "the conflict is outside relaxable staffing coverage."
        )
    if diagnostic_conflicts:
        shortage = sum(conflict.shortage for conflict in diagnostic_conflicts)
        return (
            f"The minimum explanation requires {shortage} total staffing or skill coverage "
            f"units across {len(diagnostic_conflicts)} rule-slot conflicts."
        )
    if capacity_conflicts:
        return "Local capacity checks found shortages, although the diagnostic model filled all coverage."
    return "No R01-R04 shortage explains the failure; inspect retained hard-rule interactions."


def diagnose_infeasibility(
    context: SchedulingContext,
    *,
    week_start: date,
) -> DiagnosisResult:
    return DiagnosticSolver().diagnose(context, week_start=week_start)
