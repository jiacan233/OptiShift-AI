"""CP-SAT model construction shared by primary and diagnostic solvers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ortools.sat.python import cp_model

from ..core import SchedulingFacts
from ..models import Day, SchedulingContext, Shift, Skill, WEEK_DAYS, SHIFTS


VariableKey = tuple[str, Day, Shift]
CoverageKey = tuple[str, Day, Shift]


@dataclass
class BuiltSchedulingModel:
    model: cp_model.CpModel
    assignment_vars: dict[VariableKey, cp_model.IntVar]
    workday_vars: dict[tuple[str, Day], cp_model.IntVar]
    workload_vars: dict[str, cp_model.IntVar]
    staffing_slacks: dict[CoverageKey, cp_model.IntVar]
    facts: SchedulingFacts
    preference_terms: list[cp_model.IntVar]
    change_terms: list[cp_model.IntVar]
    workload_gap: cp_model.IntVar | None


class ConstraintBuilder:
    """Build the hard constraints once so diagnosis cannot silently diverge."""

    def build(
        self,
        context: SchedulingContext,
        *,
        week_start: date,
        diagnostic: bool = False,
    ) -> BuiltSchedulingModel:
        model = cp_model.CpModel()
        facts = SchedulingFacts(context, week_start)
        employee_ids = [employee.id for employee in context.employees]
        rules = context.rules

        assignment_vars: dict[VariableKey, cp_model.IntVar] = {}
        for employee_id in employee_ids:
            for day in WEEK_DAYS:
                for shift in SHIFTS:
                    assignment_vars[(employee_id, day, shift)] = model.NewBoolVar(
                        f"x_{employee_id}_{day.value}_{shift.value}"
                    )

        # H01: a person may work at most one shift per day.
        workday_vars: dict[tuple[str, Day], cp_model.IntVar] = {}
        for employee_id in employee_ids:
            for day in WEEK_DAYS:
                day_vars = [assignment_vars[(employee_id, day, shift)] for shift in SHIFTS]
                model.Add(sum(day_vars) <= 1)
                workday = model.NewBoolVar(f"works_{employee_id}_{day.value}")
                model.Add(workday == sum(day_vars))
                workday_vars[(employee_id, day)] = workday

        # R08 and explicit, validated request changes.
        for employee_id in employee_ids:
            policy = facts.policies[employee_id]
            for day in WEEK_DAYS:
                if not policy.can_work(day):
                    for shift in SHIFTS:
                        model.Add(assignment_vars[(employee_id, day, shift)] == 0)
            for day, shift in policy.forced_assignments:
                model.Add(assignment_vars[(employee_id, day, shift)] == 1)
            for day, shift in policy.forced_unassignments:
                model.Add(assignment_vars[(employee_id, day, shift)] == 0)

        # R01-R04.  Only the diagnostic model receives shortage slack.
        staffing_slacks: dict[CoverageKey, cp_model.IntVar] = {}
        coverage_specs = (
            ("R01", Skill.MANAGER, rules.manager_per_shift),
            ("R02", Skill.BEVERAGE, rules.beverage_per_shift),
            ("R03", Skill.CASHIER, rules.cashier_per_shift),
        )
        for day in WEEK_DAYS:
            for shift in SHIFTS:
                for rule_id, skill, required in coverage_specs:
                    qualified = [
                        assignment_vars[(employee.id, day, shift)]
                        for employee in context.employees
                        if skill in employee.skills
                    ]
                    self._add_coverage(
                        model,
                        staffing_slacks,
                        (rule_id, day, shift),
                        qualified,
                        required,
                        diagnostic,
                    )
                all_staff = [assignment_vars[(employee_id, day, shift)] for employee_id in employee_ids]
                self._add_coverage(
                    model,
                    staffing_slacks,
                    ("R04", day, shift),
                    all_staff,
                    rules.minimum_staff(day),
                    diagnostic,
                )

        # R05: weekly cap remains hard in both primary and diagnostic models.
        workload_vars: dict[str, cp_model.IntVar] = {}
        for employee_id in employee_ids:
            workload = model.NewIntVar(
                0, rules.max_shifts_per_week, f"workload_{employee_id}"
            )
            model.Add(
                workload
                == sum(
                    assignment_vars[(employee_id, day, shift)]
                    for day in WEEK_DAYS
                    for shift in SHIFTS
                )
            )
            workload_vars[employee_id] = workload

        # R06: include all windows crossing the preceding confirmed boundary.
        window_length = rules.max_consecutive_days + 1
        for employee_id in employee_ids:
            previous = facts.previous_work_vector(employee_id)
            timeline: list[int | cp_model.IntVar] = previous + [
                workday_vars[(employee_id, day)] for day in WEEK_DAYS
            ]
            first_current_index = len(previous)
            for start in range(0, len(timeline) - window_length + 1):
                end = start + window_length
                if end <= first_current_index:
                    continue
                model.Add(sum(timeline[start:end]) <= rules.max_consecutive_days)

        # R07: previous Sunday evening and every current evening-to-morning pair.
        for employee_id in employee_ids:
            if facts.previous_sunday_evening(employee_id):
                model.Add(assignment_vars[(employee_id, Day.MON, Shift.MORNING)] == 0)
            for day_index in range(len(WEEK_DAYS) - 1):
                current_day = WEEK_DAYS[day_index]
                next_day = WEEK_DAYS[day_index + 1]
                model.Add(
                    assignment_vars[(employee_id, current_day, Shift.EVENING)]
                    + assignment_vars[(employee_id, next_day, Shift.MORNING)]
                    <= 1
                )

        preference_terms = [
            assignment_vars[(employee.id, day, facts.policies[employee.id].preferred_shift)]
            for employee in context.employees
            if facts.policies[employee.id].preferred_shift is not None
            for day in WEEK_DAYS
        ]

        workload_gap: cp_model.IntVar | None = None
        if employee_ids:
            workload_max = model.NewIntVar(0, rules.max_shifts_per_week, "workload_max")
            workload_min = model.NewIntVar(0, rules.max_shifts_per_week, "workload_min")
            model.AddMaxEquality(workload_max, list(workload_vars.values()))
            model.AddMinEquality(workload_min, list(workload_vars.values()))
            workload_gap = model.NewIntVar(0, rules.max_shifts_per_week, "workload_gap")
            model.Add(workload_gap == workload_max - workload_min)

        change_terms: list[cp_model.IntVar] = []
        if context.base_schedule is not None and context.minimize_changes:
            base_keys = facts.base_assignment_keys()
            for key, variable in assignment_vars.items():
                changed = model.NewBoolVar(
                    f"changed_{key[0]}_{key[1].value}_{key[2].value}"
                )
                if key in base_keys:
                    model.Add(changed + variable == 1)
                else:
                    model.Add(changed == variable)
                change_terms.append(changed)

        if diagnostic:
            total_shortage = sum(staffing_slacks.values())
            total_assignments = sum(assignment_vars.values())
            model.Minimize(10_000 * total_shortage + total_assignments)
        else:
            weights = rules.objective
            objective = weights.preference_reward * sum(preference_terms)
            if workload_gap is not None:
                objective -= weights.workload_gap_penalty * workload_gap
            if change_terms:
                objective -= weights.schedule_change_penalty * sum(change_terms)
            model.Maximize(objective)

        return BuiltSchedulingModel(
            model=model,
            assignment_vars=assignment_vars,
            workday_vars=workday_vars,
            workload_vars=workload_vars,
            staffing_slacks=staffing_slacks,
            facts=facts,
            preference_terms=preference_terms,
            change_terms=change_terms,
            workload_gap=workload_gap,
        )

    @staticmethod
    def _add_coverage(
        model: cp_model.CpModel,
        slacks: dict[CoverageKey, cp_model.IntVar],
        key: CoverageKey,
        variables: list[cp_model.IntVar],
        required: int,
        diagnostic: bool,
    ) -> None:
        if diagnostic:
            shortage = model.NewIntVar(0, required, f"shortage_{key[0]}_{key[1].value}_{key[2].value}")
            model.Add(sum(variables) + shortage >= required)
            slacks[key] = shortage
        else:
            model.Add(sum(variables) >= required)
